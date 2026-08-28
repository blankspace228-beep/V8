import math, statistics, json
from datetime import datetime, timezone, timedelta
import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

PROCESSORS=('trend','momentum','volatility','spread','diversification','behavior')
BASE_WEIGHTS={'trend':1.25,'momentum':1.15,'volatility':.80,'spread':.75,'diversification':.85,'behavior':.80}


def register(app, base):
    def ensure_tables():
        conn=base.db()
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS user_ai_settings(
          user_id INTEGER PRIMARY KEY,
          enabled INTEGER NOT NULL DEFAULT 1,
          mode TEXT NOT NULL DEFAULT 'copilot',
          risk_profile TEXT NOT NULL DEFAULT 'balanced',
          max_positions INTEGER NOT NULL DEFAULT 4,
          max_position_pct REAL NOT NULL DEFAULT 20,
          scan_interval INTEGER NOT NULL DEFAULT 30,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_ai_decisions(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          symbol TEXT,
          action TEXT NOT NULL,
          score REAL,
          confidence REAL,
          detail TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_ai_processor_memory(
          user_id INTEGER NOT NULL,
          processor TEXT NOT NULL,
          reliability REAL NOT NULL DEFAULT 1.0,
          observations INTEGER NOT NULL DEFAULT 0,
          correct REAL NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(user_id,processor)
        );
        CREATE TABLE IF NOT EXISTS user_ai_symbol_memory(
          user_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          visits INTEGER NOT NULL DEFAULT 0,
          ema_score REAL NOT NULL DEFAULT 50,
          last_score REAL,
          last_action TEXT,
          last_price REAL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(user_id,symbol)
        );
        CREATE TABLE IF NOT EXISTS user_ai_observations(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          score REAL NOT NULL,
          price REAL NOT NULL,
          processors TEXT NOT NULL,
          created_at TEXT NOT NULL,
          resolved INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS user_ai_working_memory(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          kind TEXT NOT NULL,
          symbol TEXT,
          payload TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        ''')
        for p in PROCESSORS:
            conn.execute('''INSERT OR IGNORE INTO user_ai_processor_memory(user_id,processor,reliability,observations,correct,updated_at)
                            SELECT id,?,1.0,0,0,? FROM users''',(p,base.now_iso()))
        conn.commit();conn.close()

    def settings(uid:int):
        ensure_tables();conn=base.db();r=conn.execute('SELECT * FROM user_ai_settings WHERE user_id=?',(uid,)).fetchone()
        if not r:
            conn.execute("INSERT INTO user_ai_settings(user_id,enabled,mode,risk_profile,max_positions,max_position_pct,scan_interval,updated_at) VALUES(?,1,'copilot','balanced',4,20,30,?)",(uid,base.now_iso()));conn.commit();r=conn.execute('SELECT * FROM user_ai_settings WHERE user_id=?',(uid,)).fetchone()
        for p in PROCESSORS:conn.execute('INSERT OR IGNORE INTO user_ai_processor_memory(user_id,processor,reliability,observations,correct,updated_at) VALUES(?,?,1,0,0,?)',(uid,p,base.now_iso()))
        conn.commit();out=dict(r);out['enabled']=bool(out['enabled']);conn.close();return out

    class SettingsReq(BaseModel):
        enabled:bool=True
        mode:str=Field(default='copilot')
        risk_profile:str=Field(default='balanced')
        max_positions:int=Field(default=4,ge=1,le=12)
        max_position_pct:float=Field(default=20,ge=2,le=60)
        scan_interval:int=Field(default=30,ge=10,le=300)
    class ScanReq(BaseModel): symbols:list[str]|None=None
    class ScaleReq(BaseModel): capital:float=Field(gt=0,le=100_000_000)
    class ExecuteReq(BaseModel): symbols:list[str]|None=None

    def pct(a,b):return ((a/b)-1)*100 if b else 0.0
    def clamp(x,a,b):return max(a,min(b,x))

    def processor_memory(uid:int):
        settings(uid);conn=base.db();rows=conn.execute('SELECT * FROM user_ai_processor_memory WHERE user_id=?',(uid,)).fetchall();conn.close()
        return {r['processor']:{'reliability':float(r['reliability']),'observations':int(r['observations']),'correct':float(r['correct'])} for r in rows}

    def symbol_memory(uid:int,symbol:str):
        conn=base.db();r=conn.execute('SELECT * FROM user_ai_symbol_memory WHERE user_id=? AND symbol=?',(uid,symbol)).fetchone();conn.close();return dict(r) if r else None

    def remember(uid:int,kind:str,symbol:str|None,payload:dict):
        conn=base.db();conn.execute('INSERT INTO user_ai_working_memory(user_id,kind,symbol,payload,created_at) VALUES(?,?,?,?,?)',(uid,kind,symbol,json.dumps(payload,separators=(',',':')),base.now_iso()))
        # bounded memory: the brain keeps only a compact recent working set
        conn.execute('''DELETE FROM user_ai_working_memory WHERE user_id=? AND id NOT IN
                        (SELECT id FROM user_ai_working_memory WHERE user_id=? ORDER BY id DESC LIMIT 80)''',(uid,uid));conn.commit();conn.close()

    async def history(symbol:str):
        if '/' in symbol or not base.API_KEY or not base.SECRET_KEY:return []
        headers={'APCA-API-KEY-ID':base.API_KEY,'APCA-API-SECRET-KEY':base.SECRET_KEY}
        end=datetime.now(timezone.utc);start=end-timedelta(days=8)
        params={'timeframe':'15Min','start':start.isoformat(),'end':end.isoformat(),'limit':80,'feed':'iex','adjustment':'raw','sort':'asc'}
        try:
            async with httpx.AsyncClient(timeout=6) as c:r=await c.get(f'{base.ALPACA_DATA}/stocks/{symbol}/bars',headers=headers,params=params)
            if r.status_code>=400:return []
            d=r.json();return d.get('bars',[]) if isinstance(d,dict) else []
        except Exception:return []

    def route_processors(raw:dict):
        # Sparse routing: always preserve safety gates, then select highest-salience market processors.
        must=[k for k in ('behavior','diversification','spread') if k in raw]
        ranked=sorted((k for k in raw if k not in must),key=lambda k:abs(raw[k]-50),reverse=True)
        chosen=(must+ranked)[:5]
        return {k:raw[k] for k in chosen}

    def recurrent_communication(active:dict):
        x=dict(active);links=[]
        # Trend and momentum reinforce agreement, inhibit disagreement.
        if 'trend' in x and 'momentum' in x:
            agreement=(x['trend']-50)*(x['momentum']-50)
            delta=4 if agreement>80 else -4 if agreement<-80 else 0
            if delta:
                x['trend']=clamp(x['trend']+delta,0,100);x['momentum']=clamp(x['momentum']+delta,0,100)
                links.append({'from':'trend','to':'momentum','effect':delta,'reason':'directional agreement' if delta>0 else 'directional conflict'})
        # High volatility suppresses momentum conviction rather than merely voting independently.
        if 'volatility' in x and 'momentum' in x and x['volatility']<45:
            d=min(10,(45-x['volatility'])*.35);x['momentum']=clamp(x['momentum']-d,0,100);links.append({'from':'volatility','to':'momentum','effect':round(-d,1),'reason':'unstable regime inhibits momentum'})
        # Poor execution quality gates otherwise attractive signals.
        if 'spread' in x and x['spread']<45:
            for k in ('trend','momentum'):
                if k in x:
                    d=min(8,(45-x['spread'])*.25);x[k]=clamp(x[k]-d,0,100);links.append({'from':'spread','to':k,'effect':round(-d,1),'reason':'execution friction gate'})
        # Behavioral stress creates global inhibition so the system can choose no-trade.
        if 'behavior' in x and x['behavior']<65:
            for k in ('trend','momentum'):
                if k in x:
                    d=min(9,(65-x['behavior'])*.28);x[k]=clamp(x[k]-d,0,100);links.append({'from':'behavior','to':k,'effect':round(-d,1),'reason':'behavioral-risk inhibition'})
        return {k:round(v,1) for k,v in x.items()},links

    def analyze_symbol(uid:int,symbol:str,bars:list[dict],acct:dict,behavior:dict,mem:dict):
        price=float(base.latest_prices.get(symbol) or 0);closes=[float(x.get('c') or 0) for x in bars if x.get('c')]
        raw={};reasons=[]
        if len(closes)>=20:
            fast=sum(closes[-5:])/5;slow=sum(closes[-20:])/20;raw['trend']=50+clamp((fast/slow-1)*1200,-35,35);reasons.append(('Trend','short trend above long trend' if fast>slow else 'short trend below long trend'))
        if len(closes)>=8:
            mom=pct(closes[-1],closes[-6]);raw['momentum']=50+clamp(mom*4,-35,35);reasons.append(('Momentum',f'{mom:+.2f}% over recent bars'))
        if len(closes)>=12:
            rets=[(closes[i]/closes[i-1]-1)*100 for i in range(1,len(closes)) if closes[i-1]];vol=statistics.pstdev(rets[-20:]) if rets else 0;raw['volatility']=75-clamp(abs(vol-.55)*28,0,45);reasons.append(('Volatility',f'{vol:.2f}% recent bar volatility'))
        q=base.latest_quotes.get(symbol) or {};bid=float(q.get('bid') or 0);ask=float(q.get('ask') or 0)
        if bid and ask and price:
            sp=(ask-bid)/price*100;raw['spread']=90-clamp(sp*120,0,55);reasons.append(('Spread',f'{sp:.3f}% quoted spread'))
        held=next((p for p in acct.get('positions',[]) if p['symbol']==symbol),None);conc=(held['market_value']/acct['equity']*100) if held and acct.get('equity') else 0;raw['diversification']=80-clamp(conc*1.8,0,55)
        penalty=(8 if behavior.get('loss_streak',0)>=2 else 0)+(7 if behavior.get('size_escalations',0) else 0);raw['behavior']=82-penalty
        raw={k:round(clamp(v,0,100),1) for k,v in raw.items()};active=route_processors(raw);active,links=recurrent_communication(active)
        weights={};num=den=0.0
        for k,v in active.items():
            reliability=mem.get(k,{}).get('reliability',1.0);w=BASE_WEIGHTS[k]*reliability;weights[k]=round(w,3);num+=v*w;den+=w
        score=num/den if den else 50
        # A tiny recurrent prior from this symbol's own recent history; intentionally bounded.
        sm=symbol_memory(uid,symbol)
        if sm and int(sm.get('visits') or 0)>=2:score=score*.90+float(sm.get('ema_score') or 50)*.10
        score=round(clamp(score,0,100),1);conf=clamp(34+len(active)*9+(12 if len(closes)>=20 else 0),35,96)
        reliability_mean=sum(mem.get(k,{}).get('reliability',1) for k in active)/max(1,len(active));conf=round(clamp(conf*clamp(reliability_mean,.75,1.15),30,97),1)
        action='BUY' if score>=68 and active.get('behavior',100)>=60 else 'WATCH' if score>=54 else 'AVOID' if score>=40 else 'REDUCE'
        return {'symbol':symbol,'price':price,'score':score,'confidence':conf,'action':action,'processors':active,'raw_processors':raw,'processor_weights':weights,'processor_count':len(active),'communication':links,'memory':{'visits':int(sm['visits']) if sm else 0,'ema_score':round(float(sm['ema_score']),1) if sm else None},'reasons':[{'title':a,'text':b} for a,b in reasons[:4]]}

    def persist_scan(uid:int,c:dict):
        conn=base.db();old=conn.execute('SELECT * FROM user_ai_symbol_memory WHERE user_id=? AND symbol=?',(uid,c['symbol'])).fetchone();visits=int(old['visits'])+1 if old else 1;ema=(float(old['ema_score'])*.78+c['score']*.22) if old else c['score']
        conn.execute('''INSERT INTO user_ai_symbol_memory(user_id,symbol,visits,ema_score,last_score,last_action,last_price,updated_at) VALUES(?,?,?,?,?,?,?,?)
                        ON CONFLICT(user_id,symbol) DO UPDATE SET visits=excluded.visits,ema_score=excluded.ema_score,last_score=excluded.last_score,last_action=excluded.last_action,last_price=excluded.last_price,updated_at=excluded.updated_at''',(uid,c['symbol'],visits,ema,c['score'],c['action'],c['price'],base.now_iso()))
        # one unresolved learning sample per symbol at a time prevents runaway DB growth
        unresolved=conn.execute('SELECT 1 FROM user_ai_observations WHERE user_id=? AND symbol=? AND resolved=0',(uid,c['symbol'])).fetchone()
        if not unresolved and c['price']>0:conn.execute('INSERT INTO user_ai_observations(user_id,symbol,score,price,processors,created_at,resolved) VALUES(?,?,?,?,?,?,0)',(uid,c['symbol'],c['score'],c['price'],json.dumps(c['processors'],separators=(',',':')),base.now_iso()))
        conn.commit();conn.close()

    def consolidate(uid:int):
        # Sleep-like micro-consolidation: resolve aged predictions against a later observed price.
        conn=base.db();cut=(datetime.now(timezone.utc)-timedelta(minutes=45)).isoformat();rows=conn.execute('SELECT * FROM user_ai_observations WHERE user_id=? AND resolved=0 AND created_at<? ORDER BY id LIMIT 20',(uid,cut)).fetchall();updates=0
        for r in rows:
            nowp=float(base.latest_prices.get(r['symbol']) or 0)
            if not nowp or not float(r['price']):continue
            move=(nowp/float(r['price'])-1)*100;bull=float(r['score'])>=56;correct=(move>0 if bull else move<=0);processors=json.loads(r['processors'] or '{}')
            for p,val in processors.items():
                pr=conn.execute('SELECT * FROM user_ai_processor_memory WHERE user_id=? AND processor=?',(uid,p)).fetchone();rel=float(pr['reliability']) if pr else 1.0;obs=int(pr['observations']) if pr else 0;good=float(pr['correct']) if pr else 0
                # credit is stronger when processor conviction agreed with fused direction
                aligned=(float(val)>=50)==bull;credit=1.0 if correct and aligned else .65 if correct else .35 if not aligned else 0.0;good+=credit;obs+=1;target=.78+(good/obs)*.44;rel=clamp(rel*.88+target*.12,.72,1.22)
                conn.execute('''INSERT INTO user_ai_processor_memory(user_id,processor,reliability,observations,correct,updated_at) VALUES(?,?,?,?,?,?)
                                ON CONFLICT(user_id,processor) DO UPDATE SET reliability=excluded.reliability,observations=excluded.observations,correct=excluded.correct,updated_at=excluded.updated_at''',(uid,p,rel,obs,good,base.now_iso()))
            conn.execute('UPDATE user_ai_observations SET resolved=1 WHERE id=?',(r['id'],));updates+=1
        conn.execute('''DELETE FROM user_ai_observations WHERE user_id=? AND id NOT IN
                        (SELECT id FROM user_ai_observations WHERE user_id=? ORDER BY id DESC LIMIT 500)''',(uid,uid));conn.commit();conn.close();return updates

    async def scan(uid:int,requested:list[str]|None=None):
        acct=base.account_snapshot(uid);behavior=base.adaptive_coach_metrics(uid);cfg=settings(uid);consolidated=consolidate(uid);mem=processor_memory(uid)
        symbols=requested or ['AAPL','MSFT','NVDA','AMZN','META','TSLA','SPY','AMD'];symbols=[s.strip().upper() for s in symbols if s and len(s)<=16][:12];out=[]
        for s in symbols:
            if '/' in s:await base.fetch_crypto_snapshot(s)
            else:await base.fetch_latest_snapshot(s)
            c=analyze_symbol(uid,s,await history(s),acct,behavior,mem);out.append(c);persist_scan(uid,c)
        out.sort(key=lambda x:x['score'],reverse=True);remember(uid,'scan',None,{'top':[(x['symbol'],x['score'],x['action']) for x in out[:4]],'consolidated':consolidated})
        return {'engine':'Purple Adaptive Sparse Cognitive Mesh V8.5','mode':cfg['mode'],'ram_design':'bounded SQLite memory + sparse numeric processors; no resident language model','active_processors_max':5,'processor_reliability':{k:round(v['reliability'],3) for k,v in mem.items()},'consolidated_observations':consolidated,'candidates':out,'account':{'equity':acct['equity'],'cash':acct['cash'],'positions':len(acct['positions'])},'behavior':{'loss_streak':behavior.get('loss_streak',0),'size_escalations':behavior.get('size_escalations',0)}}

    def target_pct(cfg,score):
        bp={'conservative':10,'balanced':15,'aggressive':20}.get(cfg['risk_profile'],15);return min(float(cfg['max_position_pct']),bp+max(0,(score-70))*.18)

    def log_decision(uid,symbol,action,score,confidence,detail):
        conn=base.db();conn.execute('INSERT INTO user_ai_decisions(user_id,symbol,action,score,confidence,detail,created_at) VALUES(?,?,?,?,?,?,?)',(uid,symbol,action,score,confidence,detail,base.now_iso()));conn.commit();conn.close();remember(uid,'decision',symbol,{'action':action,'score':score,'confidence':confidence})

    async def execute_plan(uid:int,result:dict,cfg:dict):
        acct=base.account_snapshot(uid);positions={p['symbol']:p for p in acct['positions']};actions=[]
        for c in result['candidates']:
            if c['symbol'] in positions and c['score']<38:
                p=positions[c['symbol']];qty=float(p['qty']);price=float(base.latest_prices.get(c['symbol']) or p['price'])
                if qty>0 and price>0:
                    conn=base.db();cur=conn.execute("INSERT INTO user_orders(user_id,symbol,side,order_type,qty,status,submitted_at,note) VALUES(?,?, 'sell','market',?,'open',?,'Purple AI simulator autopilot')",(uid,c['symbol'],qty,base.now_iso()));oid=cur.lastrowid;conn.commit();conn.close();ok,msg=base.execute_fill(uid,oid,c['symbol'],'sell',qty,base.simulated_fill_price(c['symbol'],'sell',price));actions.append({'symbol':c['symbol'],'side':'sell','qty':qty,'ok':ok,'message':msg});log_decision(uid,c['symbol'],'AUTO_SELL',c['score'],c['confidence'],'Adaptive-mesh weak-score rebalance')
        acct=base.account_snapshot(uid);positions={p['symbol']:p for p in acct['positions']};slots=max(0,int(cfg['max_positions'])-len(positions))
        for c in [x for x in result['candidates'] if x['score']>=68 and x['action']=='BUY'][:slots]:
            if c['symbol'] in positions:continue
            price=float(base.latest_prices.get(c['symbol']) or 0)
            if not price:continue
            alloc=min(acct['equity']*target_pct(cfg,c['score'])/100,acct['cash']*.92);qty=math.floor((alloc/price)*1000)/1000
            if qty<=0:continue
            conn=base.db();cur=conn.execute("INSERT INTO user_orders(user_id,symbol,side,order_type,qty,status,submitted_at,note) VALUES(?,?, 'buy','market',?,'open',?,'Purple AI simulator autopilot')",(uid,c['symbol'],qty,base.now_iso()));oid=cur.lastrowid;conn.commit();conn.close();ok,msg=base.execute_fill(uid,oid,c['symbol'],'buy',qty,base.simulated_fill_price(c['symbol'],'buy',price));actions.append({'symbol':c['symbol'],'side':'buy','qty':qty,'allocation':alloc,'ok':ok,'message':msg});log_decision(uid,c['symbol'],'AUTO_BUY',c['score'],c['confidence'],f'Adaptive sparse-brain score {c["score"]}');acct=base.account_snapshot(uid)
        return actions

    @app.get('/api/ai/settings')
    async def ai_settings(request:Request):return settings(base.current_user_id(request))

    @app.post('/api/ai/settings')
    async def ai_settings_save(req:SettingsReq,request:Request):
        uid=base.current_user_id(request);mode=req.mode.lower();risk=req.risk_profile.lower()
        if mode not in {'manual','copilot','autopilot'}:raise HTTPException(400,'Mode must be manual, copilot, or autopilot')
        if risk not in {'conservative','balanced','aggressive'}:raise HTTPException(400,'Unknown risk profile')
        ensure_tables();conn=base.db();conn.execute('''INSERT INTO user_ai_settings(user_id,enabled,mode,risk_profile,max_positions,max_position_pct,scan_interval,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,mode=excluded.mode,risk_profile=excluded.risk_profile,max_positions=excluded.max_positions,max_position_pct=excluded.max_position_pct,scan_interval=excluded.scan_interval,updated_at=excluded.updated_at''',(uid,1 if req.enabled else 0,mode,risk,req.max_positions,req.max_position_pct,req.scan_interval,base.now_iso()));conn.commit();conn.close();return settings(uid)

    @app.post('/api/ai/scan')
    async def ai_scan(req:ScanReq,request:Request):return await scan(base.current_user_id(request),req.symbols)

    @app.post('/api/ai/build-plan')
    async def ai_build(req:ScanReq,request:Request):
        uid=base.current_user_id(request);cfg=settings(uid);r=await scan(uid,req.symbols);picks=[]
        for c in [x for x in r['candidates'] if x['score']>=60][:int(cfg['max_positions'])]:
            pp=target_pct(cfg,c['score']);picks.append({**c,'target_pct':round(pp,1),'target_fake_dollars':round(r['account']['equity']*pp/100,2)})
        return {'mode':cfg['mode'],'risk_profile':cfg['risk_profile'],'picks':picks,'note':'Simulator portfolio plan. No brokerage order is sent.'}

    @app.post('/api/ai/autopilot/run')
    async def ai_autopilot(req:ExecuteReq,request:Request):
        uid=base.current_user_id(request);cfg=settings(uid)
        if not cfg['enabled'] or cfg['mode']!='autopilot':raise HTTPException(409,'Enable AI and select AUTOPILOT first')
        r=await scan(uid,req.symbols);actions=await execute_plan(uid,r,cfg);return {'ok':True,'actions':actions,'scan':r,'account':base.account_snapshot(uid),'simulation_only':True}

    @app.post('/api/ai/real-scale')
    async def ai_real_scale(req:ScaleReq,request:Request):
        uid=base.current_user_id(request);cfg=settings(uid);r=await scan(uid,None);rows=[]
        for c in [x for x in r['candidates'] if x['score']>=60][:int(cfg['max_positions'])]:
            pp=target_pct(cfg,c['score']);d=req.capital*pp/100;rows.append({'symbol':c['symbol'],'target_pct':round(pp,1),'equivalent_dollars':round(d,2),'approx_shares':round(d/c['price'],4) if c['price'] else 0,'score':c['score']})
        return {'capital':req.capital,'allocations':rows,'educational_only':True,'note':'This translates the simulator plan into equivalent dollar sizing only. It does not connect to or trade a real brokerage account.'}

    @app.get('/api/ai/history')
    async def ai_history(request:Request):
        uid=base.current_user_id(request);ensure_tables();conn=base.db();rows=[dict(r) for r in conn.execute('SELECT * FROM user_ai_decisions WHERE user_id=? ORDER BY id DESC LIMIT 40',(uid,)).fetchall()];conn.close();return rows

    @app.get('/api/ai/brain')
    async def ai_brain(request:Request):
        uid=base.current_user_id(request);mem=processor_memory(uid);conn=base.db();working=[dict(r) for r in conn.execute('SELECT * FROM user_ai_working_memory WHERE user_id=? ORDER BY id DESC LIMIT 12',(uid,)).fetchall()];symbols=[dict(r) for r in conn.execute('SELECT * FROM user_ai_symbol_memory WHERE user_id=? ORDER BY visits DESC,updated_at DESC LIMIT 12',(uid,)).fetchall()];pending=conn.execute('SELECT COUNT(*) c FROM user_ai_observations WHERE user_id=? AND resolved=0',(uid,)).fetchone()['c'];resolved=conn.execute('SELECT COUNT(*) c FROM user_ai_observations WHERE user_id=? AND resolved=1',(uid,)).fetchone()['c'];conn.close()
        return {'engine':'Purple Adaptive Sparse Cognitive Mesh V8.5','architecture':{'processor_pool':len(PROCESSORS),'max_active_per_symbol':5,'memory_model':'bounded working + symbol EMA + processor metaplasticity','resident_llm':False},'processors':{k:{'reliability':round(v['reliability'],3),'observations':v['observations'],'learned_credit':round(v['correct'],2)} for k,v in mem.items()},'learning':{'pending_observations':pending,'resolved_observations':resolved},'symbol_memory':symbols,'working_memory':working}
