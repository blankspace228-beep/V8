import secrets
from datetime import datetime
from functools import wraps
from flask import request, redirect, url_for, flash, session, render_template_string, abort
import app as base

app=base.app
page=base.page
db=base.db

def now(): return datetime.now().isoformat(timespec='seconds')

def init_ops():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,business_name TEXT NOT NULL,contact_name TEXT,phone TEXT,email TEXT,billing_address TEXT,notes TEXT,status TEXT NOT NULL DEFAULT 'Active');
    CREATE TABLE IF NOT EXISTS properties(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_id INTEGER NOT NULL,name TEXT NOT NULL,address TEXT NOT NULL,city TEXT NOT NULL,site_contact TEXT,site_phone TEXT,notes TEXT);
    CREATE TABLE IF NOT EXISTS employees(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,full_name TEXT NOT NULL,phone TEXT,email TEXT,role TEXT NOT NULL DEFAULT 'Fire Watch',active INTEGER NOT NULL DEFAULT 1,notes TEXT);
    CREATE TABLE IF NOT EXISTS fire_watch_jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,customer_id INTEGER NOT NULL,property_id INTEGER NOT NULL,employee_id INTEGER,start_at TEXT NOT NULL,end_at TEXT,patrol_interval INTEGER NOT NULL DEFAULT 30,impairment TEXT,instructions TEXT,status TEXT NOT NULL DEFAULT 'Scheduled',access_code TEXT NOT NULL,clock_in_at TEXT,clock_out_at TEXT,clock_in_lat TEXT,clock_in_lng TEXT,clock_out_lat TEXT,clock_out_lng TEXT);
    CREATE TABLE IF NOT EXISTS patrol_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id INTEGER NOT NULL,created_at TEXT NOT NULL,checkpoint TEXT,condition TEXT NOT NULL,notes TEXT,latitude TEXT,longitude TEXT);
    CREATE TABLE IF NOT EXISTS incident_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id INTEGER NOT NULL,created_at TEXT NOT NULL,severity TEXT NOT NULL,category TEXT NOT NULL,description TEXT NOT NULL,action_taken TEXT,latitude TEXT,longitude TEXT);
    '''); c.commit(); c.close()
init_ops()

def guard(fn):
    @wraps(fn)
    def w(*a,**k):
        if not session.get('admin'): return redirect('/admin?next='+request.path)
        return fn(*a,**k)
    return w

NAV='''<div style="display:flex;gap:8px;flex-wrap:wrap;margin:0 0 24px"><a class="btn darkbtn" href="/admin/dashboard">Overview</a><a class="btn darkbtn" href="/admin/fire-watch">Fire Watch Command</a><a class="btn darkbtn" href="/admin/customers">Customers</a><a class="btn darkbtn" href="/admin/team">Team</a></div>'''

@app.after_request
def command_link(resp):
    if session.get('admin') and resp.content_type and resp.content_type.startswith('text/html'):
        try:
            s=resp.get_data(as_text=True)
            if '/admin/fire-watch' not in s and '</nav>' in s:
                s=s.replace('</nav>','<a href="/admin/fire-watch">Command</a></nav>',1); resp.set_data(s)
        except Exception: pass
    return resp

@app.route('/admin/fire-watch')
@guard
def fw_board():
    c=db(); jobs=c.execute('''SELECT j.*,p.name property_name,p.address,p.city,e.full_name employee_name,c.business_name,(SELECT COUNT(*) FROM patrol_logs r WHERE r.job_id=j.id) rounds,(SELECT COUNT(*) FROM incident_logs i WHERE i.job_id=j.id) incidents FROM fire_watch_jobs j JOIN properties p ON p.id=j.property_id JOIN customers c ON c.id=j.customer_id LEFT JOIN employees e ON e.id=j.employee_id ORDER BY j.id DESC''').fetchall(); c.close()
    return page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Operations</span><h1>Fire Watch Command</h1><p class="lead">Dispatch, clock-ins, mobile patrol rounds, incident logs, GPS capture and client-ready reports.</p></div></section><section class="section"><div class="wrap">'''+NAV+'''<div class="admin-head"><h2>Dispatch board</h2><a class="btn primary" href="/admin/fire-watch/new">New Fire Watch</a></div><div class="table-card table-wrap"><table><tr><th>Job</th><th>Customer / Site</th><th>Officer</th><th>Schedule</th><th>Activity</th><th>Status</th><th></th></tr>{% for j in jobs %}<tr><td>#{{j.id}}<br><span class="note">{{j.access_code}}</span></td><td><b>{{j.business_name}}</b><br>{{j.property_name}}<br>{{j.city}}</td><td>{{j.employee_name or 'Unassigned'}}</td><td>{{j.start_at}}<br>{{j.end_at or 'Open-ended'}}</td><td>{{j.rounds}} rounds<br>{{j.incidents}} incidents</td><td>{{j.status}}</td><td><a href="/admin/fire-watch/{{j.id}}">Open</a></td></tr>{% else %}<tr><td colspan="7">No jobs yet. Add a customer and property first.</td></tr>{% endfor %}</table></div></div></section>''',jobs=jobs,title='Fire Watch Command')

