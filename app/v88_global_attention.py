import json, math, statistics
from datetime import datetime, timezone, timedelta
import httpx
from fastapi import Request
from pydantic import BaseModel, Field

DEFAULT_UNIVERSE=['SPY','QQQ','AAPL','MSFT','NVDA','AMD','AMZN','META','TSLA','BTC/USD','ETH/USD']
GLOBAL_TTL_SECONDS=420


def register(app, base):
    def clamp(x,a=0,b=100): return max(a,min(b,x))
    def ensure_tables():
        conn=base.db();conn.executescript('''
        CREATE TABLE IF NOT EXISTS user_ai_global_attention_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          focus TEXT NOT NULL,
          activation REAL NOT NULL,
          bias TEXT NOT NULL,
          payload TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_ai_global_attention_memory(
          user_id INTEGER NOT NULL,
          assembly TEXT NOT NULL,
          activations INTEGER NOT NULL DEFAULT 0,
          ema_strength REAL NOT NULL DEFAULT 50,
          last_bias TEXT,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(user_id,assembly)
        );
        ''');conn.commit();conn.close()

    class GlobalReq(BaseModel):
        symbols:list[str]|None=None
        include_portfolio:bool=True

    async def stock_bars(symbol):
        if not base.API_KEY or not base.SECRET_KEY:return []
        headers={'APCA-API-KEY-ID':base.API_KEY,'APCA-API-SECRET-KEY':base.SECRET_KEY}
        end=datetime.now(timezone.utc);start=end-timedelta(days=7)
        params={'timeframe':'15Min','start':start.isoformat(),'end':end.isoformat(),'limit':72,'feed':'iex','adjustment':'raw','sort':'asc'}
        try:
            async with httpx.AsyncClient(timeout=5) as c:r=await c.get(f'{base.ALPACA_DATA}/stocks/{symbol}/bars',headers=headers,params=params)
            if r.status_code>=400:return []
            d=r.json();return d.get('bars',[]) if isinstance(d,dict) else []
        except Exception:return []

    def returns(bars):
        c=[float(x.get('c') or 0) for x in bars if x.get('c')]
        return [(c[i]/c[i-1]-1)*100 for i in range(1,len(c)) if c[i-1]][-30:]

    def corr(a,b):
        n=min(len(a),len(b))
        if n<8:return None
        a=a[-n:];b=b[-n:];ma=sum(a)/n;mb=sum(b)/n
        num=sum((x-ma)*(y-mb) for x,y in zip(a,b));da=math.sqrt(sum((x-ma)**2 for x in a));db=math.sqrt(sum((y-mb)**2 for y in b))
        return num/(da*db) if da and db else None

    async def collect(symbols):
        data={}
        for s in symbols:
            if '/' in s:
                await base.fetch_crypto_snapshot(s)
                data[s]={'returns':[],'price':float(base.latest_prices.get(s) or 0),'kind':'crypto'}
            else:
                await base.fetch_latest_snapshot(s);b=await stock_bars(s);data[s]={'returns':returns(b),'price':float(base.latest_prices.get(s) or 0),'kind':'stock'}
        return data

    def market_features(data,acct):
        usable={s:d for s,d in data.items() if len(d['returns'])>=8}
        recent=[];vols=[];directions=[]
        for s,d in usable.items():
            r=d['returns'];recent.append(sum(r[-4:]));vols.append(statistics.pstdev(r[-20:]) if len(r)>=2 else 0);directions.append(1 if sum(r[-4:])>0 else -1)
        breadth=(sum(1 for x in recent if x>0)/len(recent)*100) if recent else 50
        mean_move=(sum(recent)/len(recent)) if recent else 0
        dispersion=statistics.pstdev(recent) if len(recent)>=2 else 0
        mean_vol=(sum(vols)/len(vols)) if vols else 0
        pairs=[]
        keys=list(usable)
        for i in range(len(keys)):
            for j in range(i+1,len(keys)):
                c=corr(usable[keys[i]]['returns'],usable[keys[j]]['returns'])
                if c is not None:pairs.append((keys[i],keys[j],c))
        avg_corr=(sum(c for _,_,c in pairs)/len(pairs)) if pairs else 0
        high_corr=sum(1 for *_,c in pairs if c>.72)
        tech=[s for s in ('QQQ','AAPL','MSFT','NVDA','AMD','AMZN','META','TSLA') if s in usable]
        tech_moves=[sum(usable[s]['returns'][-4:]) for s in tech]
        tech_breadth=(sum(1 for x in tech_moves if x>0)/len(tech_moves)*100) if tech_moves else 50
        pos=acct.get('positions',[]);weights=[]
        if acct.get('equity'):
            weights=[float(p.get('market_value') or 0)/float(acct['equity'])*100 for p in pos]
        concentration=max(weights) if weights else 0
        return {'breadth':round(breadth,1),'mean_move_4bars':round(mean_move,3),'dispersion':round(dispersion,3),'mean_volatility':round(mean_vol,3),'avg_correlation':round(avg_corr,3),'high_corr_pairs':high_corr,'pair_count':len(pairs),'tech_breadth':round(tech_breadth,1),'portfolio_max_weight':round(concentration,1),'usable_assets':len(usable),'pairs':sorted([{'a':a,'b':b,'corr':round(c,3)} for a,b,c in pairs],key=lambda x:abs(x['corr']),reverse=True)[:12]}

    def spawn(f):
        out=[]
        def add(i,label,a,reason,kind,bias):
            if a>=58:out.append({'id':i,'label':label,'activation':round(clamp(a),1),'reason':reason,'kind':kind,'bias':bias,'ttl_seconds':GLOBAL_TTL_SECONDS})
        add('risk_on_breadth','Risk-On Breadth',50+max(0,f['breadth']-58)*.9+max(0,f['mean_move_4bars'])*7,'A large share of tracked assets are advancing together.','opportunity','ALLOW NORMAL RISK / PRIORITIZE STRONG LEADERS')
        add('risk_off_breadth','Risk-Off Breadth',50+max(0,42-f['breadth'])*1.0+max(0,-f['mean_move_4bars'])*8,'Weakness is broad across the tracked market universe.','defense','REDUCE NEW RISK / FAVOR CASH')
        add('correlation_spike','Correlation Spike',50+max(0,f['avg_correlation']-.48)*70+min(15,f['high_corr_pairs']*1.5),'Multiple assets are moving together, reducing effective diversification.','defense','TIGHTEN PORTFOLIO EXPOSURE / TREAT POSITIONS AS ONE CLUSTER')
        add('dispersion_regime','Dispersion Regime',50+max(0,f['dispersion']-.9)*20,'Cross-sectional returns are separating enough to favor selective rather than broad positioning.','specialist','SELECTIVITY HIGH / AVOID INDEX-LIKE ASSUMPTIONS')
        add('tech_cluster_shift','Technology Cluster Shift',50+abs(f['tech_breadth']-50)*.85,'Large technology names are moving unusually coherently as a group.','specialist','APPLY TECH-CLUSTER CONTEXT TO MEMBER SIGNALS')
        add('portfolio_cluster_risk','Portfolio Cluster Risk',50+max(0,f['portfolio_max_weight']-20)*2.1+max(0,f['avg_correlation']-.55)*25,'Portfolio concentration and market co-movement can amplify one common factor.','defense','LOWER ADDITIONAL EXPOSURE TO CORRELATED NAMES')
        add('volatility_regime','Market Volatility Regime',50+max(0,f['mean_volatility']-.75)*30,'Average short-horizon volatility is elevated across the market basket.','warning','REQUIRE MORE CONFIRMATION / SMALLER SIMULATED SIZE')
        out.sort(key=lambda x:x['activation'],reverse=True);return out[:5]

    def focus(assemblies):
        if not assemblies:return {'id':'baseline','label':'No global assembly','activation':0,'bias':'NONE','conflict':False}
        top=assemblies[0];conflict=any(a['kind']=='opportunity' for a in assemblies[:3]) and any(a['kind'] in ('defense','warning') for a in assemblies[:3])
        return {'id':top['id'],'label':top['label'],'activation':top['activation'],'bias':top['bias'],'conflict':conflict}

    def persist(uid,assemblies,features):
        ensure_tables();conn=base.db()
        top=focus(assemblies);conn.execute('INSERT INTO user_ai_global_attention_events(user_id,focus,activation,bias,payload,created_at) VALUES(?,?,?,?,?,?)',(uid,top['id'],top['activation'],top['bias'],json.dumps({'features':features,'assemblies':assemblies},separators=(',',':')),base.now_iso()))
        for a in assemblies:
            r=conn.execute('SELECT * FROM user_ai_global_attention_memory WHERE user_id=? AND assembly=?',(uid,a['id'])).fetchone();n=(int(r['activations'])+1) if r else 1;old=float(r['ema_strength']) if r else 50;ema=old*.82+a['activation']*.18
            conn.execute('''INSERT INTO user_ai_global_attention_memory(user_id,assembly,activations,ema_strength,last_bias,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,assembly) DO UPDATE SET activations=excluded.activations,ema_strength=excluded.ema_strength,last_bias=excluded.last_bias,updated_at=excluded.updated_at''',(uid,a['id'],n,ema,a['bias'],base.now_iso()))
        conn.execute('''DELETE FROM user_ai_global_attention_events WHERE user_id=? AND id NOT IN (SELECT id FROM user_ai_global_attention_events WHERE user_id=? ORDER BY id DESC LIMIT 120)''',(uid,uid));conn.commit();conn.close()

    @app.post('/api/ai/global-attention')
    async def global_attention(req:GlobalReq,request:Request):
        uid=base.current_user_id(request);acct=base.account_snapshot(uid)
        symbols=(req.symbols or DEFAULT_UNIVERSE)[:16]
        if req.include_portfolio:
            for p in acct.get('positions',[]):
                s=str(p.get('symbol') or '').upper()
                if s and s not in symbols and len(symbols)<16:symbols.append(s)
        symbols=[str(s).strip().upper() for s in symbols if s]
        data=await collect(symbols);features=market_features(data,acct);assemblies=spawn(features);foc=focus(assemblies);persist(uid,assemblies,features)
        return {'engine':'Purple Cross-Market Global Attention V8.8','universe':symbols,'features':features,'assemblies':assemblies,'focus':foc,'global_bias':foc['bias'],'temporary':True,'ttl_seconds':GLOBAL_TTL_SECONDS,'simulation_only':True,'note':'Global attention changes simulated decision context only; it does not execute real brokerage orders.'}

    @app.get('/api/ai/global-attention-memory')
    async def global_attention_memory(request:Request):
        uid=base.current_user_id(request);ensure_tables();conn=base.db();memory=[dict(r) for r in conn.execute('SELECT * FROM user_ai_global_attention_memory WHERE user_id=? ORDER BY updated_at DESC LIMIT 20',(uid,)).fetchall()];events=[dict(r) for r in conn.execute('SELECT * FROM user_ai_global_attention_events WHERE user_id=? ORDER BY id DESC LIMIT 10',(uid,)).fetchall()];conn.close();return {'engine':'Purple Cross-Market Global Attention V8.8','memory':memory,'recent_events':events}
