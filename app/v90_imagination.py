import json, math
from types import SimpleNamespace
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field


def register(app, base):
    def clamp(x,a,b): return max(a,min(b,x))

    scan_ep=next((r.endpoint for r in app.router.routes if getattr(r,'path',None)=='/api/ai/scan' and 'POST' in getattr(r,'methods',set())),None)
    settings_ep=next((r.endpoint for r in app.router.routes if getattr(r,'path',None)=='/api/ai/settings' and 'GET' in getattr(r,'methods',set())),None)

    async def run_scan(request,symbols=None):
        if not scan_ep: raise HTTPException(503,'Sparse AI scan engine unavailable')
        return await scan_ep(SimpleNamespace(symbols=symbols),request)

    async def get_settings(request):
        if not settings_ep:return {'enabled':True,'mode':'copilot','risk_profile':'balanced','max_positions':4,'max_position_pct':20}
        return await settings_ep(request)

    def base_target(cfg,score):
        bp={'conservative':10,'balanced':15,'aggressive':20}.get(cfg.get('risk_profile'),15)
        return min(float(cfg.get('max_position_pct',20)),bp+max(0,(score-70))*.18)

    def global_focus(uid):
        conn=base.db();row=None
        try:row=conn.execute('SELECT * FROM user_ai_global_attention_events WHERE user_id=? ORDER BY id DESC LIMIT 1',(uid,)).fetchone()
        except Exception:pass
        conn.close();return dict(row) if row else None

    def scenario_engine(uid,candidate,acct,route,target_pct):
        score=float(candidate.get('score') or 50);confidence=float(candidate.get('confidence') or 50)
        processors=candidate.get('processors') or {};vol_quality=float(processors.get('volatility',55) or 55)
        route_auth=float(route.get('execution_authority') or 0);equity=float(acct.get('equity') or 0);alloc=equity*max(0,target_pct)/100
        gf=global_focus(uid);gfocus=str((gf or {}).get('focus') or 'baseline');gact=float((gf or {}).get('activation') or 0)
        risk_scale=clamp(1+(55-vol_quality)/90,.75,1.45)
        edge=clamp((score-50)/50,-.8,.9)

        raw=[
          {'id':'bull_continuation','label':'Bull continuation','move':(2.2+max(0,edge)*3.6)*risk_scale,'weight':.24+max(0,edge)*.18,'kind':'upside'},
          {'id':'failed_breakout','label':'Failed breakout','move':-(1.7+max(0,edge)*1.5)*risk_scale,'weight':.19+max(0,score-68)/180,'kind':'downside'},
          {'id':'volatility_shock','label':'Volatility shock','move':-(3.0+(100-vol_quality)/38)*risk_scale,'weight':.16+(max(0,60-vol_quality)/220),'kind':'stress'},
          {'id':'market_reversal','label':'Broad market reversal','move':-(2.5+max(0,gact-55)/18)*risk_scale,'weight':.16+(0.12 if gfocus in ('risk_off_breadth','volatility_regime') else 0),'kind':'stress'},
          {'id':'correlation_spike','label':'Correlation spike','move':-(2.0+max(0,gact-55)/24)*risk_scale,'weight':.14+(0.13 if gfocus in ('correlation_spike','portfolio_cluster_risk') else 0),'kind':'stress'},
          {'id':'sideways_noise','label':'Sideways / no edge','move':(.15*edge)*risk_scale,'weight':.11,'kind':'neutral'}
        ]
        total=sum(x['weight'] for x in raw) or 1
        scenarios=[];weighted=0;positive=0;worst=0
        for s in raw:
            p=s['weight']/total;move=round(s['move'],2);pl=alloc*move/100;projected=equity+pl
            scenarios.append({'id':s['id'],'label':s['label'],'probability':round(p*100,1),'simulated_move_pct':move,'position_pl':round(pl,2),'projected_equity':round(projected,2),'kind':s['kind']})
            weighted+=p*move
            if move>0:positive+=p
            worst=min(worst,move)
        downside_equity_pct=abs((alloc*worst/100)/equity*100) if equity else 0
        robustness=clamp(50+weighted*8+(positive-.5)*35-downside_equity_pct*5+(route_auth-50)*.16,0,100)
        mult=clamp(.35+(robustness/100)*.78,.28,1.08)
        permission='ALLOW'
        reasons=[]
        if route.get('permission')=='BLOCK_NEW_BUY':permission='BLOCK_NEW_BUY';mult=0;reasons.append('Hierarchical router already blocked this buy')
        elif robustness<36:permission='BLOCK_NEW_BUY';mult=0;reasons.append('Forward scenarios are too fragile')
        elif robustness<52:permission='REQUIRE_REVIEW';mult=min(mult,.62);reasons.append('Scenario set is mixed or downside-heavy')
        if downside_equity_pct>2.4 and permission=='ALLOW':permission='REQUIRE_REVIEW';mult=min(mult,.7);reasons.append('Worst simulated scenario consumes too much account equity')
        return {'symbol':candidate.get('symbol'),'target_pct_before_imagination':round(target_pct,2),'allocation_before_imagination':round(alloc,2),'weighted_scenario_return_pct':round(weighted,2),'positive_scenario_probability':round(positive*100,1),'worst_scenario_move_pct':round(worst,2),'worst_account_impact_pct':round(downside_equity_pct,2),'robustness_score':round(robustness,1),'imagination_multiplier':round(mult,3),'permission':permission,'reasons':reasons,'scenarios':scenarios,'global_context':{'focus':gfocus,'activation':round(gact,1)},'simulation_only':True}

    base.v90_imagine_candidate=scenario_engine

    def log_imagination(uid,candidate,route,img,action):
        try:
            conn=base.db();conn.execute('INSERT INTO user_ai_decisions(user_id,symbol,action,score,confidence,detail,created_at) VALUES(?,?,?,?,?,?,?)',(uid,candidate['symbol'],action,candidate.get('score'),candidate.get('confidence'),json.dumps({'v89':route,'v90':img},separators=(',',':')),base.now_iso()));conn.commit();conn.close()
        except Exception:pass

    class ImagineReq(BaseModel):
        symbol:str=Field(default='NVDA',min_length=1,max_length=24)
    class PlanReq(BaseModel): symbols:list[str]|None=None
    class ExecuteReq(BaseModel): symbols:list[str]|None=None

    @app.post('/api/ai/imagine')
    async def imagine(req:ImagineReq,request:Request):
        uid=base.current_user_id(request);sym=req.symbol.strip().upper();scan=await run_scan(request,[sym]);candidate=next((x for x in scan.get('candidates',[]) if x.get('symbol')==sym),None)
        if not candidate:raise HTTPException(404,'No candidate data for that symbol')
        acct=base.account_snapshot(uid);cfg=await get_settings(request);route=base.v89_route_policy(uid,candidate,acct) if hasattr(base,'v89_route_policy') else {'permission':'ALLOW','size_multiplier':1,'execution_authority':100,'layers':[],'gates':[]}
        target=base_target(cfg,float(candidate.get('score') or 50))*float(route.get('size_multiplier') or 0);img=scenario_engine(uid,candidate,acct,route,target)
        return {'engine':'Purple Forward Simulation / Imagination Engine V9.0','candidate':candidate,'hierarchical_route':route,'imagination':img,'final_target_pct':round(target*img['imagination_multiplier'],2),'note':'These are synthetic stress scenarios for the fake-money simulator, not forecasts or guarantees.'}

    app.router.routes[:]=[r for r in app.router.routes if getattr(r,'path',None) not in {'/api/ai/build-plan','/api/ai/autopilot/run'}]

    @app.post('/api/ai/build-plan')
    async def imagination_plan(req:PlanReq,request:Request):
        uid=base.current_user_id(request);cfg=await get_settings(request);scan=await run_scan(request,req.symbols);acct=base.account_snapshot(uid);picks=[]
        for c in [x for x in scan.get('candidates',[]) if float(x.get('score') or 0)>=60][:int(cfg.get('max_positions',4))*3]:
            route=base.v89_route_policy(uid,c,acct) if hasattr(base,'v89_route_policy') else {'permission':'ALLOW','size_multiplier':1,'execution_authority':100}
            if route['permission']=='BLOCK_NEW_BUY':continue
            pre=base_target(cfg,float(c['score']))*float(route.get('size_multiplier') or 0);img=scenario_engine(uid,c,acct,route,pre)
            if img['permission']=='BLOCK_NEW_BUY':continue
            final=pre*img['imagination_multiplier']
            if final<1:continue
            picks.append({**c,'target_pct':round(final,2),'target_fake_dollars':round(float(acct.get('equity') or 0)*final/100,2),'hierarchical_route':route,'imagination':img})
            if len(picks)>=int(cfg.get('max_positions',4)):break
        return {'mode':cfg.get('mode'),'risk_profile':cfg.get('risk_profile'),'engine':'Purple Imagination-Gated Portfolio Builder V9.0','picks':picks,'note':'Each simulated allocation passed hierarchical routing and a multi-scenario forward stress test. No real brokerage order is sent.'}

    @app.post('/api/ai/autopilot/run')
    async def imagination_autopilot(req:ExecuteReq,request:Request):
        uid=base.current_user_id(request);cfg=await get_settings(request)
        if not cfg.get('enabled') or cfg.get('mode')!='autopilot':raise HTTPException(409,'Enable AI and select AUTOPILOT first')
        scan=await run_scan(request,req.symbols);acct=base.account_snapshot(uid);positions={p['symbol']:p for p in acct.get('positions',[])};actions=[]
        for c in scan.get('candidates',[]):
            if c['symbol'] in positions and float(c.get('score') or 0)<38:
                p=positions[c['symbol']];qty=float(p['qty']);price=float(base.latest_prices.get(c['symbol']) or p['price'])
                if qty>0 and price>0:
                    route=base.v89_route_policy(uid,c,acct) if hasattr(base,'v89_route_policy') else {'permission':'ALLOW','size_multiplier':1,'execution_authority':100}
                    conn=base.db();cur=conn.execute("INSERT INTO user_orders(user_id,symbol,side,order_type,qty,status,submitted_at,note) VALUES(?,?, 'sell','market',?,'open',?,'Purple V9.0 imagination autopilot risk exit')",(uid,c['symbol'],qty,base.now_iso()));oid=cur.lastrowid;conn.commit();conn.close();ok,msg=base.execute_fill(uid,oid,c['symbol'],'sell',qty,base.simulated_fill_price(c['symbol'],'sell',price));actions.append({'symbol':c['symbol'],'side':'sell','qty':qty,'ok':ok,'message':msg,'hierarchical_route':route});log_imagination(uid,c,route,{'reason':'risk exit; imagination not required'},'V90_AUTO_SELL')
        acct=base.account_snapshot(uid);positions={p['symbol']:p for p in acct.get('positions',[])};slots=max(0,int(cfg.get('max_positions',4))-len(positions))
        for c in [x for x in scan.get('candidates',[]) if float(x.get('score') or 0)>=68 and x.get('action')=='BUY']:
            if slots<=0:break
            if c['symbol'] in positions:continue
            route=base.v89_route_policy(uid,c,acct) if hasattr(base,'v89_route_policy') else {'permission':'ALLOW','size_multiplier':1,'execution_authority':100}
            pre=base_target(cfg,float(c['score']))*float(route.get('size_multiplier') or 0);img=scenario_engine(uid,c,acct,route,pre)
            if route['permission']!='ALLOW' or img['permission']!='ALLOW':
                actions.append({'symbol':c['symbol'],'side':'skip','ok':True,'message':img['permission'] if route['permission']=='ALLOW' else route['permission'],'hierarchical_route':route,'imagination':img});log_imagination(uid,c,route,img,'V90_SKIP');continue
            price=float(base.latest_prices.get(c['symbol']) or 0)
            if not price:continue
            target=pre*img['imagination_multiplier'];alloc=min(float(acct.get('equity') or 0)*target/100,float(acct.get('cash') or 0)*.92);qty=math.floor((alloc/price)*1000)/1000
            if qty<=0:continue
            conn=base.db();cur=conn.execute("INSERT INTO user_orders(user_id,symbol,side,order_type,qty,status,submitted_at,note) VALUES(?,?, 'buy','market',?,'open',?,'Purple V9.0 imagination-gated autopilot')",(uid,c['symbol'],qty,base.now_iso()));oid=cur.lastrowid;conn.commit();conn.close();ok,msg=base.execute_fill(uid,oid,c['symbol'],'buy',qty,base.simulated_fill_price(c['symbol'],'buy',price));actions.append({'symbol':c['symbol'],'side':'buy','qty':qty,'allocation':round(alloc,2),'target_pct':round(target,2),'ok':ok,'message':msg,'hierarchical_route':route,'imagination':img});log_imagination(uid,c,route,img,'V90_AUTO_BUY');acct=base.account_snapshot(uid);slots-=1
        return {'ok':True,'engine':'Purple Forward Simulation / Imagination Autopilot V9.0','actions':actions,'scan':scan,'account':base.account_snapshot(uid),'simulation_only':True}