@app.route('/admin/customers',methods=['GET','POST'])
@guard
def fw_customers():
    c=db()
    if request.method=='POST':
        n=request.form.get('business_name','').strip()
        if not n: flash('Business name is required.'); c.close(); return redirect(request.path)
        c.execute('INSERT INTO customers(created_at,business_name,contact_name,phone,email,billing_address,notes) VALUES(?,?,?,?,?,?,?)',(now(),n,request.form.get('contact_name','').strip(),request.form.get('phone','').strip(),request.form.get('email','').strip(),request.form.get('billing_address','').strip(),request.form.get('notes','').strip())); c.commit(); c.close(); flash('Customer created.'); return redirect(request.path)
    rows=c.execute('SELECT * FROM customers ORDER BY business_name').fetchall(); c.close()
    return page('''<section class="page-head"><div class="wrap"><span class="eyebrow">CRM</span><h1>Customers & properties</h1></div></section><section class="section"><div class="wrap">'''+NAV+'''<div class="card-grid">{% for x in rows %}<article class="card"><span class="badge Available">{{x.status}}</span><h3>{{x.business_name}}</h3><p>{{x.contact_name}}<br>{{x.phone}}<br>{{x.email}}</p><a href="/admin/customers/{{x.id}}">Open account →</a></article>{% else %}<p>No customers yet.</p>{% endfor %}</div><div class="form-shell" style="margin-top:24px"><h3>Add customer</h3><form method="post" class="form-grid"><label>Business name *<input name="business_name" required></label><label>Contact<input name="contact_name"></label><label>Phone<input name="phone"></label><label>Email<input type="email" name="email"></label><label class="span2">Billing address<input name="billing_address"></label><label class="span2">Notes<textarea name="notes"></textarea></label><div class="span2"><button class="btn primary">Create Customer</button></div></form></div></div></section>''',rows=rows,title='Customers')

