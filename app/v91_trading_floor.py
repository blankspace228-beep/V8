import json
from types import SimpleNamespace
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field


def register(app, base):
    def clamp(x,a,b): return max(a,min(b,x))
    scan_ep=next((r.endpoint for r in app.router.routes if getattr(r,'path',None)=='/api/ai/scan' and 'POST' in getattr(r,'methods',set())),None)

    async def scan(request,symbol):
        if not scan_ep: raise HTTPException(503,'Sparse AI scan unavailable')
        d=await scan_ep(SimpleNamespace(symbols=[symbol]),request)
        return next((x for x in d.get('candidates',[]) if x.get('symbol')==symbol),None)

    def floor_debate(uid,c,acct,route,img):
        p=c.get('processors') or {}; score=float(c.get('score') or 50); conf=float(c.get('confidence') or 50)
        robust=float(img.get('robustness_score') or 50); auth=float(route.get('execution_authority') or 0)
        agents=[
          ('Maya','Lead Trader','Find the strongest actionable edge', clamp(score*.62+conf*.18+auth*.20,0,100)),
          ('Theo','Trend Desk','Judge continuation and structure', float(p.get('trend',50))),
          ('Mina','Momentum Desk','Measure acceleration and follow-through', float(p.get('momentum',50))),
          ('Victor','Volatility Desk','Challenge trades that cannot survive noise', float(p.get('volatility',50))),
          ('Lena','Liquidity Desk','Check execution quality and spread', float(p.get('spread',50))),
          ('Drew','Diversification Desk','Protect against hidden concentration', float(p.get('diversification',50))),
          ('Rhea','Risk Manager','Stress the idea before capital is committed', robust),
          ('Quinn','Contrarian','Argue the strongest case against consensus', clamp(100-score*.55-robust*.25+35,0,100)),
          ('Sage','Behavior Officer','Stop emotion/chasing from becoming a trade', float(p.get('behavior',50))),
          ('Iris','Scenario Analyst','Compare multiple hypothetical futures', robust),
        ]
        transcript=[];votes=[]
        for name,role,mission,v in agents:
            stance='BUY' if v>=68 else 'WAIT' if v>=48 else 'NO TRADE'
            if role=='Contrarian': stance='CHALLENGE' if score>=62 else 'WAIT'
            text=f'{mission}. My evidence score is {v:.0f}/100.'
            if stance=='BUY': text+=' I support the simulated long, but only inside the risk gates.'
            elif stance=='NO TRADE': text+=' I do not think the edge compensates for the current risk.'
            elif stance=='CHALLENGE': text+=' The floor is getting excited; prove the downside case is survivable before we act.'
            else:text+=' I want more confirmation before committing fake capital.'
            transcript.append({'agent':name,'role':role,'stance':stance,'message':text,'evidence_score':round(v,1)})
            votes.append((stance,v))
        # cross-talk: agents react to the strongest proposal and the risk manager has veto power
        buy=sum(1 for s,_ in votes if s=='BUY'); no=sum(1 for s,_ in votes if s=='NO TRADE'); wait=len(votes)-buy-no
        big_idea=score>=78 and robust>=68 and auth>=65
        if big_idea:
            transcript.append({'agent':'Maya','role':'Lead Trader','stance':'PROPOSAL','message':'High-conviction proposal detected. I am asking every desk to challenge it before the floor increases simulated conviction.','evidence_score':round((score+robust+auth)/3,1)})
            transcript.append({'agent':'Rhea','role':'Risk Manager','stance':'REVIEW','message':f'I ran the stress case. Robustness is {robust:.0f}/100. A large-looking opportunity does not bypass position limits or downside controls.','evidence_score':robust})
            transcript.append({'agent':'Quinn','role':'Contrarian','stance':'CHALLENGE','message':'I am deliberately opposing the exciting story. If the thesis only works in the upside scenario, the floor should not size up.','evidence_score':round(100-score*.5,1)})
        permission='ALLOW'
        if route.get('permission')=='BLOCK_NEW_BUY' or img.get('permission')=='BLOCK_NEW_BUY':permission='BLOCK_NEW_BUY'
        elif robust<52 or auth<48 or no>=4:permission='REQUIRE_REVIEW'
        consensus=clamp(score*.25+robust*.30+auth*.25+(buy/len(votes))*20,0,100)
        if permission=='ALLOW' and consensus<58:permission='REQUIRE_REVIEW'
        conviction='HIGH' if consensus>=76 and big_idea else 'MEDIUM' if consensus>=60 else 'LOW'
        return {'symbol':c['symbol'],'agents':transcript,'vote_summary':{'support':buy,'wait_or_challenge':wait,'oppose':no},'consensus_score':round(consensus,1),'conviction':conviction,'big_idea_flag':big_idea,'permission':permission,'final_statement':('Floor consensus supports a simulated trade within existing size limits.' if permission=='ALLOW' else 'The floor will not automatically commit new fake capital yet.'),'simulation_only':True}

    base.v91_floor_debate=floor_debate

    class Req(BaseModel):symbol:str=Field(default='NVDA',min_length=1,max_length=24)
    @app.post('/api/ai/trading-floor')
    async def trading_floor(req:Req,request:Request):
        uid=base.current_user_id(request);sym=req.symbol.strip().upper();c=await scan(request,sym)
        if not c:raise HTTPException(404,'No candidate data for that symbol')
        acct=base.account_snapshot(uid);route=base.v89_route_policy(uid,c,acct) if hasattr(base,'v89_route_policy') else {'permission':'ALLOW','size_multiplier':1,'execution_authority':100}
        # Reuse V9.0's forward simulator with a neutral 10% proposal for deliberation display.
        img=base.v90_imagine_candidate(uid,c,acct,route,10*float(route.get('size_multiplier') or 0)) if hasattr(base,'v90_imagine_candidate') else {'robustness_score':50,'permission':'REQUIRE_REVIEW'}
        floor=floor_debate(uid,c,acct,route,img)
        try:
            conn=base.db();conn.execute('INSERT INTO user_ai_decisions(user_id,symbol,action,score,confidence,detail,created_at) VALUES(?,?,?,?,?,?,?)',(uid,sym,'V91_FLOOR_DEBATE',c.get('score'),c.get('confidence'),json.dumps({'floor':floor},separators=(',',':')),base.now_iso()));conn.commit();conn.close()
        except Exception:pass
        return {'engine':'Purple Trading Floor V9.1','candidate':c,'hierarchical_route':route,'imagination':img,'floor':floor,'note':'Independent specialist agents debate the simulated trade, challenge high-conviction ideas, and then form a bounded consensus. No real brokerage order is sent.'}
