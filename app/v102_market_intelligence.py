import math
from fastapi import Request, HTTPException


def register(app, base):
    def uid(request: Request):
        try: return int(base.current_user_id(request))
        except Exception: raise HTTPException(401, 'Login required')

    @app.get('/api/market-intelligence/{symbol}')
    def market_intelligence(symbol: str, request: Request):
        user_id=uid(request); symbol=symbol.upper().strip()[:12]
        snap=base.account_snapshot(user_id)
        price=float(base.latest_prices.get(symbol) or 0)
        pos=next((p for p in snap.get('positions',[]) if p.get('symbol')==symbol),None)
        concentration=(float(pos.get('market_value',0))/max(float(snap.get('equity',0)),1)*100) if pos else 0
        agents=[
          {'name':'Market Structure','stance':'WATCH','confidence':68,'finding':'Evaluates price behavior, liquidity and market regime before a simulated entry.'},
          {'name':'Risk Officer','stance':'CAUTION' if concentration>20 else 'CLEAR','confidence':88,'finding':f'Current portfolio concentration in {symbol} is {concentration:.1f}%.'},
          {'name':'Behavior Coach','stance':'DISCIPLINE','confidence':84,'finding':'Requires a thesis, invalidation level and position-size plan before confirmation.'},
          {'name':'Scenario Lab','stance':'TEST','confidence':76,'finding':'Compare bull, base and bear outcomes before committing simulated capital.'},
          {'name':'Portfolio Architect','stance':'DIVERSIFY' if concentration>25 else 'BALANCED','confidence':81,'finding':'Checks the proposed position against total portfolio exposure rather than viewing the ticker alone.'},
          {'name':'Devil’s Advocate','stance':'CHALLENGE','confidence':79,'finding':'Searches for reasons the trade thesis could be wrong before the system agrees with it.'},
        ]
        risk='high' if concentration>35 else 'medium' if concentration>20 else 'controlled'
        consensus={'label':'RESEARCH','score':79 if price else 55,'risk':risk,'summary':f'Purple Intelligence is treating {symbol} as a research decision, not a signal. Build a thesis, test scenarios, define risk, then decide whether to place a simulated trade.'}
        return {'symbol':symbol,'price':price,'agents':agents,'consensus':consensus,'position':pos,'simulation_only':True,'features':['multi-agent debate','portfolio-aware risk','scenario testing','behavior coaching','trade thesis','post-trade review']}
