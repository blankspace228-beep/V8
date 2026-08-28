import hashlib, hmac, os, secrets
from datetime import datetime, timezone, timedelta
import httpx
from fastapi import HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import app as base

app=base.app
RESEND_API_KEY=os.getenv('RESEND_API_KEY','').strip()
EMAIL_FROM=os.getenv('EMAIL_FROM','Purple Paper <onboarding@resend.dev>').strip()
EMAIL_VERIFICATION_REQUIRED=os.getenv('EMAIL_VERIFICATION_REQUIRED','1').lower() in {'1','true','yes','on'}

_orig_init=base.init_db
def init_db_v82():
    _orig_init()
    conn=base.db()
    base.add_column(conn,'users','email','TEXT')
    base.add_column(conn,'users','email_verified','INTEGER NOT NULL DEFAULT 0')
    base.add_column(conn,'users','verification_code_hash','TEXT')
    base.add_column(conn,'users','verification_expires_at','TEXT')
    conn.execute('''CREATE TABLE IF NOT EXISTS admin_balance_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT, actor_user_id INTEGER NOT NULL,
      target_user_id INTEGER NOT NULL, old_cash REAL NOT NULL, new_cash REAL NOT NULL,
      reason TEXT, created_at TEXT NOT NULL)''')
    rows=conn.execute("SELECT u.id FROM users u JOIN user_accounts a ON a.user_id=u.id WHERE u.role!='owner' AND (a.cash!=0 OR a.starting_cash!=0)").fetchall()
    for r in rows:
        uid=r['id']
        trades=conn.execute('SELECT COUNT(*) c FROM user_trades WHERE user_id=?',(uid,)).fetchone()['c']
        positions=conn.execute('SELECT COUNT(*) c FROM user_positions WHERE user_id=?',(uid,)).fetchone()['c']
        if trades==0 and positions==0:
            conn.execute('UPDATE user_accounts SET cash=0,starting_cash=0,realized_pl=0 WHERE user_id=?',(uid,))
    conn.commit();conn.close()
base.init_db=init_db_v82

def ensure_user_account_v82(user_id:int):
    conn=base.db(); row=conn.execute('SELECT * FROM user_accounts WHERE user_id=?',(user_id,)).fetchone()
    if row is None:
        u=conn.execute('SELECT role FROM users WHERE id=?',(user_id,)).fetchone()
        initial=base.STARTING_CASH if u and u['role']=='owner' else 0.0
        conn.execute('INSERT INTO user_accounts(user_id,cash,starting_cash,realized_pl,created_at) VALUES(?,?,?,?,?)',(user_id,initial,initial,0.0,base.now_iso()));conn.commit()
    conn.close()
base.ensure_user_account=ensure_user_account_v82

def public_user_v82(row):
    keys=set(row.keys())
    email=row['email'] if 'email' in keys else None
    verified=bool(row['email_verified']) if 'email_verified' in keys else False
    return {'id':row['id'],'username':row['username'],'role':row['role'],'role_label':base.ROLE_LABELS.get(row['role'],row['role'].upper()),'is_active':bool(row['is_active']),'created_at':row['created_at'],'last_login_at':row['last_login_at'],'email':email,'email_verified':verified or row['role']=='owner'}
base.public_user=public_user_v82

def vhash(code): return hashlib.sha256(code.encode()).hexdigest()
async def send_verify(email,code):
    if not RESEND_API_KEY: raise HTTPException(503,'Email verification is not configured yet. The Owner needs to connect the Purple Paper email service.')
    payload={'from':EMAIL_FROM,'to':[email],'subject':'Verify your Purple Paper account','html':f"<div style='font-family:Arial;background:#0d0912;color:#fff;padding:28px'><h2 style='color:#a978ff'>Purple Paper verification</h2><p>Your verification code:</p><div style='font-size:30px;font-weight:800;letter-spacing:8px'>{code}</div><p>This code expires in 15 minutes.</p></div>"}
    async with httpx.AsyncClient(timeout=12) as c:r=await c.post('https://api.resend.com/emails',headers={'Authorization':f'Bearer {RESEND_API_KEY}','Content-Type':'application/json'},json=payload)
    if r.status_code>=400: raise HTTPException(502,'Verification email could not be sent. Please try again shortly.')

