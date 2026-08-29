import io, os, secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import request, redirect, session, flash, abort, url_for, send_file, render_template_string
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode
import app as base

app=base.app
page=base.page
db=base.db

ROLES=('user','worker','supervisor','customer','owner')

def now(): return datetime.now().isoformat(timespec='seconds')

def init_upgrade():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at TEXT NOT NULL,
      username TEXT NOT NULL UNIQUE COLLATE NOCASE,
      email TEXT UNIQUE COLLATE NOCASE,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT 'user',
      employee_id INTEGER,
      customer_id INTEGER,
      active INTEGER NOT NULL DEFAULT 1,
      last_login TEXT
    );
    CREATE TABLE IF NOT EXISTS checkpoints(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      property_id INTEGER NOT NULL,
      label TEXT NOT NULL,
      code TEXT NOT NULL UNIQUE,
      latitude TEXT,
      longitude TEXT,
      active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS patrol_v2(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id INTEGER NOT NULL,
      user_id INTEGER,
      created_at TEXT NOT NULL,
      checkpoint_id INTEGER,
      checkpoint_code TEXT,
      condition TEXT NOT NULL DEFAULT 'Clear',
      notes TEXT,
      latitude TEXT,
      longitude TEXT
    );
    CREATE TABLE IF NOT EXISTS worker_locations(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      job_id INTEGER,
      created_at TEXT NOT NULL,
      latitude TEXT NOT NULL,
      longitude TEXT NOT NULL,
      accuracy TEXT
    );
    CREATE TABLE IF NOT EXISTS photo_evidence(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id INTEGER NOT NULL,
      user_id INTEGER,
      created_at TEXT NOT NULL,
      caption TEXT,
      filename TEXT,
      mimetype TEXT,
      data BLOB NOT NULL
    );
    CREATE TABLE IF NOT EXISTS extinguisher_assets(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at TEXT NOT NULL,
      customer_id INTEGER NOT NULL,
      property_id INTEGER NOT NULL,
      asset_code TEXT NOT NULL UNIQUE,
      location_text TEXT NOT NULL,
      extinguisher_type TEXT,
      size_text TEXT,
      manufacturer TEXT,
      serial_number TEXT,
      manufacture_year TEXT,
      last_inspection TEXT,
      next_due TEXT,
      status TEXT NOT NULL DEFAULT 'In Service',
      notes TEXT
    );
    '''); c.commit(); c.close()
init_upgrade()


def current_user():
    uid=session.get('user_id')
    if not uid: return None
    c=db(); u=c.execute('SELECT * FROM users WHERE id=? AND active=1',(uid,)).fetchone(); c.close(); return u

def login_required(fn):
    @wraps(fn)
    def w(*a,**k):
        if not current_user(): return redirect('/account/login?next='+request.path)
        return fn(*a,**k)
    return w

def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        def w(*a,**k):
            u=current_user()
            if not u: return redirect('/account/login?next='+request.path)
            if u['role'] not in roles: abort(403)
            return fn(*a,**k)
        return w
    return deco

ACCOUNT_NAV='''<div style="display:flex;gap:8px;flex-wrap:wrap;margin:0 0 24px">
<a class="btn darkbtn" href="/account">My Account</a>
{% if user and user.role in ['worker','supervisor','owner'] %}<a class="btn darkbtn" href="/worker">Worker Portal</a>{% endif %}
{% if user and user.role=='owner' %}<a class="btn darkbtn" href="/owner/users">Users</a><a class="btn darkbtn" href="/owner/dispatch-map">Dispatch Map</a><a class="btn darkbtn" href="/owner/assets">Extinguishers</a><a class="btn darkbtn" href="/admin/fire-watch">Fire Watch Command</a>{% endif %}
{% if user and user.role=='customer' %}<a class="btn darkbtn" href="/customer/portal">Customer Portal</a>{% endif %}
<a class="btn darkbtn" href="/account/logout">Log Out</a></div>'''

def acct_page(inner, title, **ctx):
    ctx['user']=current_user()
    return page(ACCOUNT_NAV+inner,title=title,**ctx)

@app.after_request
def inject_account_nav(resp):
    try:
        if resp.content_type and resp.content_type.startswith('text/html'):
            s=resp.get_data(as_text=True)
            if '</nav>' in s and '/account/login' not in s:
                u=current_user()
                link='<a href="/account">Account</a>' if u else '<a href="/account/login">Login</a>'
                s=s.replace('</nav>',link+'</nav>',1); resp.set_data(s)
    except Exception: pass
    return resp

@app.route('/account/register',methods=['GET','POST'])
def account_register():
    if request.method=='POST':
        username=request.form.get('username','').strip(); email=request.form.get('email','').strip() or None; pw=request.form.get('password','')
        if len(username)<3 or len(pw)<8:
            flash('Username must be at least 3 characters and password at least 8.'); return redirect(request.path)
        c=db()
        try:
            c.execute('INSERT INTO users(created_at,username,email,password_hash,role) VALUES(?,?,?,?,?)',(now(),username,email,generate_password_hash(pw),'user')); c.commit()
        except Exception:
            c.close(); flash('That username or email is already in use.'); return redirect(request.path)
        uid=c.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()[0]; c.close(); session['user_id']=uid; flash('Account created.'); return redirect('/account')
    return page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Account</span><h1>Create an account</h1></div></section><section class="section"><div class="wrap login-box" style="max-width:620px"><form method="post"><label>Username<input name="username" autocomplete="username" required></label><label>Email<input type="email" name="email" autocomplete="email"></label><label>Password<input type="password" name="password" minlength="8" autocomplete="new-password" required></label><button class="btn primary" style="margin-top:16px">Create Account</button></form><p><a href="/account/login">Already have an account? Log in</a></p></div></section>''',title='Create Account')

