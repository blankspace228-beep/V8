import hashlib,json,math,secrets,time
from fastapi import HTTPException,Request
from pydantic import BaseModel,Field

CAP=10_000
BASE_BITS=18
MAX_BITS=32
TARGET_BLOCK_SECONDS=120
RETARGET_BLOCKS=12
MAX_BATCH=250_000
HALVING_INTERVAL=1250

class MineReq(BaseModel):
    nonce_start:int=Field(ge=0,le=9_000_000_000_000_000)
    attempts:int=Field(default=25_000,ge=1,le=MAX_BATCH)
    challenge:str=Field(min_length=16,max_length=128)

class UsefulReq(BaseModel):
    challenge:str=Field(min_length=16,max_length=128)
    values:list[float]=Field(min_length=32,max_length=512)


def register(app,base):
    def ensure():
        c=base.db()
        c.execute('''CREATE TABLE IF NOT EXISTS ppc_mining_state(id INTEGER PRIMARY KEY CHECK(id=1),height INTEGER NOT NULL DEFAULT 0,last_hash TEXT NOT NULL,difficulty_bits INTEGER NOT NULL DEFAULT 18,reward_units REAL NOT NULL DEFAULT 1,updated_at TEXT NOT NULL,last_block_at INTEGER NOT NULL DEFAULT 0)''')
        try:c.execute('ALTER TABLE ppc_mining_state ADD COLUMN last_block_at INTEGER NOT NULL DEFAULT 0')
        except:pass
        c.execute('''CREATE TABLE IF NOT EXISTS ppc_mining_challenges(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,challenge TEXT NOT NULL UNIQUE,height INTEGER NOT NULL,prev_hash TEXT NOT NULL,difficulty_bits INTEGER NOT NULL,expires_at INTEGER NOT NULL,used INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS ppc_mined_blocks(id INTEGER PRIMARY KEY AUTOINCREMENT,height INTEGER NOT NULL UNIQUE,user_id INTEGER NOT NULL,block_hash TEXT NOT NULL UNIQUE,prev_hash TEXT NOT NULL,nonce INTEGER NOT NULL,difficulty_bits INTEGER NOT NULL,reward_units REAL NOT NULL,created_at TEXT NOT NULL,created_ts INTEGER NOT NULL DEFAULT 0)''')
        try:c.execute('ALTER TABLE ppc_mined_blocks ADD COLUMN created_ts INTEGER NOT NULL DEFAULT 0')
        except:pass
        c.execute('''CREATE TABLE IF NOT EXISTS ppc_useful_work(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,challenge TEXT NOT NULL,work_hash TEXT NOT NULL UNIQUE,samples INTEGER NOT NULL,score REAL NOT NULL,created_at TEXT NOT NULL)''')
        c.execute("INSERT OR IGNORE INTO ppc_mining_state(id,height,last_hash,difficulty_bits,reward_units,updated_at,last_block_at) VALUES(1,0,?,18,1,?,0)",('0'*64,base.now_iso()))
        c.commit();c.close()
    ensure()

    def auth_uid(request:Request):
        try:return int(base.current_user_id(request))
        except HTTPException:raise
        except Exception:raise HTTPException(401,'Login required')

    def leading_zero_bits(raw:bytes):
        n=0
        for b in raw:
            if b==0:n+=8;continue
            n+=8-b.bit_length();break
        return n

    def supply(c):
        row=c.execute('SELECT minted,max_supply FROM purple_currency_supply WHERE id=1').fetchone()
        return (float(row['minted']),int(row['max_supply'])) if row else (0.0,CAP)

    def reward_for_height(height:int):
        era=max(0,(height-1)//HALVING_INTERVAL)
        return max(0.0625,1.0/(2**era))

    def network_bits(c):
        st=c.execute('SELECT * FROM ppc_mining_state WHERE id=1').fetchone();bits=int(st['difficulty_bits'] or BASE_BITS);height=int(st['height'])
        if height<RETARGET_BLOCKS or height%RETARGET_BLOCKS:return max(BASE_BITS,min(MAX_BITS,bits))
        rows=c.execute('SELECT created_ts FROM ppc_mined_blocks WHERE created_ts>0 ORDER BY height DESC LIMIT ?',(RETARGET_BLOCKS,)).fetchall()
        if len(rows)<RETARGET_BLOCKS:return bits
        newest=int(rows[0]['created_ts']);oldest=int(rows[-1]['created_ts']);actual=max(1,newest-oldest);target=TARGET_BLOCK_SECONDS*(RETARGET_BLOCKS-1)
        ratio=target/actual
        if ratio>1.35:bits+=1
        elif ratio<0.70:bits-=1
        return max(BASE_BITS,min(MAX_BITS,bits))

    def status_for(uid:int):
        ensure();c=base.db();st=c.execute('SELECT * FROM ppc_mining_state WHERE id=1').fetchone();minted,cap=supply(c);bits=network_bits(c)
        mined=c.execute('SELECT COUNT(*) n,COALESCE(SUM(reward_units),0) r FROM ppc_mined_blocks WHERE user_id=?',(uid,)).fetchone();useful=c.execute('SELECT COUNT(*) n FROM ppc_useful_work WHERE user_id=?',(uid,)).fetchone();c.close()
        h=int(st['height'])+1;reward=reward_for_height(h)
        return {'protocol':'Purple Proof Network','algorithm':'SHA-256 chained proof-of-work + verifiable useful work','height':int(st['height']),'last_hash':st['last_hash'],'difficulty_bits':bits,'estimated_attempts':2**bits,'target_block_seconds':TARGET_BLOCK_SECONDS,'retarget_blocks':RETARGET_BLOCKS,'reward_ppc':reward,'halving_interval':HALVING_INTERVAL,'next_halving_height':((int(st['height'])//HALVING_INTERVAL)+1)*HALVING_INTERVAL,'minted':minted,'hard_cap':cap,'remaining':max(0,cap-minted),'blocks_mined':int(mined['n']),'mined_ppc':float(mined['r']),'useful_jobs':int(useful['n']),'real_money_value':False,'cash_redemption':False,'note':'Proof-of-work creates measurable computational scarcity. Electricity cost is not a price floor; market value requires independent demand and utility.'}

    @app.get('/api/mining/status')
    def mining_status(request:Request):
        return status_for(auth_uid(request))

    @app.post('/api/mining/challenge')
    def mining_challenge(request:Request):
        ensure();uid=auth_uid(request);c=base.db();st=c.execute('SELECT * FROM ppc_mining_state WHERE id=1').fetchone();minted,cap=supply(c)
        if minted>=cap:c.close();raise HTTPException(409,'All PPC has been issued')
        bits=network_bits(c);challenge=secrets.token_hex(24);exp=int(time.time())+300
        c.execute('DELETE FROM ppc_mining_challenges WHERE user_id=? OR expires_at<?',(uid,int(time.time())))
        c.execute('INSERT INTO ppc_mining_challenges(user_id,challenge,height,prev_hash,difficulty_bits,expires_at,used,created_at) VALUES(?,?,?,?,?,?,0,?)',(uid,challenge,int(st['height'])+1,st['last_hash'],bits,exp,base.now_iso()));c.commit();c.close()
        return {'challenge':challenge,'height':int(st['height'])+1,'prev_hash':st['last_hash'],'difficulty_bits':bits,'expires_at':exp,'reward_ppc':reward_for_height(int(st['height'])+1)}

    @app.post('/api/mining/useful-work')
    def useful_work(req:UsefulReq,request:Request):
        uid=auth_uid(request);c=base.db();ch=c.execute('SELECT * FROM ppc_mining_challenges WHERE challenge=? AND user_id=?',(req.challenge,uid)).fetchone()
        if not ch or ch['used'] or int(ch['expires_at'])<int(time.time()):c.close();raise HTTPException(409,'Challenge expired')
        vals=[float(x) for x in req.values if math.isfinite(float(x))]
        if len(vals)<32:c.close();raise HTTPException(400,'At least 32 finite samples required')
        mean=sum(vals)/len(vals);variance=sum((x-mean)**2 for x in vals)/len(vals);score=math.sqrt(variance)
        canonical=json.dumps([round(x,8) for x in vals],separators=(',',':'))
        wh=hashlib.sha256((req.challenge+'|'+canonical).encode()).hexdigest()
        c.execute('INSERT OR IGNORE INTO ppc_useful_work(user_id,challenge,work_hash,samples,score,created_at) VALUES(?,?,?,?,?,?)',(uid,req.challenge,wh,len(vals),score,base.now_iso()));c.commit();c.close()
        return {'verified':True,'work_hash':wh,'samples':len(vals),'volatility_score':score,'note':'Verified useful-work receipt; it does not mint PPC by itself.'}

    @app.post('/api/mining/mine')
    def mine(req:MineReq,request:Request):
        ensure();uid=auth_uid(request);c=base.db();ch=c.execute('SELECT * FROM ppc_mining_challenges WHERE challenge=? AND user_id=?',(req.challenge,uid)).fetchone()
        if not ch or ch['used'] or int(ch['expires_at'])<int(time.time()):c.close();raise HTTPException(409,'Mining challenge expired or invalid')
        st=c.execute('SELECT * FROM ppc_mining_state WHERE id=1').fetchone()
        if int(ch['height'])!=int(st['height'])+1 or ch['prev_hash']!=st['last_hash']:c.close();raise HTTPException(409,'A newer block was found. Get a fresh challenge.')
        bits=int(ch['difficulty_bits']);found=None;prefix=f"PPC|{ch['height']}|{ch['prev_hash']}|{uid}|{ch['challenge']}|"
        for nonce in range(req.nonce_start,req.nonce_start+req.attempts):
            raw=hashlib.sha256((prefix+str(nonce)).encode()).digest()
            if leading_zero_bits(raw)>=bits:found=(nonce,raw.hex());break
        if not found:c.close();return {'found':False,'attempts':req.attempts,'next_nonce':req.nonce_start+req.attempts,'difficulty_bits':bits}
        try:
            c.execute('BEGIN IMMEDIATE');st=c.execute('SELECT * FROM ppc_mining_state WHERE id=1').fetchone();minted,cap=supply(c)
            if int(ch['height'])!=int(st['height'])+1 or ch['prev_hash']!=st['last_hash']:raise HTTPException(409,'Another miner won this block')
            if minted>=cap:raise HTTPException(409,'All PPC has been issued')
            nonce,bh=found;reward=min(reward_for_height(int(ch['height'])),max(0,cap-minted));now=int(time.time())
            c.execute('UPDATE purple_currency_supply SET minted=minted+? WHERE id=1 AND minted+?<=max_supply',(reward,reward))
            c.execute('INSERT OR IGNORE INTO user_purple_currency(user_id,balance,updated_at) VALUES(?,0,?)',(uid,base.now_iso()))
            c.execute('UPDATE user_purple_currency SET balance=balance+?,updated_at=? WHERE user_id=?',(reward,base.now_iso(),uid))
            c.execute('INSERT INTO purple_currency_ledger(user_id,delta,reason,level,created_at) VALUES(?,?,?,?,?)',(uid,reward,'proof_of_work_mining',int(ch['height']),base.now_iso()))
            c.execute('INSERT INTO ppc_mined_blocks(height,user_id,block_hash,prev_hash,nonce,difficulty_bits,reward_units,created_at,created_ts) VALUES(?,?,?,?,?,?,?,?,?)',(int(ch['height']),uid,bh,ch['prev_hash'],nonce,bits,reward,base.now_iso(),now))
            c.execute('UPDATE ppc_mining_state SET height=?,last_hash=?,difficulty_bits=?,reward_units=?,updated_at=?,last_block_at=? WHERE id=1',(int(ch['height']),bh,network_bits(c),reward_for_height(int(ch['height'])+1),base.now_iso(),now))
            c.execute('UPDATE ppc_mining_challenges SET used=1 WHERE id=?',(int(ch['id']),));c.commit()
        except Exception:
            c.rollback();c.close();raise
        c.close();return {'found':True,'height':int(ch['height']),'block_hash':bh,'nonce':nonce,'reward_ppc':reward,'status':status_for(uid)}

    from .v101_world import register as register_world
    register_world(app,base)
