import hashlib,hmac,os,secrets,importlib.util
from datetime import datetime,timezone,timedelta
from pathlib import Path
import httpx
from fastapi import HTTPException,Request,Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,Field

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('purple_legacy_app',ROOT/'app.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
app=base.app
RESEND_API_KEY=os.getenv('RESEND_API_KEY','').strip()
EMAIL_FROM=os.getenv('EMAIL_FROM','Purple Paper <onboarding@resend.dev>').strip()
EMAIL_VERIFICATION_REQUIRED=os.getenv('EMAIL_VERIFICATION_REQUIRED','1').lower() in {'1','true','yes','on'}

_orig_init=base.init_db
def init_db_v82():
    _orig_init();conn=base.db()
    base.add_column(conn,'users','email','TEXT');base.add_column(conn,'users','email_verified','INTEGER NOT NULL DEFAULT 0');base.add_column(conn,'users','verification_code_hash','TEXT');base.add_column(conn,'users','verification_expires_at','TEXT')
    conn.execute('''CREATE TABLE IF NOT EXISTS admin_balance_audit (id INTEGER PRIMARY KEY AUTOINCREMENT,actor_user_id INTEGER NOT NULL,target_user_id INTEGER NOT NULL,old_cash REAL NOT NULL,new_cash REAL NOT NULL,reason TEXT,created_at TEXT NOT NULL)''');conn.commit();conn.close()
base.init_db=init_db_v82

def ensure_user_account_v82(user_id:int):
    conn=base.db();row=conn.execute('SELECT * FROM user_accounts WHERE user_id=?',(user_id,)).fetchone()
    if row is None:
        u=conn.execute('SELECT role FROM users WHERE id=?',(user_id,)).fetchone();initial=base.STARTING_CASH if u and u['role']=='owner' else 0.0
        conn.execute('INSERT INTO user_accounts(user_id,cash,starting_cash,realized_pl,created_at) VALUES(?,?,?,?,?)',(user_id,initial,initial,0.0,base.now_iso()));conn.commit()
    conn.close()
base.ensure_user_account=ensure_user_account_v82

def public_user_v82(row):
    keys=set(row.keys());email=row['email'] if 'email' in keys else None;verified=bool(row['email_verified']) if 'email_verified' in keys else False
    return {'id':row['id'],'username':row['username'],'role':row['role'],'role_label':base.ROLE_LABELS.get(row['role'],row['role'].upper()),'is_active':bool(row['is_active']),'created_at':row['created_at'],'last_login_at':row['last_login_at'],'email':email,'email_verified':verified or row['role']=='owner'}
base.public_user=public_user_v82

def vhash(code):return hashlib.sha256(code.encode()).hexdigest()
async def send_verify(email,code):
    if not RESEND_API_KEY:raise HTTPException(503,'Email verification is not configured yet.')
    payload={'from':EMAIL_FROM,'to':[email],'subject':'Verify your Purple Paper account','html':f'<h2>Purple Paper verification</h2><p>Your verification code:</p><h1>{code}</h1>'}
    async with httpx.AsyncClient(timeout=12) as c:r=await c.post('https://api.resend.com/emails',headers={'Authorization':f'Bearer {RESEND_API_KEY}','Content-Type':'application/json'},json=payload)
    if r.status_code>=400:raise HTTPException(502,'Verification email could not be sent.')

class SignupV82(BaseModel):
    username:str=Field(min_length=3,max_length=32);password:str=Field(min_length=8,max_length=128);email:str|None=Field(default=None,max_length=254);setup_code:str|None=Field(default=None,max_length=256)
class VerifyV82(BaseModel):username:str=Field(min_length=3,max_length=32);code:str=Field(min_length=6,max_length=6)
class BalanceV82(BaseModel):cash:float=Field(ge=0,le=1_000_000_000_000);reason:str|None=Field(default=None,max_length=240)
replace_paths={'/','/api/auth/signup','/api/auth/login','/api/admin/users'}
app.router.routes[:]=[r for r in app.router.routes if getattr(r,'path',None) not in replace_paths]

@app.get('/')
async def home_v82():
    html=(base.ROOT/'static'/'index.html').read_text(encoding='utf-8')
    html=html.replace('</head>',"<link rel='stylesheet' href='/static/v82.css?v=2'><link rel='stylesheet' href='/static/v83.css?v=3'><link rel='stylesheet' href='/static/v84_ai.css?v=1'><link rel='stylesheet' href='/static/v85_brain.css?v=1'><link rel='stylesheet' href='/static/v86_hypothesis.css?v=1'><link rel='stylesheet' href='/static/v87_attention.css?v=1'><link rel='stylesheet' href='/static/v88_global_attention.css?v=1'><link rel='stylesheet' href='/static/v89_router.css?v=1'><link rel='stylesheet' href='/static/v90_imagination.css?v=1'><link rel='stylesheet' href='/static/v91_trading_floor.css?v=2'><link rel='stylesheet' href='/static/v93_currency.css?v=1'><link rel='stylesheet' href='/static/v94_coin.css?v=1'></head>")
    scripts="<script src='/static/v82.js?v=2'></script><script src='/static/v83.js?v=3'></script><script src='/static/v84_ai.js?v=1'></script><script src='/static/v85_brain.js?v=1'></script><script src='/static/v86_hypothesis.js?v=1'></script><script src='/static/v87_attention.js?v=1'></script><script src='/static/v88_global_attention.js?v=1'></script><script src='/static/v89_router.js?v=1'></script><script src='/static/v90_imagination.js?v=1'></script><script src='/static/v91_trading_floor.js?v=2'></script><script src='/static/v93_currency.js?v=1'></script><script src='/static/v94_coin.js?v=1'></script><script src='/static/v95_account_vault.js?v=2'></script><script src='/static/v100_mining.js?v=2'></script><script src='/static/v101_world.js?v=1'></script><script src='/static/v102_market_intelligence.js?v=1'></script>"
    html=html.replace('</body>',scripts+'</body>');return HTMLResponse(html,headers={'Cache-Control':'no-store, max-age=0'})

@app.post('/api/auth/signup')
async def signup_v82(req:SignupV82,response:Response):
    username=req.username.strip();conn=base.db()
    if conn.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone():conn.close();raise HTTPException(409,'Username already exists')
    count=conn.execute('SELECT COUNT(*) c FROM users').fetchone()['c'];role='owner' if count==0 else 'player';email=(req.email or '').strip().lower()
    salt,ph=base._new_password(req.password);cur=conn.execute('INSERT INTO users(username,password_hash,password_salt,role,is_active,created_at,email,email_verified) VALUES(?,?,?,?,1,?,?,?)',(username,ph,salt,role,base.now_iso(),email or None,1));uid=cur.lastrowid;conn.commit();row=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();conn.close();base.ensure_user_account(uid);base.create_session(response,uid);return {'ok':True,'user':base.public_user(row)}

@app.post('/api/auth/login')
def login_v82(req:base.LoginRequest,response:Response):
    conn=base.db();row=conn.execute('SELECT * FROM users WHERE username=?',(req.username.strip(),)).fetchone()
    if not row or not hmac.compare_digest(row['password_hash'],base._password_hash(req.password,row['password_salt'])):conn.close();raise HTTPException(401,'Invalid username or password')
    conn.close();base.create_session(response,row['id']);return {'ok':True,'user':base.public_user(row)}

from .purple_ai import register as register_purple_ai
from .v86_hypothesis import register as register_v86_hypothesis
from .v87_attention import register as register_v87_attention
from .v88_global_attention import register as register_v88_global_attention
from .v89_hierarchical import register as register_v89_hierarchical
from .v90_imagination import register as register_v90_imagination
from .v91_trading_floor import register as register_v91_trading_floor
from .v93_earned_currency import register as register_v93_currency
from .v94_market_coin import register as register_v94_coin
from .v95_economy_security import register as register_v95_security
from .v96_persistent_core import register as register_v96_persistent
from .v100_mining import register as register_v100_mining
from .v101_world import register as register_v101_world
from .v102_market_intelligence import register as register_v102_intel
for fn in [register_purple_ai,register_v86_hypothesis,register_v87_attention,register_v88_global_attention,register_v89_hierarchical,register_v90_imagination,register_v91_trading_floor,register_v93_currency,register_v94_coin,register_v95_security,register_v96_persistent,register_v100_mining,register_v101_world,register_v102_intel]:fn(app,base)