@app.route('/account/login',methods=['GET','POST'])
def account_login():
    if request.method=='POST':
        ident=request.form.get('identity','').strip(); pw=request.form.get('password','')
        c=db(); u=c.execute('SELECT * FROM users WHERE active=1 AND (username=? COLLATE NOCASE OR email=? COLLATE NOCASE)',(ident,ident)).fetchone()
        if not u or not check_password_hash(u['password_hash'],pw): c.close(); flash('Invalid login.'); return redirect(request.path)
        c.execute('UPDATE users SET last_login=? WHERE id=?',(now(),u['id'])); c.commit(); c.close(); session['user_id']=u['id']
        nxt=request.args.get('next') or '/account'; return redirect(nxt if nxt.startswith('/') else '/account')
    return page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Secure Portal</span><h1>Sign in</h1></div></section><section class="section"><div class="wrap login-box" style="max-width:620px"><form method="post"><label>Username or email<input name="identity" autocomplete="username" required></label><label>Password<input type="password" name="password" autocomplete="current-password" required></label><button class="btn primary" style="margin-top:16px">Log In</button></form><p><a href="/account/register">Create a user account</a></p><p class="note"><a href="/owner/setup">First owner setup</a></p></div></section>''',title='Login')

@app.route('/account/logout')
def account_logout():
    session.pop('user_id',None); return redirect('/')

@app.route('/owner/setup',methods=['GET','POST'])
def owner_setup():
    c=db(); exists=c.execute("SELECT 1 FROM users WHERE role='owner' LIMIT 1").fetchone(); c.close()
    if exists: return redirect('/account/login')
    if request.method=='POST':
        code=request.form.get('setup_code',''); expected=os.environ.get('OWNER_SETUP_CODE','')
        if not expected or not secrets.compare_digest(code,expected): flash('Owner setup code is incorrect.'); return redirect(request.path)
        username=request.form.get('username','').strip(); email=request.form.get('email','').strip() or None; pw=request.form.get('password','')
        if len(username)<3 or len(pw)<10: flash('Use a username of 3+ characters and a password of 10+ characters.'); return redirect(request.path)
        c=db()
        try:
            c.execute('INSERT INTO users(created_at,username,email,password_hash,role) VALUES(?,?,?,?,?)',(now(),username,email,generate_password_hash(pw),'owner')); c.commit(); uid=c.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()[0]
        except Exception: c.close(); flash('Username or email already in use.'); return redirect(request.path)
        c.close(); session['user_id']=uid; session['admin']=True; return redirect('/account')
    return page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Owner Setup</span><h1>Create the protected owner account</h1></div></section><section class="section"><div class="wrap login-box" style="max-width:650px"><p>This page only works until the first owner is created.</p><form method="post"><label>Owner setup code<input type="password" name="setup_code" required></label><label>Owner username<input name="username" required></label><label>Email<input type="email" name="email"></label><label>Password<input type="password" name="password" minlength="10" required></label><button class="btn primary" style="margin-top:16px">Create Owner</button></form></div></section>''',title='Owner Setup')