@app.route('/admin/customers/<int:cid>',methods=['GET','POST'])
@guard
def fw_customer(cid):
    c=db(); customer=c.execute('SELECT * FROM customers WHERE id=?',(cid,)).fetchone()
    if not customer: c.close(); abort(404)
    if request.method=='POST':
        n=request.form.get('name','').strip(); a=request.form.get('address','').strip(); city=request.form.get('city','').strip()
        if not n or not a or not city: flash('Property name, address and city are required.'); c.close(); return redirect(request.path)
        c.execute('INSERT INTO properties(customer_id,name,address,city,site_contact,site_phone,notes) VALUES(?,?,?,?,?,?,?)',(cid,n,a,city,request.form.get('site_contact','').strip(),request.form.get('site_phone','').strip(),request.form.get('notes','').strip())); c.commit(); c.close(); flash('Property added.'); return redirect(request.path)
    props=c.execute('SELECT * FROM properties WHERE customer_id=? ORDER BY name',(cid,)).fetchall(); c.close()
    return page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Customer</span><h1>{{customer.business_name}}</h1></div></section><section class="section"><div class="wrap">'''+NAV+'''<div class="table-card"><b>{{customer.contact_name}}</b><p>{{customer.phone}} • {{customer.email}}<br>{{customer.billing_address}}</p></div><h2>Properties</h2><div class="card-grid">{% for p in props %}<article class="card"><h3>{{p.name}}</h3><p>{{p.address}}<br>{{p.city}}<br>{{p.site_contact}} {{p.site_phone}}</p><a href="/admin/fire-watch/new?property_id={{p.id}}">Create fire watch →</a></article>{% else %}<p>No properties yet.</p>{% endfor %}</div><div class="form-shell" style="margin-top:24px"><h3>Add property</h3><form method="post" class="form-grid"><label>Property name *<input name="name" required></label><label>City *<input name="city" required></label><label class="span2">Address *<input name="address" required></label><label>Site contact<input name="site_contact"></label><label>Site phone<input name="site_phone"></label><label class="span2">Notes<textarea name="notes"></textarea></label><div class="span2"><button class="btn primary">Add Property</button></div></form></div></div></section>''',customer=customer,props=props,title=customer['business_name'])

@app.route('/admin/team',methods=['GET','POST'])
@guard
def fw_team():
    c=db()
    if request.method=='POST':
        n=request.form.get('full_name','').strip()
        if not n: flash('Name is required.'); c.close(); return redirect(request.path)
        c.execute('INSERT INTO employees(created_at,full_name,phone,email,role,notes) VALUES(?,?,?,?,?,?)',(now(),n,request.form.get('phone','').strip(),request.form.get('email','').strip(),request.form.get('role','Fire Watch'),request.form.get('notes','').strip())); c.commit(); c.close(); flash('Team member added.'); return redirect(request.path)
    rows=c.execute('SELECT * FROM employees ORDER BY full_name').fetchall(); c.close()
    return page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Team</span><h1>Fire watch personnel</h1></div></section><section class="section"><div class="wrap">'''+NAV+'''<div class="table-card table-wrap"><table><tr><th>Name</th><th>Role</th><th>Phone</th><th>Email</th></tr>{% for e in rows %}<tr><td><b>{{e.full_name}}</b></td><td>{{e.role}}</td><td>{{e.phone}}</td><td>{{e.email}}</td></tr>{% else %}<tr><td colspan="4">No team members yet.</td></tr>{% endfor %}</table></div><div class="form-shell" style="margin-top:24px"><h3>Add team member</h3><form method="post" class="form-grid"><label>Name *<input name="full_name" required></label><label>Role<select name="role"><option>Fire Watch</option><option>Supervisor</option><option>Operations</option></select></label><label>Phone<input name="phone"></label><label>Email<input type="email" name="email"></label><label class="span2">Notes<textarea name="notes"></textarea></label><div class="span2"><button class="btn primary">Add Team Member</button></div></form></div></div></section>''',rows=rows,title='Team')

