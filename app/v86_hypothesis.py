import json, statistics
from datetime import datetime, timezone, timedelta
import httpx
from fastapi import Request
from pydantic import BaseModel, Field

HYPOTHESES=('bull_continuation','mean_reversion','stay_cash','portfolio_defense')


def register(app, base):
    def clamp(x,a=0,b=100): return max(a,min(b,x))
    def ensure_tables():
        conn=base.db();conn.executescript('''
        CREATE TABLE IF NOT EXISTS user_ai_hypothesis_memory(
          user_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          hypothesis TEXT NOT NULL,
          ema_activation REAL NOT NULL DEFAULT 50,
          wins INTEGER NOT NULL DEFAULT 0,
          rounds INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(user_id,symbol,hypothesis)
        );
        CREATE TABLE IF NOT EXISTS user_ai_hypothesis_rounds(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          winner TEXT NOT NULL,
          confidence REAL NOT NULL,
          activations TEXT NOT NULL,
          evidence TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        ''');conn.commit();conn.close()

    class HypReq(BaseModel):
        symbol:str=Field(default='NVDA',min_length=1,max_length=16)
        cycles:int=Field(default=4,ge=2,le=8)

    async def bars(symbol):
        if '/' in symbol or not base.API_KEY or not base.SECRET_KEY:return []
        headers={'APCA-API-KEY-ID':base.API_KEY,'APCA-API-SECRET-KEY':base.SECRET_KEY}
        end=datetime.now(timezone.utc);start=end-timedelta(days=8)
        params={'timeframe':'15Min','start':start.isoformat(),'end':end.isoformat(),'limit':80,'feed':'iex','adjustment':'raw','sort':'asc'}
        try:
            async with httpx.AsyncClient(timeout=6) as c:r=await c.get(f'{base.ALPACA_DATA}/stocks/{symbol}/bars',headers=headers,params=params)
            if r.status_code>=400:return []
            d=r.json();return d.get('bars',[]) if isinstance(d,dict) else []
        except Exception:return []

    def prior(uid,symbol):
        ensure_tables();conn=base.db();rows=conn.execute('SELECT * FROM user_ai_hypothesis_memory WHERE user_id=? AND symbol=?',(uid,symbol)).fetchall();conn.close()
        return {r['hypothesis']:dict(r) for r in rows}

    def evidence(symbol, data, acct, behavior):
        closes=[float(x.get('c') or 0) for x in data if x.get('c')]
        price=float(base.latest_prices.get(symbol) or (closes[-1] if closes else 0) or 0)
        e={'price':price,'trend':50.0,'momentum':50.0,'volatility_quality':50.0,'spread_quality':55.0,'mean_reversion_pressure':50.0,'portfolio_fit':75.0,'behavior_state':82.0}
        if len(closes)>=20:
            fast=sum(closes[-5:])/5;slow=sum(closes[-20:])/20;e['trend']=clamp(50+(fast/slow-1)*1200)
            mean20=slow;dist=(closes[-1]/mean20-1)*100;e['mean_reversion_pressure']=clamp(50-dist*6)
        if len(closes)>=8:
            mom=(closes[-1]/closes[-6]-1)*100;e['momentum']=clamp(50+mom*4)
        if len(closes)>=12:
            rets=[(closes[i]/closes[i-1]-1)*100 for i in range(1,len(closes)) if closes[i-1]];vol=statistics.pstdev(rets[-20:]) if rets else 0;e['volatility_quality']=clamp(78-abs(vol-.55)*30)
        q=base.latest_quotes.get(symbol) or {};bid=float(q.get('bid') or 0);ask=float(q.get('ask') or 0)
        if bid and ask and price:
            sp=(ask-bid)/price*100;e['spread_quality']=clamp(92-sp*130)
        held=next((p for p in acct.get('positions',[]) if p['symbol']==symbol),None)
        conc=(held['market_value']/acct['equity']*100) if held and acct.get('equity') else 0;e['portfolio_fit']=clamp(82-conc*1.9)
        penalty=(10 if behavior.get('loss_streak',0)>=2 else 0)+(9 if behavior.get('size_escalations',0) else 0);e['behavior_state']=clamp(84-penalty)
        return {k:round(v,2) if isinstance(v,(int,float)) else v for k,v in e.items()}

    def initial_assemblies(e, mem):
        # Each assembly reads overlapping evidence but interprets it differently.
        bull=.30*e['trend']+.27*e['momentum']+.13*e['volatility_quality']+.10*e['spread_quality']+.10*e['portfolio_fit']+.10*e['behavior_state']
        mr=.31*e['mean_reversion_pressure']+.18*(100-e['momentum'])+.15*e['volatility_quality']+.12*e['spread_quality']+.12*e['portfolio_fit']+.12*e['behavior_state']
        cash=.24*(100-e['trend'])+.20*(100-e['momentum'])+.18*(100-e['volatility_quality'])+.14*(100-e['spread_quality'])+.12*(100-e['behavior_state'])+.12*(100-e['portfolio_fit'])
        defense=.30*(100-e['portfolio_fit'])+.24*(100-e['behavior_state'])+.18*(100-e['volatility_quality'])+.14*(100-e['spread_quality'])+.14*(100-e['momentum'])
        out={'bull_continuation':bull,'mean_reversion':mr,'stay_cash':cash,'portfolio_defense':defense}
        for h in HYPOTHESES:
            if h in mem and int(mem[h].get('rounds') or 0)>=2:
                out[h]=out[h]*.86+float(mem[h].get('ema_activation') or 50)*.14
        return {k:clamp(v) for k,v in out.items()}

    def compete(start, cycles):
        x=dict(start);trace=[]
        # Sparse recurrent competition: strongest assemblies inhibit rivals, while cash/defense can gate risk-taking.
        for cycle in range(cycles):
            ranked=sorted(x.items(),key=lambda kv:kv[1],reverse=True);leader,lead=ranked[0]
            nxt={}
            for h,v in x.items():
                inhibition=sum(max(0,other-55)*.055 for oh,other in x.items() if oh!=h)
                self_recur=max(0,v-50)*.075
                nv=v+self_recur-inhibition
                if h in ('bull_continuation','mean_reversion'):
                    nv-=max(0,x['stay_cash']-55)*.10+max(0,x['portfolio_defense']-55)*.12
                if h=='stay_cash': nv+=max(0,x['portfolio_defense']-60)*.06
                nxt[h]=clamp(nv)
            x=nxt;trace.append({'cycle':cycle+1,'leader':leader,'activations':{k:round(v,1) for k,v in x.items()}})
        ranked=sorted(x.items(),key=lambda kv:kv[1],reverse=True);winner,top=ranked[0];second=ranked[1][1];margin=top-second
        if top<58 or margin<5:winner='unresolved'
        confidence=clamp(42+margin*3+(top-50)*.65,35,96)
        return {k:round(v,1) for k,v in x.items()},winner,round(confidence,1),trace

    def persist(uid,symbol,acts,winner,confidence,e):
        conn=base.db()
        for h,v in acts.items():
            r=conn.execute('SELECT * FROM user_ai_hypothesis_memory WHERE user_id=? AND symbol=? AND hypothesis=?',(uid,symbol,h)).fetchone();old=float(r['ema_activation']) if r else 50;rounds=int(r['rounds']) if r else 0;wins=int(r['wins']) if r else 0;ema=old*.76+v*.24;wins+=1 if winner==h else 0;rounds+=1
            conn.execute('''INSERT INTO user_ai_hypothesis_memory(user_id,symbol,hypothesis,ema_activation,wins,rounds,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,symbol,hypothesis) DO UPDATE SET ema_activation=excluded.ema_activation,wins=excluded.wins,rounds=excluded.rounds,updated_at=excluded.updated_at''',(uid,symbol,h,ema,wins,rounds,base.now_iso()))
        conn.execute('INSERT INTO user_ai_hypothesis_rounds(user_id,symbol,winner,confidence,activations,evidence,created_at) VALUES(?,?,?,?,?,?,?)',(uid,symbol,winner,confidence,json.dumps(acts,separators=(',',':')),json.dumps(e,separators=(',',':')),base.now_iso()))
        conn.execute('''DELETE FROM user_ai_hypothesis_rounds WHERE user_id=? AND id NOT IN (SELECT id FROM user_ai_hypothesis_rounds WHERE user_id=? ORDER BY id DESC LIMIT 120)''',(uid,uid));conn.commit();conn.close()

    def interpretation(winner, acts):
        labels={'bull_continuation':'Bull continuation','mean_reversion':'Mean reversion','stay_cash':'Stay in cash','portfolio_defense':'Portfolio defense','unresolved':'No dominant hypothesis'}
        if winner=='bull_continuation':action='WATCH FOR LONG SETUP'
        elif winner=='mean_reversion':action='WAIT FOR REVERSAL CONFIRMATION'
        elif winner in ('stay_cash','portfolio_defense'):action='NO NEW TRADE'
        else:action='WAIT — EVIDENCE CONFLICTS'
        return {'winner_label':labels[winner],'action':action,'ranked':[{'id':h,'label':labels[h],'activation':v} for h,v in sorted(acts.items(),key=lambda kv:kv[1],reverse=True)]}

    @app.post('/api/ai/hypotheses')
    async def hypotheses(req:HypReq, request:Request):
        uid=base.current_user_id(request);symbol=req.symbol.strip().upper();
        if '/' in symbol: await base.fetch_crypto_snapshot(symbol)
        else: await base.fetch_latest_snapshot(symbol)
        data=await bars(symbol);acct=base.account_snapshot(uid);behavior=base.adaptive_coach_metrics(uid);mem=prior(uid,symbol);e=evidence(symbol,data,acct,behavior);start=initial_assemblies(e,mem);acts,winner,conf,trace=compete(start,req.cycles);persist(uid,symbol,acts,winner,conf,e);view=interpretation(winner,acts)
        return {'engine':'Purple Competing Assemblies V8.6','symbol':symbol,'cycles':req.cycles,'winner':winner,'confidence':conf,'decision':view['action'],'ranked':view['ranked'],'evidence':e,'trace':trace,'memory_used':bool(mem),'simulation_only':True,'note':'Competing hypotheses are a simulator decision-support mechanism, not a promise of market performance.'}

    @app.get('/api/ai/hypothesis-memory')
    async def hypothesis_memory(request:Request):
        uid=base.current_user_id(request);ensure_tables();conn=base.db();rows=[dict(r) for r in conn.execute('SELECT * FROM user_ai_hypothesis_memory WHERE user_id=? ORDER BY updated_at DESC LIMIT 40',(uid,)).fetchall()];rounds=[dict(r) for r in conn.execute('SELECT * FROM user_ai_hypothesis_rounds WHERE user_id=? ORDER BY id DESC LIMIT 12',(uid,)).fetchall()];conn.close();return {'engine':'Purple Competing Assemblies V8.6','memory':rows,'recent_rounds':rounds}
