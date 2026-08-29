import hashlib,json,math,secrets,time
from fastapi import HTTPException,Request
from pydantic import BaseModel,Field

CAP=10_000
BASE_DIFFICULTY=18
MAX_BATCH=250_000

class MineReq(BaseModel):
    nonce_start:int=Field(ge=0,le=9_000_000_000_000_000)
    attempts:int=Field(default=25_000,ge=1,le=MAX_BATCH)
    challenge:str=Field(min_length=16,max_length=128)


def register(app,base):
    def ensure():
        c=base.db()
        c.execute('''CREATE TABLE IF NOT EXISTS ppc_mining_state(id INTEGER PRIMARY KEY CHECK(id=1),height INTEGER NOT NULL DEFAULT 0,last_hash TEXT NOT NULL,difficulty_bits INTEGER NOT NULL DEFAULT 18,reward_units INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS ppc_mining_challenges(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,challenge TEXT NOT NULL UNIQUE,height INTEGER NOT NULL,prev_hash TEXT NOT NULL,difficulty_bits INTEGER NOT NULL,expires_at INTEGER NOT NULL,used INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS ppc_mined_blocks(id INTEGER PRIMARY KEY AUTOINCREMENT,height INTEGER NOT NULL UNIQUE,user_id INTEGER NOT NULL,block_hash TEXT NOT NULL UNIQUE,prev_hash TEXT NOT NULL,nonce INTEGER NOT NULL,difficulty_bits INTEGER NOT NULL,reward_units INTEGER NOT NULL,created_at TEXT NOT NULL)''')
        c.execute("INSERT OR IGNORE INTO ppc_mining_state(id,height,last_hash,difficulty_bits,reward_units,updated_at) VALUES(1,0,?,18,1,?)",('0'*64,base.now_iso()))
        c.commit();c.close()
    ensure()

    def leading_zero_bits(raw:bytes):
        n=0
        for b in raw:
            if b==0:n+=8;continue
            n+=8-b.bit_length();break
        return n

    def supply(c):
        row=c.execute('SELECT minted,max_supply FROM purple_currency_supply WHERE id=1').fetchone()
        return (int(row['minted']),int(row['max_supply'])) if row else (0,CAP)

    def dynamic_bits(minted:int):
        # Scarcity raises work as the fixed 10,000 PPC cap fills. This is protocol difficulty, not a price promise.
        fill=max(0,min(0.9999,minted/CAP))
        return min(30,BASE_DIFFICULTY+int(fill*10))

    def status_for(uid:int):
        ensure();c=base.db();st=c.execute('SELECT * FROM ppc_mining_state WHERE id=1').fetchone();minted,cap=supply(c)
        mined=c.execute('SELECT COUNT(*) n,COALESCE(SUM(reward_units),0) r FROM ppc_mined_blocks WHERE user_id=?',(uid,)).fetchone();c.close()
        bits=dynamic_bits(minted)
        return {'protocol':'Purple Proof Mining','algorithm':'SHA-256 chained proof-of-work','height':int(st['height']),'last_hash':st['last_hash'],'difficulty_bits':bits,'estimated_attempts':2**bits,'reward_ppc':1,'minted':minted,'hard_cap':cap,'remaining':max(0,cap-minted),'blocks_mined':int(mined['n']),'mined_ppc':int(mined['r']),'real_money_value':False,'note':'Mining creates scarce protocol issuance and network-verifiable work. It does not guarantee a market price.'}

    @app.get('/api/mining/status')
    def mining_status(request:Request):
        u=base.current_user(request)
        if not u:raise HTTPException(401,'Login required')
        return status_for(int(u['id']))

    @app.post('/api/mining/challenge')
    def mining_challenge(request:Request):
        u=base.current_user(request)
        if not u:raise HTTPException(401,'Login required')
        ensure();uid=int(u['id']);c=base.db();st=c.execute('SELECT * FROM ppc_mining_state WHERE id=1').fetchone();minted,cap=supply(c)
        if minted>=cap:c.close();raise HTTPException(409,'All PPC has been issued')
        challenge=secrets.token_hex(24);exp=int(time.time())+180
        c.execute('DELETE FROM ppc_mining_challenges WHERE user_id=? OR expires_at<?',(uid,int(time.time())))
        c.execute('INSERT INTO ppc_mining_challenges(user_id,challenge,height,prev_hash,difficulty_bits,expires_at,used,created_at) VALUES(?,?,?,?,?,?,0,?)',(uid,challenge,int(st['height'])+1,st['last_hash'],dynamic_bits(minted),exp,base.now_iso()));c.commit();c.close()
        return {'challenge':challenge,'height':int(st['height'])+1,'prev_hash':st['last_hash'],'difficulty_bits':dynamic_bits(minted),'expires_at':exp}

    @app.post('/api/mining/mine')
    def mine(req:MineReq,request:Request):
        u=base.current_user(request)
        if not u:raise HTTPException(401,'Login required')
        ensure();uid=int(u['id']);c=base.db();ch=c.execute('SELECT * FROM ppc_mining_challenges WHERE challenge=? AND user_id=?',(req.challenge,uid)).fetchone()
        if not ch or ch['used'] or int(ch['expires_at'])<int(time.time()):c.close();raise HTTPException(409,'Mining challenge expired or invalid')
        st=c.execute('SELECT * FROM ppc_mining_state WHERE id=1').fetchone()
        if int(ch['height'])!=int(st['height'])+1 or ch['prev_hash']!=st['last_hash']:c.close();raise HTTPException(409,'A newer block was found. Get a fresh challenge.')
        bits=int(ch['difficulty_bits']);found=None
        prefix=f"PPC|{ch['height']}|{ch['prev_hash']}|{uid}|{ch['challenge']}|"
        for nonce in range(req.nonce_start,req.nonce_start+req.attempts):
            raw=hashlib.sha256((prefix+str(nonce)).encode()).digest()
            if leading_zero_bits(raw)>=bits:found=(nonce,raw.hex());break
        if not found:c.close();return {'found':False,'attempts':req.attempts,'next_nonce':req.nonce_start+req.attempts,'difficulty_bits':bits}
        try:
            c.execute('BEGIN IMMEDIATE');st=c.execute('SELECT * FROM ppc_mining_state WHERE id=1').fetchone();minted,cap=supply(c)
            if int(ch['height'])!=int(st['height'])+1 or ch['prev_hash']!=st['last_hash']:raise HTTPException(409,'Another miner won this block')
            if minted>=cap:raise HTTPException(409,'All PPC has been issued')
            nonce,bh=found
            c.execute('UPDATE purple_currency_supply SET minted=minted+1 WHERE id=1 AND minted<max_supply')
            c.execute('INSERT OR IGNORE INTO user_purple_currency(user_id,balance,updated_at) VALUES(?,0,?)',(uid,base.now_iso()))
            c.execute('UPDATE user_purple_currency SET balance=balance+1,updated_at=? WHERE user_id=?',(base.now_iso(),uid))
            c.execute('INSERT INTO purple_currency_ledger(user_id,delta,reason,level,created_at) VALUES(?,1,?,?,?)',(uid,'proof_of_work_mining',int(ch['height']),base.now_iso()))
            c.execute('INSERT INTO ppc_mined_blocks(height,user_id,block_hash,prev_hash,nonce,difficulty_bits,reward_units,created_at) VALUES(?,?,?,?,?,?,1,?)',(int(ch['height']),uid,bh,ch['prev_hash'],nonce,bits,base.now_iso()))
            c.execute('UPDATE ppc_mining_state SET height=?,last_hash=?,difficulty_bits=?,updated_at=? WHERE id=1',(int(ch['height']),bh,dynamic_bits(minted+1),base.now_iso()))
            c.execute('UPDATE ppc_mining_challenges SET used=1 WHERE id=?',(int(ch['id']),));c.commit()
        except Exception:
            c.rollback();c.close();raise
        c.close();return {'found':True,'height':int(ch['height']),'block_hash':bh,'nonce':nonce,'reward_ppc':1,'status':status_for(uid)}