@app.route('/account')
@login_required
def account_home():
    u=current_user(); dest={'owner':'/owner/users','worker':'/worker','supervisor':'/worker','customer':'/customer/portal'}.get(u['role'])
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Account</span><h1>Welcome, {{user.username}}</h1><p class="lead">Role: {{user.role|title}}</p></div></section><section class="section"><div class="wrap"><div class="card"><h2>{{user.role|title}} account</h2><p>{{user.email or 'No email on file'}}</p>{% if dest %}<a class="btn primary" href="{{dest}}">Open {{user.role|title}} Portal</a>{% else %}<p>Your account is active. An owner can upgrade your role when needed.</p>{% endif %}</div></div></section>''','My Account',dest=dest)

@app.route('/owner/users',methods=['GET','POST'])
@role_required('owner')
def owner_users():
    c=db()
    if request.method=='POST':
        uid=int(request.form.get('user_id')); role=request.form.get('role','user'); customer_id=request.form.get('customer_id') or None
        if role not in ROLES: abort(400)
        target=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        if not target: c.close(); abort(404)
        employee_id=target['employee_id']
        if role in ('worker','supervisor') and not employee_id:
            name=target['username']; c.execute('INSERT INTO employees(created_at,full_name,email,role,active,notes) VALUES(?,?,?,?,1,?)',(now(),name,target['email'] or '',('Supervisor' if role=='supervisor' else 'Fire Watch'),'Created from user account')); employee_id=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute('UPDATE users SET role=?,employee_id=?,customer_id=? WHERE id=?',(role,employee_id,customer_id if role=='customer' else None,uid)); c.commit(); c.close(); flash('User role updated.'); return redirect(request.path)
    users=c.execute('SELECT * FROM users ORDER BY id').fetchall(); customers=c.execute('SELECT id,business_name FROM customers ORDER BY business_name').fetchall(); c.close()
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Owner Control</span><h1>Users & permissions</h1><p class="lead">Upgrade normal accounts to workers, supervisors, customers, or owners.</p></div></section><section class="section"><div class="wrap"><div class="table-card table-wrap"><table><tr><th>User</th><th>Email</th><th>Current role</th><th>Change access</th></tr>{% for x in users %}<tr><td><b>{{x.username}}</b><br><span class="note">#{{x.id}}</span></td><td>{{x.email or '—'}}</td><td>{{x.role|title}}</td><td><form method="post" style="display:flex;gap:8px;flex-wrap:wrap"><input type="hidden" name="user_id" value="{{x.id}}"><select name="role"><option value="user" {% if x.role=='user' %}selected{% endif %}>User</option><option value="worker" {% if x.role=='worker' %}selected{% endif %}>Worker</option><option value="supervisor" {% if x.role=='supervisor' %}selected{% endif %}>Supervisor</option><option value="customer" {% if x.role=='customer' %}selected{% endif %}>Customer</option><option value="owner" {% if x.role=='owner' %}selected{% endif %}>Owner</option></select><select name="customer_id"><option value="">Customer link (only for customer role)</option>{% for c in customers %}<option value="{{c.id}}" {% if x.customer_id==c.id %}selected{% endif %}>{{c.business_name}}</option>{% endfor %}</select><button class="btn primary">Save</button></form></td></tr>{% endfor %}</table></div></div></section>''','Users & Roles',users=users,customers=customers)

def assigned_jobs_for(u):
    c=db()
    if u['role']=='owner':
        rows=c.execute('''SELECT j.*,p.name property_name,p.address,p.city,c.business_name,e.full_name employee_name,(SELECT MAX(created_at) FROM patrol_v2 r WHERE r.job_id=j.id) last_round FROM fire_watch_jobs j JOIN properties p ON p.id=j.property_id JOIN customers c ON c.id=j.customer_id LEFT JOIN employees e ON e.id=j.employee_id ORDER BY j.id DESC''').fetchall()
    else:
        rows=c.execute('''SELECT j.*,p.name property_name,p.address,p.city,c.business_name,e.full_name employee_name,(SELECT MAX(created_at) FROM patrol_v2 r WHERE r.job_id=j.id) last_round FROM fire_watch_jobs j JOIN properties p ON p.id=j.property_id JOIN customers c ON c.id=j.customer_id LEFT JOIN employees e ON e.id=j.employee_id WHERE j.employee_id=? ORDER BY j.id DESC''',(u['employee_id'] or -1,)).fetchall()
    c.close(); return rows

@app.route('/worker')
@role_required('worker','supervisor','owner')
def worker_home():
    u=current_user(); jobs=assigned_jobs_for(u); enriched=[]
    for j in jobs:
        d=dict(j); last=j['last_round'] or j['clock_in_at']; d['next_due']='—'; d['overdue']=False
        if j['status']=='On Watch' and last:
            try:
                due=datetime.fromisoformat(last)+timedelta(minutes=int(j['patrol_interval'])); d['next_due']=due.isoformat(timespec='minutes'); d['overdue']=datetime.now()>due
            except Exception: pass
        enriched.append(d)
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Field Operations</span><h1>Worker Portal</h1><p class="lead">Assigned jobs, patrol timers, GPS check-ins, checkpoint scans and photo evidence.</p></div></section><section class="section"><div class="wrap"><div class="card-grid">{% for j in jobs %}<article class="card"><span class="badge {% if j.overdue %}Planned{% else %}Available{% endif %}">{{'ROUND OVERDUE' if j.overdue else j.status}}</span><h3>#{{j.id}} {{j.property_name}}</h3><p><b>{{j.business_name}}</b><br>{{j.address}}, {{j.city}}<br>Interval: {{j.patrol_interval}} min<br>Next due: {{j.next_due}}</p><a class="btn primary" href="/worker/watch/{{j.id}}">Open Assignment</a></article>{% else %}<article class="card"><h3>No assigned jobs</h3><p>When an owner assigns a fire watch to your worker profile, it will appear here.</p></article>{% endfor %}</div></div></section>''','Worker Portal',jobs=enriched)

