import json,math
from fastapi import Request,HTTPException
from pydantic import BaseModel,Field

class FeedbackReq(BaseModel):
    subsystem:str=Field(min_length=2,max_length=64)
    outcome:str=Field(pattern='^(success|failure|correction)$')
    pattern:str=Field(min_length=2,max_length=240)
    lesson:str=Field(min_length=2,max_length=500)
    score:float=Field(default=0,ge=-1,le=1)


def register(app,base):
    """V10.3: transparent adaptive memory for Purple's own agents.
    Learns from Purple Paper outcomes/corrections and public research principles;
    it does not copy proprietary model weights, prompts, or private source code.
    """
    def ensure():
        c=base.db()
        c.execute('''CREATE TABLE IF NOT EXISTS purple_learning_memory(
          id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,subsystem TEXT NOT NULL,outcome TEXT NOT NULL,
          pattern TEXT NOT NULL,lesson TEXT NOT NULL,score REAL NOT NULL DEFAULT 0,hits INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(subsystem,pattern,lesson))''')
        c.execute('''CREATE TABLE IF NOT EXISTS purple_agent_reputation(
          agent TEXT PRIMARY KEY,wins INTEGER NOT NULL DEFAULT 0,losses INTEGER NOT NULL DEFAULT 0,
          corrections INTEGER NOT NULL DEFAULT 0,reliability REAL NOT NULL DEFAULT .5,updated_at TEXT NOT NULL)''')
        for a in ['trend','momentum','volatility','risk','diversification','behavior','market-regime','skeptic','historian','coach']:
            c.execute('INSERT OR IGNORE INTO purple_agent_reputation(agent,updated_at) VALUES(?,?)',(a,base.now_iso()))
        c.commit();c.close()
    ensure()

    def uid(request):
        try:return int(base.current_user_id(request))
        except:raise HTTPException(401,'Login required')

    def record(user_id,subsystem,outcome,pattern,lesson,score=0):
        ensure();c=base.db();now=base.now_iso()
        c.execute('''INSERT INTO purple_learning_memory(user_id,subsystem,outcome,pattern,lesson,score,hits,created_at,updated_at)
          VALUES(?,?,?,?,?,?,1,?,?) ON CONFLICT(subsystem,pattern,lesson) DO UPDATE SET
          outcome=excluded.outcome,score=(purple_learning_memory.score*purple_learning_memory.hits+excluded.score)/(purple_learning_memory.hits+1),
          hits=purple_learning_memory.hits+1,updated_at=excluded.updated_at''',(user_id,subsystem,outcome,pattern,lesson,float(score),now,now))
        c.commit();c.close()

    @app.post('/api/ai/learning/feedback')
    def feedback(req:FeedbackReq,request:Request):
        user=uid(request);record(user,req.subsystem,req.outcome,req.pattern,req.lesson,req.score)
        return {'ok':True,'learned':True,'scope':'Purple Paper adaptive memory'}

    @app.get('/api/ai/learning/status')
    def status(request:Request):
        uid(request);ensure();c=base.db()
        rows=c.execute('''SELECT subsystem,outcome,pattern,lesson,score,hits,updated_at FROM purple_learning_memory ORDER BY hits DESC,updated_at DESC LIMIT 30''').fetchall()
        reps=c.execute('SELECT * FROM purple_agent_reputation ORDER BY reliability DESC').fetchall();c.close()
        return {'version':'V10.3','architecture':'multi-agent critique + outcome memory + reputation weighting + correction memory',
          'principles':['independent candidate analyses','critic/revision pass','explicit failure memory','reputation weighted convergence','human correction retention','evaluation before promotion'],
          'research_basis':['public OpenAI research on pretraining/post-training/evaluation','public Anthropic Constitutional AI critique-and-revision concepts'],
          'proprietary_copying':False,'memories':[dict(x) for x in rows],'agents':[dict(x) for x in reps]}

    @app.get('/api/ai/learning/lessons/{subsystem}')
    def lessons(subsystem:str,request:Request):
        uid(request);ensure();c=base.db();rows=c.execute('''SELECT outcome,pattern,lesson,score,hits FROM purple_learning_memory WHERE subsystem=? ORDER BY hits DESC,score DESC LIMIT 12''',(subsystem[:64],)).fetchall();c.close()
        return {'subsystem':subsystem,'lessons':[dict(x) for x in rows]}

    base.purple_record_learning=record
