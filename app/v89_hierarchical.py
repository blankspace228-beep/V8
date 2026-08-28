import json
from datetime import datetime, timezone
from fastapi import Request
from pydantic import BaseModel, Field


def register(app, base):
    def clamp(x,a,b): return max(a,min(b,x))

    def _age_seconds(ts):
        if not ts:return 10**9
        try:
            d=datetime.fromisoformat(ts.replace('Z','+00:00'))
            if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
            return max(0,(datetime.now(timezone.utc)-d).total_seconds())
        except Exception:return 10**9

    def _latest_context(uid:int,symbol:str):
        conn=base.db();global_evt=local_evt=hyp=None
        try:
            global_evt=conn.execute('SELECT * FROM user_ai_global_attention_events WHERE user_id=? ORDER BY id DESC LIMIT 1',(uid,)).fetchone()
        except Exception:pass
        try:
            local_evt=conn.execute('SELECT * FROM user_ai_attention_events WHERE user_id=? AND symbol=? ORDER BY id DESC LIMIT 1',(uid,symbol)).fetchone()
        except Exception:pass
        try:
            hyp=conn.execute('SELECT * FROM user_ai_hypothesis_rounds WHERE user_id=? AND symbol=? ORDER BY id DESC LIMIT 1',(uid,symbol)).fetchone()
        except Exception:pass
        conn.close()
        return (dict(global_evt) if global_evt else None,dict(local_evt) if local_evt else None,dict(hyp) if hyp else None)

    def route_policy(uid:int,candidate:dict,acct:dict|None=None):
        symbol=str(candidate.get('symbol') or '').upper();score=float(candidate.get('score') or 50);processors=candidate.get('processors') or {}
        global_evt,local_evt,hyp=_latest_context(uid,symbol);mult=1.0;gates=[];layers=[];permission='ALLOW'

        if global_evt and _age_seconds(global_evt.get('created_at'))<=600:
            focus=str(global_evt.get('focus') or 'baseline');activation=float(global_evt.get('activation') or 0);bias=str(global_evt.get('bias') or '')
            factor=1.0
            if focus in ('risk_off_breadth','portfolio_cluster_risk'):
                factor=clamp(1-(max(0,activation-55)*.012),.42,.92);gates.append(f'Global {focus} reduced risk')
            elif focus in ('correlation_spike','volatility_regime'):
                factor=clamp(1-(max(0,activation-55)*.009),.55,.95);gates.append(f'Global {focus} tightened sizing')
            elif focus=='risk_on_breadth':factor=clamp(1+(max(0,activation-60)*.003),1,1.08)
            mult*=factor;layers.append({'layer':'global_attention','state':focus,'activation':round(activation,1),'factor':round(factor,3),'bias':bias})
            if focus=='risk_off_breadth' and activation>=82:permission='BLOCK_NEW_BUY';gates.append('Broad risk-off regime crossed hard gate')
        else:layers.append({'layer':'global_attention','state':'stale_or_baseline','factor':1.0})

        if local_evt and _age_seconds(local_evt.get('created_at'))<=420:
            assembly=str(local_evt.get('assembly') or 'baseline');activation=float(local_evt.get('activation') or 0);factor=1.0
            if assembly in ('behavioral_circuit','liquidity_stress','volatility_shock','concentration_guard','breakout_failure'):
                factor=clamp(1-(max(0,activation-55)*.011),.45,.92);gates.append(f'Local {assembly} inhibited ticker risk')
            elif assembly in ('trend_acceleration','breakout_pressure'):factor=clamp(1+(max(0,activation-60)*.0025),1,1.06)
            mult*=factor;layers.append({'layer':'ticker_attention','state':assembly,'activation':round(activation,1),'factor':round(factor,3),'reason':local_evt.get('reason')})
            if assembly=='behavioral_circuit' and activation>=80:permission='BLOCK_NEW_BUY';gates.append('Behavioral circuit breaker crossed hard gate')
            if assembly=='liquidity_stress' and activation>=86:permission='BLOCK_NEW_BUY';gates.append('Liquidity stress crossed hard gate')
        else:layers.append({'layer':'ticker_attention','state':'stale_or_baseline','factor':1.0})

        if hyp and _age_seconds(hyp.get('created_at'))<=600:
            winner=str(hyp.get('winner') or 'unresolved');confidence=float(hyp.get('confidence') or 0);factor=1.0
            if winner=='bull_continuation':factor=clamp(.96+(confidence/100)*.09,.96,1.05)
            elif winner=='mean_reversion':factor=.72
            elif winner=='unresolved':factor=.62;gates.append('Competing hypotheses remain unresolved')
            elif winner in ('stay_cash','portfolio_defense'):factor=0.0;permission='BLOCK_NEW_BUY';gates.append(f'Hypothesis winner is {winner}')
            mult*=factor;layers.append({'layer':'competing_hypotheses','state':winner,'confidence':round(confidence,1),'factor':round(factor,3)})
        else:
            # No fresh arena round: keep the fused sparse-brain score as a conservative fallback.
            fallback=clamp(.72+(score-50)*.012,.55,1.08);mult*=fallback;layers.append({'layer':'competing_hypotheses','state':'fallback_to_sparse_score','factor':round(fallback,3)})

        behavior=float(processors.get('behavior',82) or 82);factor=1.0
        if behavior<65:
            factor=clamp(.55+(behavior/65)*.35,.45,.9);mult*=factor;gates.append('Behavior processor reduced execution authority')
        layers.append({'layer':'sparse_processor_mesh','state':'fused_candidate','score':round(score,1),'behavior':round(behavior,1),'factor':round(factor,3)})

        if acct and acct.get('equity'):
            held=next((p for p in acct.get('positions',[]) if str(p.get('symbol') or '').upper()==symbol),None)
            if held:
                weight=float(held.get('market_value') or 0)/float(acct['equity'])*100
                if weight>25:
                    f=clamp(1-(weight-25)*.025,.4,1);mult*=f;gates.append('Existing position concentration reduced sizing');layers.append({'layer':'portfolio_state','state':'concentrated','weight_pct':round(weight,1),'factor':round(f,3)})
                else:layers.append({'layer':'portfolio_state','state':'normal','weight_pct':round(weight,1),'factor':1.0})
            else:layers.append({'layer':'portfolio_state','state':'new_position','factor':1.0})

        mult=round(clamp(mult,0,1.15),3)
        if permission!='BLOCK_NEW_BUY' and mult<.48:permission='REQUIRE_REVIEW'
        authority=round(clamp(mult*100,0,100),1)
        return {'symbol':symbol,'permission':permission,'size_multiplier':mult,'execution_authority':authority,'layers':layers,'gates':gates,'hierarchy':['global_attention','ticker_attention','competing_hypotheses','sparse_processor_mesh','portfolio_state']}

    base.v89_route_policy=route_policy

    class RouteReq(BaseModel):
        symbols:list[str]|None=None
        max_symbols:int=Field(default=8,ge=1,le=12)

    @app.post('/api/ai/hierarchical-route')
    async def hierarchical_route(req:RouteReq,request:Request):
        uid=base.current_user_id(request)
        if not hasattr(base,'purple_ai_scan'):
            return {'engine':'Purple Hierarchical Cognitive Router V8.9','routes':[],'note':'Sparse scan engine is not available.'}
        scan=await base.purple_ai_scan(uid,(req.symbols or None));acct=base.account_snapshot(uid);routes=[]
        for c in scan.get('candidates',[])[:req.max_symbols]:
            r=route_policy(uid,c,acct);r['candidate_score']=c.get('score');r['candidate_action']=c.get('action');r['confidence']=c.get('confidence');routes.append(r)
        routes.sort(key=lambda x:(x['permission']!='ALLOW',-x['execution_authority'],-float(x.get('candidate_score') or 0)))
        return {'engine':'Purple Hierarchical Cognitive Router V8.9','routes':routes,'account':{'equity':acct.get('equity'),'cash':acct.get('cash'),'positions':len(acct.get('positions',[]))},'simulation_only':True,'note':'Global context controls ticker attention; ticker context and competing hypotheses gate the sparse-brain signal; the resulting authority changes simulated position sizing and can block new fake-money buys.'}
