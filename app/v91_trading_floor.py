import json
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

AGENTS=[
 ('Maya','Lead Trader','Find the strongest actionable edge'),
 ('Theo','Trend Desk','Judge continuation and structure'),
 ('Mina','Momentum Desk','Measure acceleration and follow-through'),
 ('Victor','Volatility Desk','Challenge trades that cannot survive noise'),
 ('Lena','Liquidity Desk','Check execution quality and spread'),
 ('Drew','Diversification Desk','Protect against hidden concentration'),
 ('Rhea','Risk Manager','Stress the idea before capital is committed'),
 ('Quinn','Contrarian','Argue the strongest case against consensus'),
 ('Sage','Behavior Officer','Stop emotion or chasing from becoming a trade'),
 ('Iris','Scenario Analyst','Compare multiple hypothetical futures'),
]


def register(app, base):
    def clamp(x,a,b): return max(a,min(b,x))
    scan_ep=next((r.endpoint for r in app.router.routes if getattr(r,'path',None)=='/api/ai/scan' and 'POST' in getattr(r,'methods',set())),None)

    def ensure_tables():
        conn=base.db();conn.executescript('''
        CREATE TABLE IF NOT EXISTS user_ai_agent_reputation(
          user_id INTEGER NOT NULL,
          agent TEXT NOT NULL,
          regime TEXT NOT NULL,
          reliability REAL NOT NULL DEFAULT 1.0,
          observations INTEGER NOT NULL DEFAULT 0,
          credit REAL NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(user_id,agent,regime)
        );
        CREATE TABLE IF NOT EXISTS user_ai_agent_observations(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          agent TEXT NOT NULL,
          stance TEXT NOT NULL,
          evidence REAL NOT NULL,
          price REAL NOT NULL,
          regime TEXT NOT NULL,
          created_at TEXT NOT NULL,
          resolved INTEGER NOT NULL DEFAULT 0
        );
        ''');conn.commit();conn.close()

    async def scan(request,symbol):
        if not scan_ep: raise HTTPException(503,'Sparse AI scan unavailable')
        d=await scan_ep(SimpleNamespace(symbols=[symbol]),request)
        return next((x for x in d.get('candidates',[]) if x.get('symbol')==symbol),None)

    def global_context(uid):
        conn=base.db();row=None
        try:row=conn.execute('SELECT * FROM user_ai_global_attention_events WHERE user_id=? ORDER BY id DESC LIMIT 1',(uid,)).fetchone()
        except Exception:pass
        conn.close();return dict(row) if row else None

    def regime(uid,c):
        g=global_context(uid) or {};focus=str(g.get('focus') or 'baseline')
        vol=float((c.get('processors') or {}).get('volatility',55) or 55)
        if focus in ('risk_off_breadth','volatility_regime','correlation_spike','portfolio_cluster_risk'):return 'defensive'
        if focus=='risk_on_breadth':return 'risk_on'
        if vol<45:return 'high_volatility'
        if float(c.get('score') or 50)>=70:return 'strong_setup'
        return 'baseline'

    def rep(uid,agent,rg):
        ensure_tables();conn=base.db();r=conn.execute('SELECT * FROM user_ai_agent_reputation WHERE user_id=? AND agent=? AND regime=?',(uid,agent,rg)).fetchone();conn.close()
        return {'reliability':float(r['reliability']) if r else 1.0,'observations':int(r['observations']) if r else 0,'credit':float(r['credit']) if r else 0.0}

    def consolidate(uid):
        ensure_tables();conn=base.db();cut=(datetime.now(timezone.utc)-timedelta(minutes=45)).isoformat();rows=conn.execute('SELECT * FROM user_ai_agent_observations WHERE user_id=? AND resolved=0 AND created_at<? ORDER BY id LIMIT 80',(uid,cut)).fetchall();resolved=0
        for r in rows:
            nowp=float(base.latest_prices.get(r['symbol']) or 0);old=float(r['price'] or 0)
            if not nowp or not old:continue
            move=(nowp/old-1)*100;stance=str(r['stance']);correct=None
            if stance=='BUY':correct=move>0
            elif stance in ('NO TRADE','CHALLENGE'):correct=move<=0
            if correct is None:
                conn.execute('UPDATE user_ai_agent_observations SET resolved=1 WHERE id=?',(r['id'],));resolved+=1;continue
            rr=conn.execute('SELECT * FROM user_ai_agent_reputation WHERE user_id=? AND agent=? AND regime=?',(uid,r['agent'],r['regime'])).fetchone();obs=int(rr['observations']) if rr else 0;credit=float(rr['credit']) if rr else 0;rel=float(rr['reliability']) if rr else 1.0
            conviction=abs(float(r['evidence'])-50)/50;gain=(1.0 if correct else 0.0)*(.7+.3*conviction);credit+=gain;obs+=1;target=.72+(credit/max(1,obs))*.56;rel=clamp(rel*.86+target*.14,.72,1.28)
            conn.execute('''INSERT INTO user_ai_agent_reputation(user_id,agent,regime,reliability,observations,credit,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,agent,regime) DO UPDATE SET reliability=excluded.reliability,observations=excluded.observations,credit=excluded.credit,updated_at=excluded.updated_at''',(uid,r['agent'],r['regime'],rel,obs,credit,base.now_iso()))
            conn.execute('UPDATE user_ai_agent_observations SET resolved=1 WHERE id=?',(r['id'],));resolved+=1
        conn.execute('''DELETE FROM user_ai_agent_observations WHERE user_id=? AND id NOT IN (SELECT id FROM user_ai_agent_observations WHERE user_id=? ORDER BY id DESC LIMIT 800)''',(uid,uid));conn.commit();conn.close();return resolved

    def observe(uid,c,agents,rg):
        price=float(c.get('price') or base.latest_prices.get(c.get('symbol')) or 0)
        if not price:return
        ensure_tables();conn=base.db()
        for a in agents:
            if a['stance'] not in ('BUY','NO TRADE','CHALLENGE'):continue
            exists=conn.execute('SELECT 1 FROM user_ai_agent_observations WHERE user_id=? AND symbol=? AND agent=? AND resolved=0',(uid,c['symbol'],a['agent'])).fetchone()
            if not exists:conn.execute('INSERT INTO user_ai_agent_observations(user_id,symbol,agent,stance,evidence,price,regime,created_at,resolved) VALUES(?,?,?,?,?,?,?,?,0)',(uid,c['symbol'],a['agent'],a['stance'],a['evidence_score'],price,rg,base.now_iso()))
        conn.commit();conn.close()

    def floor_debate(uid,c,acct,route,img):
        consolidate(uid);p=c.get('processors') or {};score=float(c.get('score') or 50);conf=float(c.get('confidence') or 50);robust=float(img.get('robustness_score') or 50);auth=float(route.get('execution_authority') or 0);rg=regime(uid,c)
        raw_scores={'Maya':clamp(score*.62+conf*.18+auth*.20,0,100),'Theo':float(p.get('trend',50)),'Mina':float(p.get('momentum',50)),'Victor':float(p.get('volatility',50)),'Lena':float(p.get('spread',50)),'Drew':float(p.get('diversification',50)),'Rhea':robust,'Quinn':clamp(100-score*.55-robust*.25+35,0,100),'Sage':float(p.get('behavior',50)),'Iris':robust}
        transcript=[];weighted_support=weighted_oppose=weighted_total=0.0
        for name,role,mission in AGENTS:
            raw=raw_scores[name];memory=rep(uid,name,rg);rel=memory['reliability'];adjusted=clamp(50+(raw-50)*rel,0,100)
            stance='BUY' if adjusted>=68 else 'WAIT' if adjusted>=48 else 'NO TRADE'
            if role=='Contrarian':stance='CHALLENGE' if score>=62 else 'WAIT'
            text=f'{mission}. Current evidence {raw:.0f}/100. My learned influence in {rg.replace("_"," ")} conditions is x{rel:.2f}.'
            if stance=='BUY':text+=' I support the simulated long inside the existing risk gates.'
            elif stance=='NO TRADE':text+=' I do not think the edge compensates for the current risk.'
            elif stance=='CHALLENGE':text+=' The floor is leaning bullish, so I am attacking the thesis before fake capital is committed.'
            else:text+=' I want more confirmation.'
            transcript.append({'agent':name,'role':role,'stance':stance,'message':text,'evidence_score':round(raw,1),'adjusted_score':round(adjusted,1),'reputation':round(rel,3),'reputation_observations':memory['observations'],'regime':rg})
            weight=rel;weighted_total+=weight
            if stance=='BUY':weighted_support+=weight
            elif stance in ('NO TRADE','CHALLENGE'):weighted_oppose+=weight
        support_ratio=weighted_support/max(.001,weighted_total);oppose_ratio=weighted_oppose/max(.001,weighted_total)
        big_idea=score>=78 and robust>=68 and auth>=65
        if big_idea:
            transcript.append({'agent':'Maya','role':'Lead Trader','stance':'PROPOSAL','message':'High-conviction proposal detected. Every desk gets another chance to challenge it before the simulator can increase conviction.','evidence_score':round((score+robust+auth)/3,1),'adjusted_score':round((score+robust+auth)/3,1),'reputation':rep(uid,'Maya',rg)['reliability'],'regime':rg})
            transcript.append({'agent':'Rhea','role':'Risk Manager','stance':'REVIEW','message':f'Robustness is {robust:.0f}/100. A high-upside idea still cannot bypass size limits, concentration controls, or downside review.','evidence_score':robust,'adjusted_score':robust,'reputation':rep(uid,'Rhea',rg)['reliability'],'regime':rg})
            transcript.append({'agent':'Quinn','role':'Contrarian','stance':'CHALLENGE','message':'I am deliberately opposing the exciting story. The setup must survive bearish scenarios before the floor treats it as exceptional.','evidence_score':round(100-score*.5,1),'adjusted_score':round(100-score*.5,1),'reputation':rep(uid,'Quinn',rg)['reliability'],'regime':rg})
        permission='ALLOW'
        if route.get('permission')=='BLOCK_NEW_BUY' or img.get('permission')=='BLOCK_NEW_BUY':permission='BLOCK_NEW_BUY'
        elif robust<52 or auth<48 or oppose_ratio>.34:permission='REQUIRE_REVIEW'
        consensus=clamp(score*.24+robust*.28+auth*.22+support_ratio*26-oppose_ratio*10,0,100)
        if permission=='ALLOW' and consensus<58:permission='REQUIRE_REVIEW'
        conviction='HIGH' if consensus>=76 and big_idea else 'MEDIUM' if consensus>=60 else 'LOW'
        observe(uid,c,[a for a in transcript if a.get('agent') in raw_scores],rg)
        return {'symbol':c['symbol'],'agents':transcript,'vote_summary':{'weighted_support_pct':round(support_ratio*100,1),'weighted_oppose_pct':round(oppose_ratio*100,1)},'consensus_score':round(consensus,1),'conviction':conviction,'big_idea_flag':big_idea,'permission':permission,'regime':rg,'final_statement':('Floor consensus supports a simulated trade within existing size limits.' if permission=='ALLOW' else 'The floor will not automatically commit new fake capital yet.'),'simulation_only':True}

    base.v91_floor_debate=floor_debate
    base.v92_floor_debate=floor_debate

    class Req(BaseModel):symbol:str=Field(default='NVDA',min_length=1,max_length=24)

    @app.post('/api/ai/trading-floor')
    async def trading_floor(req:Req,request:Request):
        uid=base.current_user_id(request);sym=req.symbol.strip().upper();c=await scan(request,sym)
        if not c:raise HTTPException(404,'No candidate data for that symbol')
        acct=base.account_snapshot(uid);route=base.v89_route_policy(uid,c,acct) if hasattr(base,'v89_route_policy') else {'permission':'ALLOW','size_multiplier':1,'execution_authority':100}
        img=base.v90_imagine_candidate(uid,c,acct,route,10*float(route.get('size_multiplier') or 0)) if hasattr(base,'v90_imagine_candidate') else {'robustness_score':50,'permission':'REQUIRE_REVIEW'}
        floor=floor_debate(uid,c,acct,route,img)
        try:
            conn=base.db();conn.execute('INSERT INTO user_ai_decisions(user_id,symbol,action,score,confidence,detail,created_at) VALUES(?,?,?,?,?,?,?)',(uid,sym,'V92_FLOOR_DEBATE',c.get('score'),c.get('confidence'),json.dumps({'floor':floor},separators=(',',':')),base.now_iso()));conn.commit();conn.close()
        except Exception:pass
        return {'engine':'Purple Trading Floor V9.2 — Learned Staff','candidate':c,'hierarchical_route':route,'imagination':img,'floor':floor,'note':'Specialist agents keep bounded regime-specific reputations based on later simulated price outcomes. Reputations influence debate weight but never bypass risk gates. No real brokerage order is sent.'}

    @app.get('/api/ai/trading-floor-reputation')
    async def reputation(request:Request):
        uid=base.current_user_id(request);consolidated=consolidate(uid);ensure_tables();conn=base.db();rows=[dict(r) for r in conn.execute('SELECT * FROM user_ai_agent_reputation WHERE user_id=? ORDER BY reliability DESC, observations DESC',(uid,)).fetchall()];pending=conn.execute('SELECT COUNT(*) c FROM user_ai_agent_observations WHERE user_id=? AND resolved=0',(uid,)).fetchone()['c'];conn.close();return {'engine':'Purple Trading Floor V9.2 — Learned Staff','reputations':rows,'pending_observations':pending,'consolidated_now':consolidated}