def job_for_user(jid,u):
    c=db(); j=c.execute('''SELECT j.*,p.name property_name,p.address,p.city,p.id property_id,c.business_name,e.full_name employee_name FROM fire_watch_jobs j JOIN properties p ON p.id=j.property_id JOIN customers c ON c.id=j.customer_id LEFT JOIN employees e ON e.id=j.employee_id WHERE j.id=?''',(jid,)).fetchone(); c.close()
    if not j: abort(404)
    if u['role'] not in ('owner','supervisor') and j['employee_id'] != u['employee_id']: abort(403)
    return j

@app.route('/worker/watch/<int:jid>',methods=['GET','POST'])
@role_required('worker','supervisor','owner')
def worker_watch(jid):
    u=current_user(); j=job_for_user(jid,u)
    c=db()
    if request.method=='POST':
        action=request.form.get('action'); lat=request.form.get('latitude','').strip(); lng=request.form.get('longitude','').strip()
        if lat and lng: c.execute('INSERT INTO worker_locations(user_id,job_id,created_at,latitude,longitude,accuracy) VALUES(?,?,?,?,?,?)',(u['id'],jid,now(),lat,lng,request.form.get('accuracy','')))
        if action=='clock_in' and not j['clock_in_at']:
            c.execute("UPDATE fire_watch_jobs SET clock_in_at=?,clock_in_lat=?,clock_in_lng=?,status='On Watch' WHERE id=?",(now(),lat,lng,jid)); flash('Clocked in.')
        elif action=='clock_out' and not j['clock_out_at']:
            c.execute("UPDATE fire_watch_jobs SET clock_out_at=?,clock_out_lat=?,clock_out_lng=?,status='Completed' WHERE id=?",(now(),lat,lng,jid)); flash('Watch completed.')
        elif action=='round':
            code=request.form.get('checkpoint_code','').strip().upper(); cp=None
            if code: cp=c.execute('SELECT * FROM checkpoints WHERE property_id=? AND code=? AND active=1',(j['property_id'],code)).fetchone()
            if code and not cp: c.close(); flash('Checkpoint code is not valid for this property.'); return redirect(request.path)
            c.execute('INSERT INTO patrol_v2(job_id,user_id,created_at,checkpoint_id,checkpoint_code,condition,notes,latitude,longitude) VALUES(?,?,?,?,?,?,?,?,?)',(jid,u['id'],now(),cp['id'] if cp else None,code or None,request.form.get('condition','Clear'),request.form.get('notes','').strip(),lat,lng));
            c.execute('INSERT INTO patrol_logs(job_id,created_at,checkpoint,condition,notes,latitude,longitude) VALUES(?,?,?,?,?,?,?)',(jid,now(),cp['label'] if cp else (code or 'General patrol'),request.form.get('condition','Clear'),request.form.get('notes','').strip(),lat,lng)); flash('Patrol round recorded.')
        elif action=='photo':
            f=request.files.get('photo')
            if not f or not f.filename: c.close(); flash('Choose a photo.'); return redirect(request.path)
            data=f.read(2*1024*1024+1)
            if len(data)>2*1024*1024: c.close(); flash('Photo must be 2 MB or smaller.'); return redirect(request.path)
            if not (f.mimetype or '').startswith('image/'): c.close(); flash('Image files only.'); return redirect(request.path)
            c.execute('INSERT INTO photo_evidence(job_id,user_id,created_at,caption,filename,mimetype,data) VALUES(?,?,?,?,?,?,?)',(jid,u['id'],now(),request.form.get('caption','').strip(),f.filename,f.mimetype,data)); flash('Photo evidence saved.')
        c.commit(); c.close(); return redirect(request.path)
    cps=c.execute('SELECT * FROM checkpoints WHERE property_id=? AND active=1 ORDER BY label',(j['property_id'],)).fetchall(); rounds=c.execute('SELECT r.*,cp.label checkpoint_label FROM patrol_v2 r LEFT JOIN checkpoints cp ON cp.id=r.checkpoint_id WHERE r.job_id=? ORDER BY r.id DESC LIMIT 20',(jid,)).fetchall(); photos=c.execute('SELECT id,created_at,caption,filename FROM photo_evidence WHERE job_id=? ORDER BY id DESC LIMIT 12',(jid,)).fetchall(); c.close()
    last=rounds[0]['created_at'] if rounds else j['clock_in_at']; next_due=''; seconds=0
    if j['status']=='On Watch' and last:
        try:
            due=datetime.fromisoformat(last)+timedelta(minutes=int(j['patrol_interval'])); next_due=due.isoformat(timespec='seconds'); seconds=max(0,int((due-datetime.now()).total_seconds()))
        except Exception: pass
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Assignment #{{j.id}}</span><h1>{{j.property_name}}</h1><p class="lead">{{j.address}}, {{j.city}} • {{j.business_name}}</p></div></section><section class="section"><div class="wrap"><div class="card"><h2>{{j.status}}</h2><p>Patrol every <b>{{j.patrol_interval}} minutes</b>. <span id="timer" data-due="{{next_due}}">{% if next_due %}Next round timer loading…{% endif %}</span></p><p><b>Reason:</b> {{j.impairment or 'Not specified'}}<br><b>Instructions:</b> {{j.instructions or 'Follow site instructions.'}}</p></div>{% if not j.clock_in_at %}<div class="form-shell" style="margin-top:18px"><form method="post" class="geo"><input type="hidden" name="action" value="clock_in"><input type="hidden" name="latitude"><input type="hidden" name="longitude"><input type="hidden" name="accuracy"><button class="btn primary">Clock In With GPS</button></form></div>{% elif not j.clock_out_at %}<div class="card-grid" style="margin-top:18px"><div class="form-shell"><h3>Patrol round</h3><form method="post" class="geo"><input type="hidden" name="action" value="round"><input type="hidden" name="latitude"><input type="hidden" name="longitude"><input type="hidden" name="accuracy"><label>Checkpoint code<input id="checkpoint_code" name="checkpoint_code" placeholder="Scan or enter code"></label><div class="actions"><button type="button" class="btn darkbtn" onclick="scanQR()">Scan QR</button><button type="button" class="btn darkbtn" onclick="scanNFC()">Scan NFC</button></div><label>Condition<select name="condition"><option>Clear</option><option>Issue observed</option><option>Corrected on round</option></select></label><label>Notes<textarea name="notes"></textarea></label><button class="btn primary">Record Round</button></form><p class="note">Assigned checkpoints: {% for cp in cps %}{{cp.label}} ({{cp.code}}){% if not loop.last %} • {% endif %}{% else %}none yet{% endfor %}</p></div><div class="form-shell"><h3>Photo evidence</h3><form method="post" enctype="multipart/form-data"><input type="hidden" name="action" value="photo"><label>Photo<input type="file" name="photo" accept="image/*" capture="environment" required></label><label>Caption<input name="caption"></label><button class="btn primary">Upload Photo</button></form></div><div class="form-shell"><h3>End assignment</h3><form method="post" class="geo"><input type="hidden" name="action" value="clock_out"><input type="hidden" name="latitude"><input type="hidden" name="longitude"><input type="hidden" name="accuracy"><button class="btn darkbtn">Clock Out With GPS</button></form></div></div>{% endif %}<h2>Recent patrols</h2><div class="table-card table-wrap"><table><tr><th>Time</th><th>Checkpoint</th><th>Condition</th><th>GPS</th></tr>{% for r in rounds %}<tr><td>{{r.created_at}}</td><td>{{r.checkpoint_label or r.checkpoint_code or 'General patrol'}}</td><td>{{r.condition}}</td><td>{{r.latitude}}, {{r.longitude}}</td></tr>{% else %}<tr><td colspan="4">No enhanced patrols yet.</td></tr>{% endfor %}</table></div><h2>Photos</h2><div class="card-grid">{% for p in photos %}<article class="card"><a href="/evidence/{{p.id}}" target="_blank"><b>{{p.filename}}</b></a><p>{{p.created_at}}<br>{{p.caption}}</p></article>{% else %}<p>No photos yet.</p>{% endfor %}</div></div></section><script>
function geoForm(f){return new Promise(res=>{if(!navigator.geolocation){res();return}navigator.geolocation.getCurrentPosition(p=>{f.querySelector('[name=latitude]').value=p.coords.latitude.toFixed(6);f.querySelector('[name=longitude]').value=p.coords.longitude.toFixed(6);f.querySelector('[name=accuracy]').value=Math.round(p.coords.accuracy);res()},()=>res(),{enableHighAccuracy:true,timeout:5000})})}
document.querySelectorAll('.geo').forEach(f=>f.addEventListener('submit',async e=>{e.preventDefault();await geoForm(f);f.submit()}));
const t=document.getElementById('timer'); if(t&&t.dataset.due){const tick=()=>{const n=new Date(t.dataset.due)-new Date(); if(n<=0){t.textContent='ROUND OVERDUE';t.style.color='#b42318';t.style.fontWeight='900'}else{const m=Math.floor(n/60000),s=Math.floor((n%60000)/1000);t.textContent='Next round in '+m+':'+String(s).padStart(2,'0')}};tick();setInterval(tick,1000)}
async function scanQR(){if(!('BarcodeDetector'in window)){alert('QR camera scanning is not supported in this browser. Enter the checkpoint code manually.');return}try{const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'}});const v=document.createElement('video');v.srcObject=stream;await v.play();const d=new BarcodeDetector({formats:['qr_code']});let tries=0;const timer=setInterval(async()=>{tries++;const r=await d.detect(v);if(r.length){document.getElementById('checkpoint_code').value=r[0].rawValue.toUpperCase();clearInterval(timer);stream.getTracks().forEach(x=>x.stop());v.remove()}if(tries>60){clearInterval(timer);stream.getTracks().forEach(x=>x.stop());alert('QR not found. Enter code manually.')}},250)}catch(e){alert('Camera scan unavailable. Enter code manually.')}}
async function scanNFC(){if(!('NDEFReader'in window)){alert('Web NFC is not supported on this device/browser.');return}try{const n=new NDEFReader();await n.scan();n.onreading=e=>{for(const r of e.message.records){if(r.recordType==='text'){const dec=new TextDecoder(r.encoding||'utf-8');document.getElementById('checkpoint_code').value=dec.decode(r.data).toUpperCase();break}}}}catch(e){alert('NFC scan could not start.')}}
</script>''','Assignment #'+str(jid),j=j,cps=cps,rounds=rounds,photos=photos,next_due=next_due)

@app.route('/evidence/<int:pid>')
@login_required
def evidence(pid):
    u=current_user(); c=db(); p=c.execute('SELECT * FROM photo_evidence WHERE id=?',(pid,)).fetchone()
    if not p: c.close(); abort(404)
    j=c.execute('SELECT * FROM fire_watch_jobs WHERE id=?',(p['job_id'],)).fetchone(); c.close()
    if u['role'] not in ('owner','supervisor') and not (u['employee_id'] and j and u['employee_id']==j['employee_id']): abort(403)
    return send_file(io.BytesIO(p['data']),mimetype=p['mimetype'] or 'image/jpeg',download_name=p['filename'] or 'evidence.jpg')

@app.route('/owner/checkpoints/<int:property_id>',methods=['GET','POST'])
@role_required('owner','supervisor')
def owner_checkpoints(property_id):
    c=db(); prop=c.execute('SELECT p.*,c.business_name FROM properties p JOIN customers c ON c.id=p.customer_id WHERE p.id=?',(property_id,)).fetchone()
    if not prop: c.close(); abort(404)
    if request.method=='POST':
        label=request.form.get('label','').strip()
        if not label: c.close(); flash('Checkpoint label required.'); return redirect(request.path)
        code=(request.form.get('code','').strip().upper() or ('CP-'+secrets.token_hex(3).upper()))
        try: c.execute('INSERT INTO checkpoints(property_id,label,code,latitude,longitude) VALUES(?,?,?,?,?)',(property_id,label,code,request.form.get('latitude',''),request.form.get('longitude',''))); c.commit()
        except Exception: c.close(); flash('Checkpoint code must be unique.'); return redirect(request.path)
        c.close(); flash('Checkpoint created.'); return redirect(request.path)
    cps=c.execute('SELECT * FROM checkpoints WHERE property_id=? ORDER BY label',(property_id,)).fetchall(); c.close()
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Checkpoints</span><h1>{{prop.name}}</h1><p class="lead">{{prop.business_name}} • {{prop.address}}</p></div></section><section class="section"><div class="wrap"><div class="card-grid">{% for cp in cps %}<article class="card"><h3>{{cp.label}}</h3><p style="font-family:monospace;font-size:1.1rem">{{cp.code}}</p><img src="/checkpoint/{{cp.id}}/qr.png" alt="QR" style="max-width:180px;width:100%"><p class="note">Program an NFC tag with the plain text: {{cp.code}}</p></article>{% endfor %}</div><div class="form-shell" style="margin-top:24px"><h3>Add checkpoint</h3><form method="post" class="form-grid"><label>Label<input name="label" placeholder="North stairwell" required></label><label>Custom code (optional)<input name="code"></label><label>Latitude<input name="latitude"></label><label>Longitude<input name="longitude"></label><div class="span2"><button class="btn primary">Create Checkpoint</button></div></form></div></div></section>''','Checkpoints',prop=prop,cps=cps)

@app.route('/checkpoint/<int:cid>/qr.png')
@role_required('owner','supervisor','worker')
def checkpoint_qr(cid):
    c=db(); cp=c.execute('SELECT * FROM checkpoints WHERE id=?',(cid,)).fetchone(); c.close()
    if not cp: abort(404)
    img=qrcode.make(cp['code']); buf=io.BytesIO(); img.save(buf,format='PNG'); buf.seek(0); return send_file(buf,mimetype='image/png')

@app.route('/owner/dispatch-map')
@role_required('owner','supervisor')
def dispatch_map():
    c=db(); locs=c.execute('''SELECT wl.*,u.username,p.name property_name,c.business_name FROM worker_locations wl JOIN users u ON u.id=wl.user_id LEFT JOIN fire_watch_jobs j ON j.id=wl.job_id LEFT JOIN properties p ON p.id=j.property_id LEFT JOIN customers c ON c.id=j.customer_id WHERE wl.id IN (SELECT MAX(id) FROM worker_locations GROUP BY user_id) ORDER BY wl.created_at DESC''').fetchall(); c.close()
    points=[dict(x) for x in locs]
    import json
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Live Operations</span><h1>Dispatch Map</h1><p class="lead">Latest GPS point submitted by each signed-in field worker.</p></div></section><section class="section"><div class="wrap"><div id="map" style="height:560px;border-radius:20px;overflow:hidden;border:1px solid #ccc"></div><p class="note">Location updates occur when a worker clocks in/out or records a patrol through the worker portal. This is not continuous background tracking.</p></div></section><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>const pts={{points|safe}};const map=L.map('map').setView([34.13,-116.32],9);L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'}).addTo(map);const bounds=[];for(const p of pts){const a=parseFloat(p.latitude),b=parseFloat(p.longitude);if(!Number.isFinite(a)||!Number.isFinite(b))continue;L.marker([a,b]).addTo(map).bindPopup('<b>'+p.username+'</b><br>'+(p.business_name||'')+' '+(p.property_name||'')+'<br>'+p.created_at);bounds.push([a,b])}if(bounds.length)map.fitBounds(bounds,{padding:[40,40]});</script>''','Dispatch Map',points=json.dumps(points))