@app.route('/admin/fire-watch/new',methods=['GET','POST'])
@guard
def fw_new():
    c=db(); props=c.execute('SELECT p.*,c.business_name FROM properties p JOIN customers c ON c.id=p.customer_id ORDER BY c.business_name,p.name').fetchall(); team=c.execute('SELECT * FROM employees WHERE active=1 ORDER BY full_name').fetchall(); selected=request.args.get('property_id','')
    if request.method=='POST':
        p=c.execute('SELECT * FROM properties WHERE id=?',(request.form.get('property_id'),)).fetchone()
        if not p or not request.form.get('start_at'): flash('Property and start time are required.'); c.close(); return redirect(request.path)
        code=secrets.token_hex(3).upper(); c.execute('''INSERT INTO fire_watch_jobs(created_at,customer_id,property_id,employee_id,start_at,end_at,patrol_interval,impairment,instructions,status,access_code) VALUES(?,?,?,?,?,?,?,?,?,'Scheduled',?)''',(now(),p['customer_id'],p['id'],request.form.get('employee_id') or None,request.form['start_at'],request.form.get('end_at') or None,int(request.form.get('patrol_interval') or 30),request.form.get('impairment','').strip(),request.form.get('instructions','').strip(),code)); jid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.commit(); c.close(); flash('Fire watch created.'); return redirect('/admin/fire-watch/'+str(jid))
    c.close()
    return page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Dispatch</span><h1>Create fire watch</h1></div></section><section class="section"><div class="wrap">'''+NAV+'''<div class="form-shell"><form method="post" class="form-grid"><label>Customer property *<select name="property_id" required><option value="">Select</option>{% for p in props %}<option value="{{p.id}}" {% if selected|string==p.id|string %}selected{% endif %}>{{p.business_name}} — {{p.name}} — {{p.city}}</option>{% endfor %}</select></label><label>Assigned officer<select name="employee_id"><option value="">Unassigned</option>{% for e in team %}<option value="{{e.id}}">{{e.full_name}}</option>{% endfor %}</select></label><label>Start *<input type="datetime-local" name="start_at" required></label><label>Expected end<input type="datetime-local" name="end_at"></label><label>Patrol interval (minutes)<input type="number" min="5" step="5" value="30" name="patrol_interval"></label><label>Impairment / reason<input name="impairment" placeholder="Fire alarm out of service"></label><label class="span2">Instructions<textarea name="instructions" rows="5" placeholder="Patrol route, emergency contacts, checkpoints, hazards..."></textarea></label><div class="span2"><button class="btn primary">Create & Issue Access Code</button></div></form></div></div></section>''',props=props,team=team,selected=selected,title='Create Fire Watch')

@app.route('/admin/fire-watch/<int:jid>')
@guard
def fw_detail(jid):
    c=db(); j=c.execute('''SELECT j.*,p.name property_name,p.address,p.city,e.full_name employee_name,c.business_name FROM fire_watch_jobs j JOIN properties p ON p.id=j.property_id JOIN customers c ON c.id=j.customer_id LEFT JOIN employees e ON e.id=j.employee_id WHERE j.id=?''',(jid,)).fetchone()
    if not j: c.close(); abort(404)
    rounds=c.execute('SELECT * FROM patrol_logs WHERE job_id=? ORDER BY id DESC',(jid,)).fetchall(); inc=c.execute('SELECT * FROM incident_logs WHERE job_id=? ORDER BY id DESC',(jid,)).fetchall(); c.close(); mobile=url_for('fw_mobile',code=j['access_code'],_external=True)
    return page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Fire Watch #{{j.id}}</span><h1>{{j.property_name}}</h1><p class="lead">{{j.business_name}} • {{j.address}}, {{j.city}}</p></div></section><section class="section"><div class="wrap">'''+NAV+'''<div class="card-grid"><article class="card"><span class="eyebrow">Status</span><h2>{{j.status}}</h2><p><b>Assigned:</b> {{j.employee_name or 'Unassigned'}}<br><b>Start:</b> {{j.start_at}}<br><b>End:</b> {{j.end_at or 'Open-ended'}}<br><b>Interval:</b> {{j.patrol_interval}} min<br><b>Clock in:</b> {{j.clock_in_at or '—'}}<br><b>Clock out:</b> {{j.clock_out_at or '—'}}</p></article><article class="card"><span class="eyebrow">Mobile Access</span><h2 style="font-family:monospace">{{j.access_code}}</h2><p class="note">{{mobile}}</p><div class="actions"><a class="btn primary" href="{{mobile}}">Open Mobile Watch</a><a class="btn darkbtn" href="/admin/fire-watch/{{j.id}}/report">Report</a></div></article><article class="card"><span class="eyebrow">Assignment</span><p><b>Reason:</b> {{j.impairment or 'Not specified'}}</p><p><b>Instructions:</b> {{j.instructions or 'None entered'}}</p></article></div><h2>Patrol rounds ({{rounds|length}})</h2><div class="table-card table-wrap"><table><tr><th>Time</th><th>Checkpoint</th><th>Condition</th><th>GPS</th><th>Notes</th></tr>{% for r in rounds %}<tr><td>{{r.created_at}}</td><td>{{r.checkpoint}}</td><td>{{r.condition}}</td><td>{{r.latitude}}, {{r.longitude}}</td><td>{{r.notes}}</td></tr>{% else %}<tr><td colspan="5">No rounds yet.</td></tr>{% endfor %}</table></div><h2>Incidents ({{inc|length}})</h2><div class="table-card table-wrap"><table><tr><th>Time</th><th>Severity</th><th>Category</th><th>Description</th><th>Action</th></tr>{% for i in inc %}<tr><td>{{i.created_at}}</td><td>{{i.severity}}</td><td>{{i.category}}</td><td>{{i.description}}</td><td>{{i.action_taken}}</td></tr>{% else %}<tr><td colspan="5">No incidents.</td></tr>{% endfor %}</table></div></div></section>''',j=j,rounds=rounds,inc=inc,mobile=mobile,title='Fire Watch #'+str(jid))

