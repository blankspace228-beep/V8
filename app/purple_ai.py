import math, statistics
from datetime import datetime, timezone, timedelta
from typing import Any
import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field


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
        ''');conn.commit();conn.close()

    def settings(uid:int):
        ensure_tables();conn=base.db();r=conn.execute('SELECT * FROM user_ai_settings WHERE user_id=?',(uid,)).fetchone()
        if not r:
            conn.execute("INSERT INTO user_ai_settings(user_id,enabled,mode,risk_profile,max_positions,max_position_pct,scan_interval,updated_at) VALUES(?,1,'copilot','balanced',4,20,30,?)",(uid,base.now_iso()));conn.commit();r=conn.execute('SELECT * FROM user_ai_settings WHERE user_id=?',(uid,)).fetchone()
        out=dict(r);out['enabled']=bool(out['enabled']);conn.close();return out

    class SettingsReq(BaseModel):
        enabled:bool=True
        mode:str=Field(default='copilot')
        risk_profile:str=Field(default='balanced')
        max_positions:int=Field(default=4,ge=1,le=12)
        max_position_pct:float=Field(default=20,ge=2,le=60)
        scan_interval:int=Field(default=30,ge=10,le=300)
    class ScanReq(BaseModel):
        symbols:list[str]|None=None
    class ScaleReq(BaseModel):
        capital:float=Field(gt=0,le=100_000_000)
    class ExecuteReq(BaseModel):
        symbols:list[str]|None=None

    def pct(a,b): return ((a/b)-1)*100 if b else 0.0
    def clamp(x,a,b): return max(a,min(b,x))

    async def history(symbol:str):
        if '/' in symbol or not base.API_KEY or not base.SECRET_KEY:return []
        headers={'APCA-API-KEY-ID':base.API_KEY,'APCA-API-SECRET-KEY':base.SECRET_KEY}
        end=datetime.now(timezone.utc);start=end-timedelta(days=8)
        params={'timeframe':'15Min','start':start.isoformat(),'end':end.isoformat(),'limit':80,'feed':'iex','adjustment':'raw','sort':'asc'}
        try:
            async with httpx.AsyncClient(timeout=6) as c:r=await c.get(f'{base.ALPACA_DATA}/stocks/{symbol}/bars',headers=headers,params=params)
            if r.status_code>=400:return []
            return r.json().get('bars',[]) if isinstance(r.json(),dict) else []
        except Exception:return []

    def analyze_symbol(symbol:str,bars:list[dict],snap:dict,acct:dict,behavior:dict):
        price=float(base.latest_prices.get(symbol) or 0)
        closes=[float(x.get('c') or 0) for x in bars if x.get('c')]
        active={};reasons=[]
        # Sparse processor 1: trend
        if len(closes)>=20:
            fast=sum(closes[-5:])/5;slow=sum(closes[-20:])/20
            raw=50+clamp((fast/slow-1)*1200,-35,35);active['trend']=round(raw,1)
            reasons.append(('Trend','short trend above long trend' if fast>slow else 'short trend below long trend'))
        # Sparse processor 2: momentum
        if len(closes)>=8:
            mom=pct(closes[-1],closes[-6]);raw=50+clamp(mom*4,-35,35);active['momentum']=round(raw,1)
            reasons.append(('Momentum',f'{mom:+.2f}% over recent bars'))
        # Sparse processor 3: volatility quality
        if len(closes)>=12:
            rets=[(closes[i]/closes[i-1]-1)*100 for i in range(1,len(closes)) if closes[i-1]]
            vol=statistics.pstdev(rets[-20:]) if rets else 0
            raw=75-clamp(abs(vol-0.55)*28,0,45);active['volatility']=round(raw,1)
            reasons.append(('Volatility',f'{vol:.2f}% recent bar volatility'))
        # Sparse processor 4: execution quality / spread
        q=base.latest_quotes.get(symbol) or {};bid=float(q.get('bid') or 0);ask=float(q.get('ask') or 0)
        if bid and ask and price:
            sp=(ask-bid)/price*100;raw=90-clamp(sp*120,0,55);active['spread']=round(raw,1)
            reasons.append(('Spread',f'{sp:.3f}% quoted spread'))
        # Sparse processor 5: diversification
        held=next((p for p in acct.get('positions',[]) if p['symbol']==symbol),None)
        conc=(held['market_value']/acct['equity']*100) if held and acct.get('equity') else 0
        active['diversification']=round(80-clamp(conc*1.8,0,55),1)
        # Sparse processor 6: behavioral state
        penalty=0
        if behavior.get('loss_streak',0)>=2:penalty+=8
        if behavior.get('size_escalations',0):penalty+=7
        active['behavior']=round(82-penalty,1)
        weights={'trend':1.25,'momentum':1.15,'volatility':.8,'spread':.75,'diversification':.85,'behavior':.8}
        num=sum(active[k]*weights[k] for k in active);den=sum(weights[k] for k in active);score=num/den if den else 50
        score=round(clamp(score,0,100),1)
        conf=round(clamp(38+len(active)*8+(12 if len(closes)>=20 else 0),35,96),1)
        action='BUY' if score>=67 else 'WATCH' if score>=54 else 'AVOID' if score>=40 else 'REDUCE'
        return {'symbol':symbol,'price':price,'score':score,'confidence':conf,'action':action,'processors':active,'processor_count':len(active),'reasons':[{'title':a,'text':b} for a,b in reasons[:4]]}

    async def scan(uid:int, requested:list[str]|None=None):
        acct=base.account_snapshot(uid);behavior=base.adaptive_coach_metrics(uid);cfg=settings(uid)
        symbols=requested or ['AAPL','MSFT','NVDA','AMZN','META','TSLA','SPY','AMD']
        symbols=[s.strip().upper() for s in symbols if s and len(s)<=16][:12]
        out=[]
        for s in symbols:
            if '/' in s:
                await base.fetch_crypto_snapshot(s)
            else:
                await base.fetch_latest_snapshot(s)
            bars=await history(s)
            out.append(analyze_symbol(s,bars,base.latest_quotes.get(s) or {},acct,behavior))
        out.sort(key=lambda x:x['score'],reverse=True)
        return {'engine':'Purple Sparse Cognitive Mesh','mode':cfg['mode'],'ram_design':'stateless sparse processors; no resident language model','active_processors_max':6,'candidates':out,'account':{'equity':acct['equity'],'cash':acct['cash'],'positions':len(acct['positions'])},'behavior':{'loss_streak':behavior.get('loss_streak',0),'size_escalations':behavior.get('size_escalations',0)}}

    def target_pct(cfg,score):
        base_pct={'conservative':10,'balanced':15,'aggressive':20}.get(cfg['risk_profile'],15)
        return min(float(cfg['max_position_pct']),base_pct+max(0,(score-70))*.18)

    def log_decision(uid,symbol,action,score,confidence,detail):
        conn=base.db();conn.execute('INSERT INTO user_ai_decisions(user_id,symbol,action,score,confidence,detail,created_at) VALUES(?,?,?,?,?,?,?)',(uid,symbol,action,score,confidence,detail,base.now_iso()));conn.commit();conn.close()

    async def execute_plan(uid:int, result:dict, cfg:dict):
        acct=base.account_snapshot(uid);positions={p['symbol']:p for p in acct['positions']};actions=[]
        # sell weak held positions first
        for c in result['candidates']:
            if c['symbol'] in positions and c['score']<38:
                p=positions[c['symbol']];qty=float(p['qty']);price=float(base.latest_prices.get(c['symbol']) or p['price'])
                if qty>0 and price>0:
                    conn=base.db();cur=conn.execute("INSERT INTO user_orders(user_id,symbol,side,order_type,qty,status,submitted_at,note) VALUES(?,?, 'sell','market',?,'open',?,'Purple AI simulator autopilot')",(uid,c['symbol'],qty,base.now_iso()));oid=cur.lastrowid;conn.commit();conn.close();ok,msg=base.execute_fill(uid,oid,c['symbol'],'sell',qty,base.simulated_fill_price(c['symbol'],'sell',price));actions.append({'symbol':c['symbol'],'side':'sell','qty':qty,'ok':ok,'message':msg});log_decision(uid,c['symbol'],'AUTO_SELL',c['score'],c['confidence'],'Weak-score simulator rebalance')
        acct=base.account_snapshot(uid);positions={p['symbol']:p for p in acct['positions']}
        slots=max(0,int(cfg['max_positions'])-len(positions))
        for c in [x for x in result['candidates'] if x['score']>=68][:slots]:
            if c['symbol'] in positions:continue
            price=float(base.latest_prices.get(c['symbol']) or 0)
            if not price:continue
            alloc=acct['equity']*target_pct(cfg,c['score'])/100
            alloc=min(alloc,acct['cash']*.92)
            qty=math.floor((alloc/price)*1000)/1000
            if qty<=0:continue
            conn=base.db();cur=conn.execute("INSERT INTO user_orders(user_id,symbol,side,order_type,qty,status,submitted_at,note) VALUES(?,?, 'buy','market',?,'open',?,'Purple AI simulator autopilot')",(uid,c['symbol'],qty,base.now_iso()));oid=cur.lastrowid;conn.commit();conn.close();ok,msg=base.execute_fill(uid,oid,c['symbol'],'buy',qty,base.simulated_fill_price(c['symbol'],'buy',price));actions.append({'symbol':c['symbol'],'side':'buy','qty':qty,'allocation':alloc,'ok':ok,'message':msg});log_decision(uid,c['symbol'],'AUTO_BUY',c['score'],c['confidence'],f'Sparse-brain score {c["score"]}')
            acct=base.account_snapshot(uid)
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
    async def ai_scan(req:ScanReq,request:Request):
        uid=base.current_user_id(request);return await scan(uid,req.symbols)

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
