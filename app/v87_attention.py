import json, statistics
from datetime import datetime, timezone, timedelta
import httpx
from fastapi import Request
from pydantic import BaseModel, Field

ASSEMBLY_TTL_SECONDS=300


def register(app, base):
    def clamp(x,a=0,b=100): return max(a,min(b,x))
    def ensure_tables():
        conn=base.db();conn.executescript('''
        CREATE TABLE IF NOT EXISTS user_ai_attention_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          assembly TEXT NOT NULL,
          activation REAL NOT NULL,
          reason TEXT NOT NULL,
          payload TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_ai_attention_memory(
          user_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          assembly TEXT NOT NULL,
          activations INTEGER NOT NULL DEFAULT 0,
          ema_strength REAL NOT NULL DEFAULT 50,
          last_reason TEXT,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(user_id,symbol,assembly)
        );
        ''');conn.commit();conn.close()

    class AttentionReq(BaseModel):
        symbol:str=Field(default='NVDA',min_length=1,max_length=24)

    async def bars(symbol):
        if '/' in symbol or not base.API_KEY or not base.SECRET_KEY:return []
        headers={'APCA-API-KEY-ID':base.API_KEY,'APCA-API-SECRET-KEY':base.SECRET_KEY}
        end=datetime.now(timezone.utc);start=end-timedelta(days=6)
        params={'timeframe':'15Min','start':start.isoformat(),'end':end.isoformat(),'limit':96,'feed':'iex','adjustment':'raw','sort':'asc'}
        try:
            async with httpx.AsyncClient(timeout=6) as c:r=await c.get(f'{base.ALPACA_DATA}/stocks/{symbol}/bars',headers=headers,params=params)
            if r.status_code>=400:return []
            d=r.json();return d.get('bars',[]) if isinstance(d,dict) else []
        except Exception:return []

    def features(symbol,data,acct,behavior):
        closes=[float(x.get('c') or 0) for x in data if x.get('c')]
        highs=[float(x.get('h') or 0) for x in data if x.get('h')]
        lows=[float(x.get('l') or 0) for x in data if x.get('l')]
        volumes=[float(x.get('v') or 0) for x in data if x.get('v')]
        price=float(base.latest_prices.get(symbol) or (closes[-1] if closes else 0) or 0)
        f={'price':price,'trend_gap':0.0,'momentum_5':0.0,'volatility':0.0,'volume_ratio':1.0,'range_position':.5,'spread_pct':0.0,'concentration':0.0,'loss_streak':int(behavior.get('loss_streak',0) or 0),'size_escalations':int(behavior.get('size_escalations',0) or 0)}
        if len(closes)>=20:
            fast=sum(closes[-5:])/5;slow=sum(closes[-20:])/20;f['trend_gap']=(fast/slow-1)*100 if slow else 0
        if len(closes)>=6:f['momentum_5']=(closes[-1]/closes[-6]-1)*100 if closes[-6] else 0
        if len(closes)>=12:
            rets=[(closes[i]/closes[i-1]-1)*100 for i in range(1,len(closes)) if closes[i-1]];f['volatility']=statistics.pstdev(rets[-20:]) if rets else 0
        if len(volumes)>=20:
            avg=sum(volumes[-20:-1])/max(1,len(volumes[-20:-1]));f['volume_ratio']=volumes[-1]/avg if avg else 1
        if highs and lows:
            hi=max(highs[-20:]);lo=min(lows[-20:]);f['range_position']=(price-lo)/(hi-lo) if hi>lo else .5
        q=base.latest_quotes.get(symbol) or {};bid=float(q.get('bid') or 0);ask=float(q.get('ask') or 0)
        if bid and ask and price:f['spread_pct']=(ask-bid)/price*100
        held=next((p for p in acct.get('positions',[]) if p['symbol']==symbol),None)
        if held and acct.get('equity'):f['concentration']=float(held['market_value'])/float(acct['equity'])*100
        return {k:round(v,4) if isinstance(v,float) else v for k,v in f.items()}

    def spawn(symbol,f):
        spawned=[]
        def add(name,label,activation,reason,kind):
            if activation>=58:spawned.append({'id':name,'label':label,'activation':round(clamp(activation),1),'reason':reason,'kind':kind,'ttl_seconds':ASSEMBLY_TTL_SECONDS})
        add('trend_acceleration','Trend Acceleration',50+abs(f['trend_gap'])*9+max(0,abs(f['momentum_5'])-.4)*7,'Trend and recent momentum are unusually directional.','opportunity')
        breakout_pressure=(f['range_position']-.72)*110+max(0,f['volume_ratio']-1)*18+50
        add('breakout_pressure','Breakout Pressure',breakout_pressure,'Price is near the recent range edge with supporting activity.','opportunity')
        failure=50+max(0,.25-f['range_position'])*75+max(0,-f['momentum_5'])*8+max(0,f['volatility']-.8)*12
        add('breakout_failure','Breakout Failure',failure,'Price structure and momentum suggest a failed extension or rejection risk.','warning')
        shock=50+max(0,f['volatility']-.65)*32+max(0,abs(f['momentum_5'])-1.2)*6
        add('volatility_shock','Volatility Shock',shock,'Recent price dispersion is high enough to demand a temporary volatility specialist.','warning')
        liquidity=50+max(0,f['spread_pct']-.08)*230
        add('liquidity_stress','Liquidity Stress',liquidity,'Quoted spread is wide enough to change execution quality.','warning')
        defense=50+max(0,f['concentration']-18)*2.3
        add('concentration_guard','Concentration Guard',defense,'This symbol is becoming a large part of simulated equity.','defense')
        behavior=50+f['loss_streak']*7+f['size_escalations']*12
        add('behavioral_circuit','Behavioral Circuit Breaker',behavior,'Recent simulated behavior warrants a temporary risk-control assembly.','defense')
        if '/' in symbol:
            crypto=52+max(0,f['volatility']-.7)*28+max(0,abs(f['momentum_5'])-1)*5
            add('crypto_regime','Crypto Regime',crypto,'24/7 crypto volatility triggered a crypto-specific temporary assembly.','specialist')
        spawned.sort(key=lambda x:x['activation'],reverse=True)
        return spawned[:5]

    def attend(spawned):
        if not spawned:return {'focus':'baseline','focus_label':'No temporary assembly','attention_strength':0,'inhibition':0,'decision_bias':'NONE'}
        top=spawned[0];second=spawned[1]['activation'] if len(spawned)>1 else 0;gap=top['activation']-second
        inhibition=clamp((top['activation']-58)*.42+max(0,gap)*.18,0,24)
        if top['kind'] in ('warning','defense'):bias='REDUCE RISK / REQUIRE MORE CONFIRMATION'
        elif top['kind']=='opportunity':bias='PRIORITIZE THIS SETUP FOR REVIEW'
        else:bias='USE SPECIALIST REGIME RULES'
        return {'focus':top['id'],'focus_label':top['label'],'attention_strength':top['activation'],'inhibition':round(inhibition,1),'decision_bias':bias}

    def persist(uid,symbol,spawned,features):
        ensure_tables();conn=base.db()
        for a in spawned:
            conn.execute('INSERT INTO user_ai_attention_events(user_id,symbol,assembly,activation,reason,payload,created_at) VALUES(?,?,?,?,?,?,?)',(uid,symbol,a['id'],a['activation'],a['reason'],json.dumps(features,separators=(',',':')),base.now_iso()))
            r=conn.execute('SELECT * FROM user_ai_attention_memory WHERE user_id=? AND symbol=? AND assembly=?',(uid,symbol,a['id'])).fetchone();n=int(r['activations'])+1 if r else 1;old=float(r['ema_strength']) if r else 50;ema=old*.8+a['activation']*.2
            conn.execute('''INSERT INTO user_ai_attention_memory(user_id,symbol,assembly,activations,ema_strength,last_reason,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,symbol,assembly) DO UPDATE SET activations=excluded.activations,ema_strength=excluded.ema_strength,last_reason=excluded.last_reason,updated_at=excluded.updated_at''',(uid,symbol,a['id'],n,ema,a['reason'],base.now_iso()))
        conn.execute('''DELETE FROM user_ai_attention_events WHERE user_id=? AND id NOT IN (SELECT id FROM user_ai_attention_events WHERE user_id=? ORDER BY id DESC LIMIT 160)''',(uid,uid));conn.commit();conn.close()

    @app.post('/api/ai/attention')
    async def attention(req:AttentionReq,request:Request):
        uid=base.current_user_id(request);symbol=req.symbol.strip().upper()
        if '/' in symbol:await base.fetch_crypto_snapshot(symbol)
        else:await base.fetch_latest_snapshot(symbol)
        data=await bars(symbol);acct=base.account_snapshot(uid);behavior=base.adaptive_coach_metrics(uid);f=features(symbol,data,acct,behavior);spawned=spawn(symbol,f);focus=attend(spawned);persist(uid,symbol,spawned,f)
        return {'engine':'Purple Dynamic Attention Mesh V8.7','symbol':symbol,'features':f,'spawned':spawned,'spawned_count':len(spawned),'focus':focus,'temporary':True,'ttl_seconds':ASSEMBLY_TTL_SECONDS,'resident_cost':'Assemblies are computed on demand and discarded after the request; only compact summaries persist.','simulation_only':True}

    @app.get('/api/ai/attention-memory')
    async def attention_memory(request:Request):
        uid=base.current_user_id(request);ensure_tables();conn=base.db();memory=[dict(r) for r in conn.execute('SELECT * FROM user_ai_attention_memory WHERE user_id=? ORDER BY updated_at DESC LIMIT 30',(uid,)).fetchall()];events=[dict(r) for r in conn.execute('SELECT * FROM user_ai_attention_events WHERE user_id=? ORDER BY id DESC LIMIT 16',(uid,)).fetchall()];conn.close();return {'engine':'Purple Dynamic Attention Mesh V8.7','memory':memory,'recent_events':events}

    from .v88_global_attention import register as register_v88_global_attention
    register_v88_global_attention(app,base)