@app.route('/watch/<code>',methods=['GET','POST'])
def fw_mobile(code):
    c=db(); j=c.execute('''SELECT j.*,p.name property_name,p.address,p.city,e.full_name employee_name,c.business_name FROM fire_watch_jobs j JOIN properties p ON p.id=j.property_id JOIN customers c ON c.id=j.customer_id LEFT JOIN employees e ON e.id=j.employee_id WHERE j.access_code=?''',(code.upper(),)).fetchone()
    if not j: c.close(); abort(404)
    if request.method=='POST':
        a=request.form.get('action'); lat=request.form.get('latitude',''); lng=request.form.get('longitude','')
        if a=='clock_in' and not j['clock_in_at']: c.execute("UPDATE fire_watch_jobs SET clock_in_at=?,clock_in_lat=?,clock_in_lng=?,status='On Watch' WHERE id=?",(now(),lat,lng,j['id'])); flash('Clocked in. Watch active.')
        elif a=='round': c.execute('INSERT INTO patrol_logs(job_id,created_at,checkpoint,condition,notes,latitude,longitude) VALUES(?,?,?,?,?,?,?)',(j['id'],now(),request.form.get('checkpoint','').strip(),request.form.get('condition','Clear'),request.form.get('notes','').strip(),lat,lng)); flash('Patrol round logged.')
        elif a=='incident':
            if not request.form.get('description','').strip(): flash('Description required.'); c.close(); return redirect(request.path)
            c.execute('INSERT INTO incident_logs(job_id,created_at,severity,category,description,action_taken,latitude,longitude) VALUES(?,?,?,?,?,?,?,?)',(j['id'],now(),request.form.get('severity','Routine'),request.form.get('category','Other'),request.form['description'].strip(),request.form.get('action_taken','').strip(),lat,lng)); flash('Incident logged.')
        elif a=='clock_out' and not j['clock_out_at']: c.execute("UPDATE fire_watch_jobs SET clock_out_at=?,clock_out_lat=?,clock_out_lng=?,status='Completed' WHERE id=?",(now(),lat,lng,j['id'])); flash('Clocked out. Watch complete.')
        c.commit(); c.close(); return redirect(request.path)
    rounds=c.execute('SELECT * FROM patrol_logs WHERE job_id=? ORDER BY id DESC LIMIT 10',(j['id'],)).fetchall(); inc=c.execute('SELECT * FROM incident_logs WHERE job_id=? ORDER BY id DESC LIMIT 5',(j['id'],)).fetchall(); c.close()
    return page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Fire Watch Mobile</span><h1>{{j.property_name}}</h1><p class="lead">{{j.address}}, {{j.city}} • {{j.business_name}}</p></div></section><section class="section"><div class="wrap"><div class="card"><h2>{{j.status}}</h2><p>Assigned: {{j.employee_name or 'Unassigned'}} • Required patrol interval: {{j.patrol_interval}} min</p><p><b>Reason:</b> {{j.impairment or 'Not specified'}}<br><b>Instructions:</b> {{j.instructions or 'Follow assigned site procedures.'}}</p></div>{% if not j.clock_in_at %}<div class="form-shell" style="margin-top:18px;text-align:center"><h2>Start watch</h2><form method="post" class="geo"><input type="hidden" name="action" value="clock_in"><input type="hidden" name="latitude"><input type="hidden" name="longitude"><button class="btn primary">Clock In & Start</button></form></div>{% elif not j.clock_out_at %}<div class="card-grid" style="margin-top:18px"><div class="form-shell"><h3>Log patrol round</h3><form method="post" class="geo"><input type="hidden" name="action" value="round"><input type="hidden" name="latitude"><input type="hidden" name="longitude"><label>Checkpoint<input name="checkpoint" required></label><label>Condition<select name="condition"><option>Clear</option><option>Issue observed</option><option>Corrected on round</option></select></label><label>Notes<textarea name="notes"></textarea></label><button class="btn primary">Record Round</button></form></div><div class="form-shell"><h3>Incident / hazard</h3><form method="post" class="geo"><input type="hidden" name="action" value="incident"><input type="hidden" name="latitude"><input type="hidden" name="longitude"><label>Severity<select name="severity"><option>Routine</option><option>Urgent</option><option>Emergency</option></select></label><label>Category<select name="category"><option>Fire / Smoke</option><option>Alarm / Sprinkler</option><option>Blocked egress</option><option>Hot work</option><option>Unsafe condition</option><option>Other</option></select></label><label>Description<textarea name="description" required></textarea></label><label>Action taken<textarea name="action_taken"></textarea></label><button class="btn primary">Record Incident</button></form></div><div class="form-shell"><h3>End watch</h3><form method="post" class="geo"><input type="hidden" name="action" value="clock_out"><input type="hidden" name="latitude"><input type="hidden" name="longitude"><button class="btn darkbtn">Clock Out & Complete</button></form></div></div>{% else %}<div class="success-box" style="margin-top:18px"><h2>Watch complete</h2><p>Clocked out {{j.clock_out_at}}</p></div>{% endif %}<h2>Recent rounds</h2><div class="table-card table-wrap"><table><tr><th>Time</th><th>Checkpoint</th><th>Condition</th><th>Notes</th></tr>{% for r in rounds %}<tr><td>{{r.created_at}}</td><td>{{r.checkpoint}}</td><td>{{r.condition}}</td><td>{{r.notes}}</td></tr>{% else %}<tr><td colspan="4">No rounds yet.</td></tr>{% endfor %}</table></div></div></section><script>document.querySelectorAll('.geo').forEach(f=>f.addEventListener('submit',e=>{if(!navigator.geolocation)return;e.preventDefault();navigator.geolocation.getCurrentPosition(p=>{f.querySelector('[name=latitude]').value=p.coords.latitude.toFixed(6);f.querySelector('[name=longitude]').value=p.coords.longitude.toFixed(6);f.submit()},()=>f.submit(),{enableHighAccuracy:true,timeout:4000})}))</script>''',j=j,rounds=rounds,inc=inc,title='Fire Watch Mobile')

@app.route('/admin/fire-watch/<int:jid>/report')
@guard
def fw_report(jid):
    c=db(); j=c.execute('''SELECT j.*,p.name property_name,p.address,p.city,e.full_name employee_name,c.business_name FROM fire_watch_jobs j JOIN properties p ON p.id=j.property_id JOIN customers c ON c.id=j.customer_id LEFT JOIN employees e ON e.id=j.employee_id WHERE j.id=?''',(jid,)).fetchone()
    if not j: c.close(); abort(404)
    rounds=c.execute('SELECT * FROM patrol_logs WHERE job_id=? ORDER BY id',(jid,)).fetchall(); inc=c.execute('SELECT * FROM incident_logs WHERE job_id=? ORDER BY id',(jid,)).fetchall(); c.close()
    return render_template_string('''<!doctype html><html><head><meta charset="utf-8"><title>Fire Watch Report</title><style>body{font-family:Arial;margin:36px;color:#111}.box{border:1px solid #999;padding:12px;margin:12px 0}table{width:100%;border-collapse:collapse;font-size:12px}th,td{border:1px solid #999;padding:6px;text-align:left;vertical-align:top}@media print{button{display:none}}</style></head><body><button onclick="print()">Print / Save PDF</button><h1>High Desert Fire Protection & Safety</h1><p>Fire Watch Activity Report • Job #{{j.id}}</p><div class="box"><b>Customer:</b> {{j.business_name}}<br><b>Property:</b> {{j.property_name}}, {{j.address}}, {{j.city}}<br><b>Assigned:</b> {{j.employee_name or 'Unassigned'}}<br><b>Status:</b> {{j.status}}<br><b>Scheduled:</b> {{j.start_at}} — {{j.end_at or 'Open-ended'}}<br><b>Clock:</b> {{j.clock_in_at or '—'}} — {{j.clock_out_at or '—'}}<br><b>Reason:</b> {{j.impairment or 'Not specified'}}<br><b>Instructions:</b> {{j.instructions or 'None'}}</div><h2>Patrol Rounds</h2><table><tr><th>#</th><th>Time</th><th>Checkpoint</th><th>Condition</th><th>GPS</th><th>Notes</th></tr>{% for r in rounds %}<tr><td>{{loop.index}}</td><td>{{r.created_at}}</td><td>{{r.checkpoint}}</td><td>{{r.condition}}</td><td>{{r.latitude}}, {{r.longitude}}</td><td>{{r.notes}}</td></tr>{% else %}<tr><td colspan="6">No rounds.</td></tr>{% endfor %}</table><h2>Incident Log</h2><table><tr><th>Time</th><th>Severity</th><th>Category</th><th>Description</th><th>Action</th></tr>{% for i in inc %}<tr><td>{{i.created_at}}</td><td>{{i.severity}}</td><td>{{i.category}}</td><td>{{i.description}}</td><td>{{i.action_taken}}</td></tr>{% else %}<tr><td colspan="5">No incidents.</td></tr>{% endfor %}</table><p style="color:#666;font-size:11px">Operational record only. This report does not itself certify regulatory compliance or replace requirements imposed by the authority having jurisdiction.</p></body></html>''',j=j,rounds=rounds,inc=inc)

import auth_upgrade
