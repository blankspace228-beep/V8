import base64,hashlib,hmac,json,secrets
from datetime import datetime,timezone,timedelta
from fastapi import HTTPException,Request,Response
from pydantic import BaseModel,Field


def register(app,base):
    # V9.5: prevent secondary-market buys from creating PPC. Buys can only consume
    # coins previously sold into the exchange reserve. Identity vaults are signed,
    # browser-held recovery capsules for rebuilding a login after ephemeral DB loss.
    SECRET=(base.OWNER_SETUP_CODE or 'purple-paper-local-v95').encode()

    def ensure():
        c=base.db();c.executescript('''
        CREATE TABLE IF NOT EXISTS purple_coin_exchange_reserve(
          id INTEGER PRIMARY KEY CHECK(id=1), balance INTEGER NOT NULL DEFAULT 0,
          bought INTEGER NOT NULL DEFAULT 0, sold INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS purple_coin_security_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,kind TEXT NOT NULL,
          detail TEXT NOT NULL,created_at TEXT NOT NULL);
        ''');c.execute('INSERT OR IGNORE INTO purple_coin_exchange_reserve(id,balance,updated_at) VALUES(1,0,?)',(base.now_iso(),));c.commit();c.close()

    def b64(b):return base64.urlsafe_b64encode(b).decode().rstrip('=')
    def unb64(s):return base64.urlsafe_b64decode(s+'='*((4-len(s)%4)%4))
    def sign(payload):
        raw=json.dumps(payload,separators=(',',':'),sort_keys=True).encode();sig=hmac.new(SECRET,raw,hashlib.sha256).digest();return b64(raw)+'.'+b64(sig)
    def verify(token):
        try:
            a,b=token.split('.',1);raw=unb64(a);sig=unb64(b)
            if not hmac.compare_digest(sig,hmac.new(SECRET,raw,hashlib.sha256).digest()):return None
            p=json.loads(raw);issued=datetime.fromisoformat(p['issued_at'])
            if datetime.now(timezone.utc)-issued>timedelta(days=365):return None
            return p
        except Exception:return None

    # Longer remembered sessions. The password itself is never stored in the browser vault.
    def create_long_session(response,user_id):
        raw=secrets.token_urlsafe(32);created=datetime.now(timezone.utc);expires=created+timedelta(days=180);c=base.db();c.execute('DELETE FROM auth_sessions WHERE expires_at<=?',(created.isoformat(),));c.execute('INSERT INTO auth_sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)',(base._token_hash(raw),user_id,created.isoformat(),expires.isoformat()));c.commit();c.close();response.set_cookie(base.SESSION_COOKIE,raw,httponly=True,secure=base.COOKIE_SECURE,samesite='lax',max_age=180*24*3600,path='/')
    base.create_session=create_long_session

    @app.get('/api/auth/account-vault')
    def account_vault(request:Request):
        u=base.current_user_from_request(request);keys=set(u.keys());payload={'username':u['username'],'role':u['role'],'email':u['email'] if 'email' in keys else None,'issued_at':base.now_iso(),'version':1};return {'capsule':sign(payload),'username':u['username'],'expires_days':365,'contains_password':False}

    class RestoreReq(BaseModel):
        capsule:str=Field(min_length=20,max_length=4096);password:str=Field(min_length=8,max_length=128)

    @app.post('/api/auth/restore-account')
    def restore_account(req:RestoreReq,response:Response):
        p=verify(req.capsule)
        if not p:raise HTTPException(403,'Account recovery capsule is invalid or expired')
        username=str(p.get('username','')).strip();role=str(p.get('role','player'))
        if role not in {'owner','admin','moderator','coach','player'}:role='player'
        c=base.db();existing=c.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
        if existing:
            c.close()
            if not hmac.compare_digest(existing['password_hash'],base._password_hash(req.password,existing['password_salt'])):raise HTTPException(401,'That account exists; use its current password')
            create_long_session(response,existing['id']);return {'ok':True,'restored':False,'user':base.public_user(existing)}
        # Owner recovery is allowed only when no owner exists. Other roles restore only identity,
        # never balances/PPC, preventing replay of an old capsule to duplicate currency.
        if role=='owner' and c.execute("SELECT 1 FROM users WHERE role='owner'").fetchone():c.close();raise HTTPException(409,'An Owner already exists; recovery refused')
        salt,ph=base._new_password(req.password);email=(p.get('email') or None);cur=c.execute('INSERT INTO users(username,password_hash,password_salt,role,is_active,created_at,email,email_verified) VALUES(?,?,?,?,1,?,?,?)',(username,ph,salt,role,base.now_iso(),email,1));uid=cur.lastrowid;c.commit();row=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();c.close();base.ensure_user_account(uid);create_long_session(response,uid);return {'ok':True,'restored':True,'identity_only':True,'user':base.public_user(row),'note':'Identity restored. Currency/balances are never restored from browser data.'}

    class CoinOrder(BaseModel):side:str=Field(pattern='^(buy|sell)$');amount:int=Field(ge=1,le=1000)

    # Replace V9.4 trade endpoint so a BUY cannot manufacture a new PPC balance.
    app.router.routes[:]=[r for r in app.router.routes if getattr(r,'path',None)!='/api/economy/purple-coin/trade']

    @app.post('/api/economy/purple-coin/trade')
    def secure_coin_trade(req:CoinOrder,request:Request):
        uid=base.current_user_id(request);base.v94_coin_sync(uid);ensure();c=base.db()
        try:
            c.execute('BEGIN IMMEDIATE');m=c.execute('SELECT * FROM purple_coin_market WHERE id=1').fetchone();price=float(m['price']);qty=int(req.amount);notional=price*qty;c.execute('INSERT OR IGNORE INTO user_purple_currency(user_id) VALUES(?)',(uid,));w=c.execute('SELECT * FROM user_purple_currency WHERE user_id=?',(uid,)).fetchone();acct=c.execute('SELECT cash FROM user_accounts WHERE user_id=?',(uid,)).fetchone();reserve=c.execute('SELECT * FROM purple_coin_exchange_reserve WHERE id=1').fetchone()
            if req.side=='buy':
                if int(reserve['balance'])<qty:raise HTTPException(409,f'Only {int(reserve["balance"])} PPC are currently offered in the exchange reserve')
                if not acct or float(acct['cash'])<notional:raise HTTPException(409,'Not enough simulated cash')
                c.execute('UPDATE user_accounts SET cash=cash-? WHERE user_id=?',(notional,uid));c.execute('UPDATE user_purple_currency SET balance=balance+? WHERE user_id=?',(qty,uid));c.execute('UPDATE purple_coin_exchange_reserve SET balance=balance-?,bought=bought+?,updated_at=? WHERE id=1',(qty,qty,base.now_iso()));pressure=qty
            else:
                if int(w['balance'])<qty:raise HTTPException(409,'Not enough Purple Coin')
                c.execute('UPDATE user_purple_currency SET balance=balance-? WHERE user_id=?',(qty,uid));c.execute('UPDATE user_accounts SET cash=cash+? WHERE user_id=?',(notional,uid));c.execute('UPDATE purple_coin_exchange_reserve SET balance=balance+?,sold=sold+?,updated_at=? WHERE id=1',(qty,qty,base.now_iso()));pressure=-qty
            circ=max(1,int(c.execute('SELECT minted-burned n FROM purple_currency_supply WHERE id=1').fetchone()['n']));impact=max(-.05,min(.05,pressure/max(250,circ)*.08));new=max(.05,min(1000.0,price*(1+impact)));c.execute('UPDATE purple_coin_market SET prev_price=price,price=?,volume=volume+?,buy_pressure=buy_pressure+?,sell_pressure=sell_pressure+?,updated_at=? WHERE id=1',(new,notional,qty if req.side=='buy' else 0,qty if req.side=='sell' else 0,base.now_iso()));c.execute('INSERT INTO purple_coin_price_history(price,volume,reason,created_at) VALUES(?,?,?,?)',(new,notional,'SECURE_'+req.side.upper(),base.now_iso()));c.execute('INSERT INTO purple_currency_ledger(user_id,delta,reason,level,trade_count,created_at) VALUES(?,?,?,?,?,?)',(uid,qty if req.side=='buy' else -qty,'EXCHANGE_'+req.side.upper(),None,None,base.now_iso()));c.commit()
        except HTTPException:c.rollback();raise
        except Exception:c.rollback();raise
        finally:c.close()
        return {'ok':True,'coin':base.v94_coin_sync(uid),'account':base.account_snapshot(uid),'conservation_rule':'Secondary-market buys only transfer PPC already held by the exchange reserve; they never mint PPC.'}

    @app.get('/api/economy/security')
    def economy_security(request:Request):
        uid=base.current_user_id(request);ensure();c=base.db();r=dict(c.execute('SELECT * FROM purple_coin_exchange_reserve WHERE id=1').fetchone());flags=c.execute('SELECT COUNT(*) n FROM purple_coin_flags WHERE user_id=?',(uid,)).fetchone()['n'];c.close();return {'exchange_reserve':r,'anti_farm_flags':int(flags),'protections':['hard capped mint ledger','unique level rewards','daily mint ceiling','meaningful-trade filter','rapid-churn detection','reserve-backed secondary trading','server-side transactions','identity-only signed recovery vault']}