class SignupV82(BaseModel):
    username:str=Field(min_length=3,max_length=32); password:str=Field(min_length=8,max_length=128); email:str|None=Field(default=None,max_length=254); setup_code:str|None=Field(default=None,max_length=256)
class VerifyV82(BaseModel): username:str=Field(min_length=3,max_length=32); code:str=Field(min_length=6,max_length=6)
class BalanceV82(BaseModel): cash:float=Field(ge=0,le=1_000_000_000_000); reason:str|None=Field(default=None,max_length=240)

replace_paths={'/','/api/auth/signup','/api/auth/login','/api/admin/users'}
app.router.routes[:]=[r for r in app.router.routes if getattr(r,'path',None) not in replace_paths]

@app.get('/')
async def home_v82():
    html=(base.ROOT/'static'/'index.html').read_text(encoding='utf-8')
    html=html.replace('</head>',"<link rel='stylesheet' href='/static/v82.css?v=1'></head>")
    html=html.replace('</body>',"<script src='/static/v82.js?v=1'></script></body>")
    return HTMLResponse(html,headers={'Cache-Control':'no-store, max-age=0'})

@app.post('/api/auth/signup')
async def signup_v82(req:SignupV82,response:Response):
    username=req.username.strip(); conn=base.db()
    if not username.replace('_','').replace('-','').isalnum(): conn.close(); raise HTTPException(400,'Username may use letters, numbers, underscores, and hyphens')
    if conn.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone(): conn.close(); raise HTTPException(409,'Username already exists')
    count=conn.execute('SELECT COUNT(*) c FROM users').fetchone()['c']; role='owner' if count==0 else 'player'
    if count==0 and base.HOSTED_MODE:
        if not base.OWNER_SETUP_CODE: conn.close(); raise HTTPException(503,'Hosted Owner setup is locked until OWNER_SETUP_CODE is configured')
        if not hmac.compare_digest((req.setup_code or '').strip(),base.OWNER_SETUP_CODE): conn.close(); raise HTTPException(403,'Owner setup code is required')
    email=(req.email or '').strip().lower()
    if role!='owner' and EMAIL_VERIFICATION_REQUIRED:
        if '@' not in email or email.startswith('@') or email.endswith('@'): conn.close(); raise HTTPException(400,'A valid email is required for player accounts')
        if not RESEND_API_KEY: conn.close(); raise HTTPException(503,'Email verification is being configured by the Owner. Try again shortly.')
        if conn.execute('SELECT 1 FROM users WHERE email=? COLLATE NOCASE',(email,)).fetchone(): conn.close(); raise HTTPException(409,'That email is already registered')
    salt,ph=base._new_password(req.password); code=f'{secrets.randbelow(1000000):06d}' if role!='owner' and EMAIL_VERIFICATION_REQUIRED else None
    exp=(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat() if code else None
    cur=conn.execute('INSERT INTO users(username,password_hash,password_salt,role,is_active,created_at,email,email_verified,verification_code_hash,verification_expires_at) VALUES(?,?,?,?,1,?,?,?,?,?)',(username,ph,salt,role,base.now_iso(),email or None,1 if role=='owner' else 0,vhash(code) if code else None,exp));uid=cur.lastrowid;conn.commit();row=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();conn.close();base.ensure_user_account(uid)
    if role=='owner': base.create_session(response,uid); return {'ok':True,'user':base.public_user(row),'owner_created':True,'verification_required':False}
    try: await send_verify(email,code)
    except HTTPException:
        conn=base.db();conn.execute('DELETE FROM user_accounts WHERE user_id=?',(uid,));conn.execute('DELETE FROM users WHERE id=?',(uid,));conn.commit();conn.close();raise
    return {'ok':True,'verification_required':True,'username':username,'email':email}

@app.post('/api/auth/verify-email')
def verify_email_v82(req:VerifyV82,response:Response):
    conn=base.db();row=conn.execute('SELECT * FROM users WHERE username=?',(req.username.strip(),)).fetchone()
    if not row: conn.close(); raise HTTPException(404,'Account not found')
    if row['role']=='owner' or row['email_verified']: conn.close();base.create_session(response,row['id']);return {'ok':True,'user':base.public_user(row)}
    if not row['verification_code_hash'] or not row['verification_expires_at']: conn.close();raise HTTPException(400,'No active verification code')
    if datetime.fromisoformat(row['verification_expires_at'])<datetime.now(timezone.utc): conn.close();raise HTTPException(400,'Verification code expired. Create the account again.')
    if not hmac.compare_digest(row['verification_code_hash'],vhash(req.code)): conn.close();raise HTTPException(400,'Incorrect verification code')
    conn.execute('UPDATE users SET email_verified=1,verification_code_hash=NULL,verification_expires_at=NULL,last_login_at=? WHERE id=?',(base.now_iso(),row['id']));conn.commit();row=conn.execute('SELECT * FROM users WHERE id=?',(row['id'],)).fetchone();conn.close();base.create_session(response,row['id']);return {'ok':True,'user':base.public_user(row)}

@app.post('/api/auth/login')
def login_v82(req:base.LoginRequest,response:Response):
    conn=base.db();row=conn.execute('SELECT * FROM users WHERE username=?',(req.username.strip(),)).fetchone()
    if not row or not hmac.compare_digest(row['password_hash'],base._password_hash(req.password,row['password_salt'])): conn.close();raise HTTPException(401,'Invalid username or password')
    if not row['is_active']: conn.close();raise HTTPException(403,'This account is disabled')
    if row['role']!='owner' and row['email'] and not row['email_verified']: conn.close();raise HTTPException(403,'Email verification required before login')
    conn.execute('UPDATE users SET last_login_at=? WHERE id=?',(base.now_iso(),row['id']));conn.commit();row=conn.execute('SELECT * FROM users WHERE id=?',(row['id'],)).fetchone();conn.close();base.create_session(response,row['id']);return {'ok':True,'user':base.public_user(row)}

@app.get('/api/admin/users')
def admin_users_v82(request:Request):
    base.require_role(request,'moderator');conn=base.db();rows=conn.execute('SELECT * FROM users ORDER BY id').fetchall();conn.close();out=[]
    for r in rows:
        u=base.public_user(r);snap=base.account_snapshot(r['id']);conn=base.db();t=conn.execute('SELECT COUNT(*) c,COALESCE(SUM(ABS(total)),0) v FROM user_trades WHERE user_id=?',(r['id'],)).fetchone();p=conn.execute('SELECT COUNT(*) c FROM user_positions WHERE user_id=?',(r['id'],)).fetchone();conn.close();u.update(cash=snap['cash'],equity=snap['equity'],market_value=snap['market_value'],realized_pl=snap['realized_pl'],trade_count=t['c'],trade_volume=t['v'],position_count=p['c']);out.append(u)
    return {'users':out,'roles':['player','coach','moderator','admin','owner']}

@app.post('/api/admin/users/{user_id}/balance')
def admin_balance_v82(user_id:int,req:BalanceV82,request:Request):
    actor=base.require_role(request,'owner');base.ensure_user_account(user_id);conn=base.db();target=conn.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
    if not target: conn.close();raise HTTPException(404,'User not found')
    acct=conn.execute('SELECT * FROM user_accounts WHERE user_id=?',(user_id,)).fetchone();old=float(acct['cash']);new=float(req.cash);conn.execute('UPDATE user_accounts SET cash=? WHERE user_id=?',(new,user_id))
    if float(acct['starting_cash'])==0 and conn.execute('SELECT COUNT(*) c FROM user_trades WHERE user_id=?',(user_id,)).fetchone()['c']==0: conn.execute('UPDATE user_accounts SET starting_cash=? WHERE user_id=?',(new,user_id))
    conn.execute('INSERT INTO admin_balance_audit(actor_user_id,target_user_id,old_cash,new_cash,reason,created_at) VALUES(?,?,?,?,?,?)',(actor['id'],user_id,old,new,(req.reason or 'Owner correction').strip(),base.now_iso()));conn.commit();conn.close();return {'ok':True,'account':base.account_snapshot(user_id)}
