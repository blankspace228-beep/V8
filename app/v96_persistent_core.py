import os,json,hashlib,hmac,secrets
from datetime import datetime,timezone,timedelta
from fastapi import HTTPException,Request,Response
from pydantic import BaseModel,Field


def register(app,base):
    """V9.6 durable identity/economy mirror + PPC conservation monitor.
    Uses Render Postgres when PURPLE_DATABASE_URL is configured. SQLite remains the
    execution store during staged migration so the existing trading engine stays compatible.
    """
    URL=os.getenv('PURPLE_DATABASE_URL','').strip() or os.getenv('DATABASE_URL','').strip()
    pg=None
    if URL:
        try:
            import psycopg
            pg=psycopg
        except Exception:
            pg=None

    def connect():
        if not URL or not pg:return None
        return pg.connect(URL,autocommit=False)

    def ensure_pg():
        c=connect()
        if not c:return False
        with c:
            with c.cursor() as q:
                q.execute('''CREATE TABLE IF NOT EXISTS pp_users(
                  username TEXT PRIMARY KEY,password_hash TEXT NOT NULL,password_salt TEXT NOT NULL,
                  role TEXT NOT NULL,is_active BOOLEAN NOT NULL DEFAULT TRUE,email TEXT,email_verified BOOLEAN NOT NULL DEFAULT FALSE,
                  created_at TIMESTAMPTZ NOT NULL,last_login_at TIMESTAMPTZ,updated_at TIMESTAMPTZ NOT NULL)''')
                q.execute('''CREATE TABLE IF NOT EXISTS pp_accounts(
                  username TEXT PRIMARY KEY REFERENCES pp_users(username) ON DELETE CASCADE,
                  cash DOUBLE PRECISION NOT NULL,starting_cash DOUBLE PRECISION NOT NULL,realized_pl DOUBLE PRECISION NOT NULL,
                  updated_at TIMESTAMPTZ NOT NULL)''')
                q.execute('''CREATE TABLE IF NOT EXISTS pp_ppc_wallets(
                  username TEXT PRIMARY KEY REFERENCES pp_users(username) ON DELETE CASCADE,
                  balance BIGINT NOT NULL,lifetime_earned BIGINT NOT NULL,lifetime_burned BIGINT NOT NULL,
                  highest_rewarded_level INTEGER NOT NULL,updated_at TIMESTAMPTZ NOT NULL)''')
                q.execute('''CREATE TABLE IF NOT EXISTS pp_ppc_state(
                  id INTEGER PRIMARY KEY CHECK(id=1),hard_cap BIGINT NOT NULL,minted BIGINT NOT NULL,burned BIGINT NOT NULL,
                  exchange_reserve BIGINT NOT NULL,price DOUBLE PRECISION NOT NULL,updated_at TIMESTAMPTZ NOT NULL)''')
                q.execute('''CREATE TABLE IF NOT EXISTS pp_security_events(
                  id BIGSERIAL PRIMARY KEY,username TEXT,kind TEXT NOT NULL,severity TEXT NOT NULL,detail TEXT NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL)''')
        c.close();return True

    def mirror_user(uid):
        if not ensure_pg():return False
        s=base.db();u=s.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();a=s.execute('SELECT * FROM user_accounts WHERE user_id=?',(uid,)).fetchone();w=s.execute('SELECT * FROM user_purple_currency WHERE user_id=?',(uid,)).fetchone();sup=s.execute('SELECT * FROM purple_currency_supply WHERE id=1').fetchone();res=s.execute('SELECT balance FROM purple_coin_exchange_reserve WHERE id=1').fetchone();m=s.execute('SELECT price FROM purple_coin_market WHERE id=1').fetchone();s.close()
        if not u:return False
        keys=set(u.keys());now=base.now_iso();c=connect()
        with c:
            with c.cursor() as q:
                q.execute('''INSERT INTO pp_users(username,password_hash,password_salt,role,is_active,email,email_verified,created_at,last_login_at,updated_at)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash,
                  password_salt=excluded.password_salt,role=excluded.role,is_active=excluded.is_active,email=excluded.email,
                  email_verified=excluded.email_verified,last_login_at=excluded.last_login_at,updated_at=excluded.updated_at''',
                  (u['username'],u['password_hash'],u['password_salt'],u['role'],bool(u['is_active']),u['email'] if 'email' in keys else None,bool(u['email_verified']) if 'email_verified' in keys else False,u['created_at'],u['last_login_at'],now))
                if a:q.execute('''INSERT INTO pp_accounts(username,cash,starting_cash,realized_pl,updated_at) VALUES(%s,%s,%s,%s,%s)
                  ON CONFLICT(username) DO UPDATE SET cash=excluded.cash,starting_cash=excluded.starting_cash,realized_pl=excluded.realized_pl,updated_at=excluded.updated_at''',(u['username'],a['cash'],a['starting_cash'],a['realized_pl'],now))
                if w:q.execute('''INSERT INTO pp_ppc_wallets(username,balance,lifetime_earned,lifetime_burned,highest_rewarded_level,updated_at) VALUES(%s,%s,%s,%s,%s,%s)
                  ON CONFLICT(username) DO UPDATE SET balance=excluded.balance,lifetime_earned=excluded.lifetime_earned,lifetime_burned=excluded.lifetime_burned,highest_rewarded_level=excluded.highest_rewarded_level,updated_at=excluded.updated_at''',(u['username'],w['balance'],w['lifetime_earned'],w['lifetime_burned'],w['highest_rewarded_level'],now))
                if sup and res and m:q.execute('''INSERT INTO pp_ppc_state(id,hard_cap,minted,burned,exchange_reserve,price,updated_at) VALUES(1,%s,%s,%s,%s,%s,%s)
                  ON CONFLICT(id) DO UPDATE SET hard_cap=excluded.hard_cap,minted=excluded.minted,burned=excluded.burned,exchange_reserve=excluded.exchange_reserve,price=excluded.price,updated_at=excluded.updated_at''',(sup['max_supply'],sup['minted'],sup['burned'],res['balance'],m['price'],now))
        c.close();return True

    def restore_from_pg(username):
        if not ensure_pg():return None
        c=connect()
        with c.cursor() as q:
            q.execute('SELECT username,password_hash,password_salt,role,is_active,email,email_verified,created_at,last_login_at FROM pp_users WHERE lower(username)=lower(%s)',(username,));u=q.fetchone()
            if not u:c.close();return None
            q.execute('SELECT cash,starting_cash,realized_pl FROM pp_accounts WHERE username=%s',(u[0],));a=q.fetchone()
            q.execute('SELECT balance,lifetime_earned,lifetime_burned,highest_rewarded_level FROM pp_ppc_wallets WHERE username=%s',(u[0],));w=q.fetchone()
        c.close();s=base.db()
        try:
            s.execute('BEGIN IMMEDIATE');existing=s.execute('SELECT id FROM users WHERE username=?',(u[0],)).fetchone()
            if existing:uid=existing['id']
            else:
                cur=s.execute('INSERT INTO users(username,password_hash,password_salt,role,is_active,created_at,last_login_at,email,email_verified) VALUES(?,?,?,?,?,?,?,?,?)',(u[0],u[1],u[2],u[3],1 if u[4] else 0,str(u[7]),str(u[8]) if u[8] else None,u[5],1 if u[6] else 0));uid=cur.lastrowid
            if a:s.execute('INSERT OR REPLACE INTO user_accounts(user_id,cash,starting_cash,realized_pl,created_at) VALUES(?,?,?,?,?)',(uid,a[0],a[1],a[2],base.now_iso()))
            if w:s.execute('INSERT OR REPLACE INTO user_purple_currency(user_id,balance,lifetime_earned,lifetime_burned,highest_rewarded_level,starter_grant_claimed) VALUES(?,?,?,?,?,1)',(uid,w[0],w[1],w[2],w[3]))
            s.commit()
        except Exception:s.rollback();raise
        finally:s.close()
        return uid

    def audit():
        s=base.db();sup=s.execute('SELECT * FROM purple_currency_supply WHERE id=1').fetchone();res=s.execute('SELECT balance FROM purple_coin_exchange_reserve WHERE id=1').fetchone();wallets=s.execute('SELECT COALESCE(SUM(balance),0) n FROM user_purple_currency').fetchone();s.close()
        if not sup:return {'ok':True,'reason':'PPC not initialized'}
        minted=int(sup['minted']);burned=int(sup['burned']);reserve=int(res['balance']) if res else 0;held=int(wallets['n'] or 0);expected=minted-burned;actual=held+reserve;delta=actual-expected;ok=(delta==0 and minted<=int(sup['max_supply']) and burned<=minted and held>=0 and reserve>=0)
        return {'ok':ok,'hard_cap':int(sup['max_supply']),'minted':minted,'burned':burned,'expected_circulating':expected,'wallet_balances':held,'exchange_reserve':reserve,'accounted_supply':actual,'delta':delta,'freeze_recommended':not ok}

    # Restore durable account automatically before rejecting a login.
    login_paths=[r for r in app.router.routes if getattr(r,'path',None)=='/api/auth/login']
    original_login=login_paths[-1].endpoint if login_paths else None
    if original_login:
        app.router.routes[:]=[r for r in app.router.routes if getattr(r,'path',None)!='/api/auth/login']
        @app.post('/api/auth/login')
        def persistent_login(req:base.LoginRequest,response:Response):
            s=base.db();row=s.execute('SELECT 1 FROM users WHERE username=?',(req.username.strip(),)).fetchone();s.close()
            if not row:restore_from_pg(req.username.strip())
            result=original_login(req,response)
            try:
                s=base.db();u=s.execute('SELECT id FROM users WHERE username=?',(req.username.strip(),)).fetchone();s.close()
                if u:mirror_user(int(u['id']))
            except Exception:pass
            return result

    @app.post('/api/persistence/sync')
    def sync_me(request:Request):
        uid=base.current_user_id(request);return {'ok':mirror_user(uid),'postgres_configured':bool(URL and pg),'audit':audit()}

    @app.get('/api/persistence/status')
    def persistence_status(request:Request):
        uid=base.current_user_id(request)
        try:mirrored=mirror_user(uid)
        except Exception:mirrored=False
        return {'version':'V9.6','postgres_configured':bool(URL and pg),'mirrored':mirrored,'ppc_conservation':audit(),'mode':'durable identity/economy mirror with SQLite execution compatibility'}

    @app.get('/api/admin/economy-control')
    def economy_control(request:Request):
        base.require_role(request,'owner');s=base.db();a=audit();wallets=[dict(x) for x in s.execute('''SELECT u.username,w.balance,w.lifetime_earned,w.lifetime_burned,w.highest_rewarded_level FROM user_purple_currency w JOIN users u ON u.id=w.user_id ORDER BY w.balance DESC LIMIT 100''').fetchall()];flags=[dict(x) for x in s.execute('''SELECT u.username,f.kind,f.detail,f.created_at FROM purple_coin_flags f LEFT JOIN users u ON u.id=f.user_id ORDER BY f.id DESC LIMIT 100''').fetchall()];ledger=[dict(x) for x in s.execute('''SELECT u.username,l.delta,l.reason,l.level,l.trade_count,l.created_at FROM purple_currency_ledger l LEFT JOIN users u ON u.id=l.user_id ORDER BY l.id DESC LIMIT 100''').fetchall()];s.close();return {'audit':a,'wallets':wallets,'flags':flags,'ledger':ledger,'postgres_configured':bool(URL and pg)}

    base.v96_mirror_user=mirror_user;base.v96_restore=restore_from_pg;base.v96_audit=audit