@app.route('/owner/assets',methods=['GET','POST'])
@role_required('owner','supervisor')
def owner_assets():
    c=db(); props=c.execute('SELECT p.*,c.business_name,c.id customer_id FROM properties p JOIN customers c ON c.id=p.customer_id ORDER BY c.business_name,p.name').fetchall()
    if request.method=='POST':
        p=c.execute('SELECT * FROM properties WHERE id=?',(request.form.get('property_id'),)).fetchone()
        if not p: c.close(); flash('Select a property.'); return redirect(request.path)
        code=(request.form.get('asset_code','').strip().upper() or ('FE-'+secrets.token_hex(4).upper()))
        try:
            c.execute('''INSERT INTO extinguisher_assets(created_at,customer_id,property_id,asset_code,location_text,extinguisher_type,size_text,manufacturer,serial_number,manufacture_year,last_inspection,next_due,status,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(now(),p['customer_id'],p['id'],code,request.form.get('location_text','').strip(),request.form.get('extinguisher_type',''),request.form.get('size_text',''),request.form.get('manufacturer',''),request.form.get('serial_number',''),request.form.get('manufacture_year',''),request.form.get('last_inspection',''),request.form.get('next_due',''),request.form.get('status','In Service'),request.form.get('notes',''))); c.commit()
        except Exception: c.close(); flash('Asset code must be unique.'); return redirect(request.path)
        c.close(); flash('Extinguisher asset added.'); return redirect(request.path)
    assets=c.execute('''SELECT a.*,p.name property_name,c.business_name FROM extinguisher_assets a JOIN properties p ON p.id=a.property_id JOIN customers c ON c.id=a.customer_id ORDER BY a.id DESC''').fetchall(); c.close()
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Asset Management</span><h1>Extinguisher QR Registry</h1></div></section><section class="section"><div class="wrap"><div class="table-card table-wrap"><table><tr><th>Asset</th><th>Customer / Property</th><th>Location</th><th>Type</th><th>Next due</th><th>Status</th><th>QR</th></tr>{% for a in assets %}<tr><td><b>{{a.asset_code}}</b><br>{{a.serial_number}}</td><td>{{a.business_name}}<br>{{a.property_name}}</td><td>{{a.location_text}}</td><td>{{a.extinguisher_type}} {{a.size_text}}</td><td>{{a.next_due}}</td><td>{{a.status}}</td><td><a href="/asset/{{a.asset_code}}">Record</a> • <a href="/asset/{{a.asset_code}}/qr.png">QR</a></td></tr>{% else %}<tr><td colspan="7">No extinguisher assets yet.</td></tr>{% endfor %}</table></div><div class="form-shell" style="margin-top:24px"><h3>Add extinguisher</h3><form method="post" class="form-grid"><label>Property<select name="property_id" required><option value="">Select</option>{% for p in props %}<option value="{{p.id}}">{{p.business_name}} — {{p.name}}</option>{% endfor %}</select></label><label>Asset code (optional)<input name="asset_code"></label><label>Location<input name="location_text" placeholder="Building A rear exit" required></label><label>Type<input name="extinguisher_type" placeholder="ABC Dry Chemical"></label><label>Size<input name="size_text" placeholder="10 lb"></label><label>Manufacturer<input name="manufacturer"></label><label>Serial number<input name="serial_number"></label><label>Manufacture year<input name="manufacture_year"></label><label>Last inspection<input type="date" name="last_inspection"></label><label>Next due<input type="date" name="next_due"></label><label>Status<select name="status"><option>In Service</option><option>Needs Service</option><option>Out of Service</option><option>Retired</option></select></label><label class="span2">Notes<textarea name="notes"></textarea></label><div class="span2"><button class="btn primary">Add Asset</button></div></form></div></div></section>''','Extinguisher Assets',assets=assets,props=props)

