import os,hmac,hashlib
from fastapi import HTTPException,Request,Response
from pydantic import BaseModel,Field


def register(app,base):
    RESERVED=(os.getenv('OWNER_ACCOUNT_USERNAME','austinbterrey').strip() or 'austinbterrey')
    RESERVED_N=RESERVED.casefold()

    def ensure():
        c=base.db();c.executescript('''
        CREATE TABLE IF NOT EXISTS owner_server_lock(
          id INTEGER PRIMARY KEY CHECK(id=1),
          bound_username TEXT NOT NULL,
          claimed_user_id INTEGER NOT NULL,
          claimed_at TEXT NOT NULL,
          code_fingerprint TEXT NOT NULL
        );
        ''');c.commit();c.close()

    def owner_state():
        ensure();c=base.db();lock=c.execute('SELECT * FROM owner_server_lock WHERE id=1').fetchone();owners=c.execute("SELECT id,username FROM users WHERE role='owner' ORDER BY id").fetchall();c.close()
        return {'reserved_username':RESERVED,'claimed':bool(lock or owners),'locked_to':(lock['bound_username'] if lock else (owners[0]['username'] if owners else None)),'owner_count':len(owners)}

    # All normal signups start as Player. Owner elevation happens only from Account settings.
    app.router.routes[:]=[r for r in app.router.routes if getattr(r,'path',None)!='/api/auth/signup']

    class Signup(BaseModel):
        username:str=Field(min_length=3,max_length=32)
        password:str=Field(min_length=8,max_length=128)
        email:str|None=Field(default=None,max_length=254)
        setup_code:str|None=Field(default=None,max_length=256)

    @app.post('/api/auth/signup')
    async def signup_player(req:Signup,response:Response):
        username=req.username.strip();c=base.db()
        if not username.replace('_','').replace('-','').isalnum():c.close();raise HTTPException(400,'Username may use letters, numbers, underscores, and hyphens')
        if c.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone():c.close();raise HTTPException(409,'Username already exists')
        email=(req.email or '').strip().lower() or None;reserved=(username.casefold()==RESERVED_N)
        if not reserved and os.getenv('EMAIL_VERIFICATION_REQUIRED','1').lower() in {'1','true','yes','on'}:
            if not email or '@' not in email or email.startswith('@') or email.endswith('@'):c.close();raise HTTPException(400,'A valid email is required for player accounts')
        salt,ph=base._new_password(req.password)
        cur=c.execute('INSERT INTO users(username,password_hash,password_salt,role,is_active,created_at,email,email_verified) VALUES(?,?,?,?,1,?,?,?)',(username,ph,salt,'player',base.now_iso(),email,1 if reserved else 0));uid=cur.lastrowid;c.commit();row=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();c.close();base.ensure_user_account(uid);base.create_session(response,uid)
        return {'ok':True,'user':base.public_user(row),'owner_claim_available':reserved and not owner_state()['claimed'],'note':'Account created as Player. The reserved Owner account can be promoted from Account settings with the Owner Setup Code.'}

    class ClaimReq(BaseModel):
        code:str=Field(min_length=8,max_length=256)

    @app.get('/api/owner/claim-status')
    def claim_status(request:Request):
        u=base.current_user_from_request(request,required=False);st=owner_state();st['signed_in']=bool(u);st['current_username']=u['username'] if u else None;st['can_claim']=bool(u and u['username'].casefold()==RESERVED_N and not st['claimed']);st['is_owner']=bool(u and u['role']=='owner');return st

    @app.post('/api/owner/claim')
    def claim_owner(req:ClaimReq,request:Request):
        u=base.current_user_from_request(request)
        if u['username'].casefold()!=RESERVED_N:raise HTTPException(403,f'Owner access is permanently reserved for {RESERVED}.')
        if not base.OWNER_SETUP_CODE:raise HTTPException(503,'OWNER_SETUP_CODE is not configured on this server')
        if not hmac.compare_digest(req.code.strip(),base.OWNER_SETUP_CODE):raise HTTPException(403,'Incorrect Owner Setup Code')
        ensure();c=base.db()
        try:
            c.execute('BEGIN IMMEDIATE');lock=c.execute('SELECT * FROM owner_server_lock WHERE id=1').fetchone();owners=c.execute("SELECT id,username FROM users WHERE role='owner'").fetchall()
            if lock and lock['bound_username'].casefold()!=RESERVED_N:raise HTTPException(409,'This server Owner slot is already permanently bound.')
            if lock and int(lock['claimed_user_id'])!=int(u['id']):raise HTTPException(409,f"This server's Owner slot is permanently bound to {lock['bound_username']}.")
            if any(int(x['id'])!=int(u['id']) for x in owners):raise HTTPException(409,'This server already has an Owner account. Owner access cannot be transferred.')
            fp=hashlib.sha256(base.OWNER_SETUP_CODE.encode()).hexdigest()[:16]
            c.execute("UPDATE users SET role='owner',email_verified=1 WHERE id=?",(u['id'],))
            c.execute('INSERT OR IGNORE INTO owner_server_lock(id,bound_username,claimed_user_id,claimed_at,code_fingerprint) VALUES(1,?,?,?,?)',(RESERVED,u['id'],base.now_iso(),fp))
            acct=c.execute('SELECT * FROM user_accounts WHERE user_id=?',(u['id'],)).fetchone()
            if acct and float(acct['cash'])==0 and c.execute('SELECT COUNT(*) n FROM user_trades WHERE user_id=?',(u['id'],)).fetchone()['n']==0:
                c.execute('UPDATE user_accounts SET cash=?,starting_cash=? WHERE user_id=?',(base.STARTING_CASH,base.STARTING_CASH,u['id']))
            c.commit()
        except HTTPException:c.rollback();raise
        except Exception:c.rollback();raise
        finally:c.close()
        try:
            if hasattr(base,'v96_mirror_user'):base.v96_mirror_user(u['id'])
        except Exception:pass
        c=base.db();row=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone();c.close();return {'ok':True,'user':base.public_user(row),'permanent_binding':RESERVED,'transferable':False,'message':'Owner access is now permanently bound to this account on this server.'}

    base.v97_owner_state=owner_state