@app.route('/asset/<code>')
def asset_record(code):
    c=db(); a=c.execute('''SELECT a.*,p.name property_name,p.address,p.city,c.business_name FROM extinguisher_assets a JOIN properties p ON p.id=a.property_id JOIN customers c ON c.id=a.customer_id WHERE a.asset_code=?''',(code.upper(),)).fetchone(); c.close()
    if not a: abort(404)
    return page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Asset Record</span><h1>{{a.asset_code}}</h1><p class="lead">{{a.business_name}} • {{a.property_name}}</p></div></section><section class="section"><div class="wrap card"><h2>{{a.status}}</h2><p><b>Location:</b> {{a.location_text}}<br><b>Type:</b> {{a.extinguisher_type}} {{a.size_text}}<br><b>Manufacturer:</b> {{a.manufacturer}}<br><b>Serial:</b> {{a.serial_number}}<br><b>Manufacture year:</b> {{a.manufacture_year}}<br><b>Last inspection:</b> {{a.last_inspection or '—'}}<br><b>Next due:</b> {{a.next_due or '—'}}</p><p class="note">Digital asset record only. Regulatory tags, inspection procedures and service must be performed as required by applicable law and the authority having jurisdiction.</p></div></section>''',a=a,title=a['asset_code'])

@app.route('/asset/<code>/qr.png')
@role_required('owner','supervisor')
def asset_qr(code):
    target=url_for('asset_record',code=code,_external=True); img=qrcode.make(target); buf=io.BytesIO(); img.save(buf,format='PNG'); buf.seek(0); return send_file(buf,mimetype='image/png')

@app.route('/customer/portal')
@role_required('customer','owner')
def customer_portal():
    u=current_user(); cid=request.args.get('customer_id',type=int) if u['role']=='owner' else u['customer_id']
    c=db(); customer=c.execute('SELECT * FROM customers WHERE id=?',(cid or -1,)).fetchone()
    if not customer: c.close(); return acct_page('''<section class="section"><div class="wrap card"><h2>No customer account linked</h2><p>An owner needs to link this login to a customer record.</p></div></section>''','Customer Portal')
    props=c.execute('SELECT * FROM properties WHERE customer_id=? ORDER BY name',(cid,)).fetchall(); jobs=c.execute('''SELECT j.*,p.name property_name FROM fire_watch_jobs j JOIN properties p ON p.id=j.property_id WHERE j.customer_id=? ORDER BY j.id DESC LIMIT 50''',(cid,)).fetchall(); assets=c.execute('''SELECT a.*,p.name property_name FROM extinguisher_assets a JOIN properties p ON p.id=a.property_id WHERE a.customer_id=? ORDER BY a.id DESC''',(cid,)).fetchall(); c.close()
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Customer Portal</span><h1>{{customer.business_name}}</h1><p class="lead">Properties, fire-watch records and tracked fire-safety assets.</p></div></section><section class="section"><div class="wrap"><h2>Properties</h2><div class="card-grid">{% for p in props %}<article class="card"><h3>{{p.name}}</h3><p>{{p.address}}<br>{{p.city}}</p></article>{% endfor %}</div><h2>Fire watch history</h2><div class="table-card table-wrap"><table><tr><th>Job</th><th>Property</th><th>Schedule</th><th>Status</th><th>Report</th></tr>{% for j in jobs %}<tr><td>#{{j.id}}</td><td>{{j.property_name}}</td><td>{{j.start_at}} — {{j.end_at or 'Open'}}</td><td>{{j.status}}</td><td>{% if user.role=='owner' %}<a href="/admin/fire-watch/{{j.id}}/report">View</a>{% else %}Available from office{% endif %}</td></tr>{% else %}<tr><td colspan="5">No fire-watch jobs.</td></tr>{% endfor %}</table></div><h2>Extinguisher assets</h2><div class="table-card table-wrap"><table><tr><th>Asset</th><th>Property</th><th>Location</th><th>Next due</th><th>Status</th></tr>{% for a in assets %}<tr><td><a href="/asset/{{a.asset_code}}">{{a.asset_code}}</a></td><td>{{a.property_name}}</td><td>{{a.location_text}}</td><td>{{a.next_due}}</td><td>{{a.status}}</td></tr>{% else %}<tr><td colspan="5">No tracked assets.</td></tr>{% endfor %}</table></div></div></section>''','Customer Portal',customer=customer,props=props,jobs=jobs,assets=assets)
