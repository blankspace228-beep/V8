import csv, io, json, os, secrets, zipfile
from datetime import datetime, timedelta
from functools import wraps
from flask import request, redirect, flash, abort, send_file, render_template_string, session
import app as base
import auth_upgrade as auth

app=base.app
page=base.page
db=base.db
current_user=auth.current_user
role_required=auth.role_required
acct_page=auth.acct_page

def now(): return datetime.now().isoformat(timespec='seconds')

def init_business_ops():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS audit_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at TEXT NOT NULL,
      user_id INTEGER,
      event_type TEXT NOT NULL,
      object_type TEXT,
      object_id TEXT,
      detail TEXT,
      ip_address TEXT
    );
    CREATE TABLE IF NOT EXISTS quotes(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at TEXT NOT NULL,
      customer_id INTEGER NOT NULL,
      property_id INTEGER,
      created_by INTEGER,
      quote_number TEXT NOT NULL UNIQUE,
      status TEXT NOT NULL DEFAULT 'Draft',
      valid_until TEXT,
      subtotal_cents INTEGER NOT NULL DEFAULT 0,
      tax_cents INTEGER NOT NULL DEFAULT 0,
      total_cents INTEGER NOT NULL DEFAULT 0,
      scope TEXT,
      terms TEXT,
      accepted_at TEXT,
      customer_signature TEXT
    );
    CREATE TABLE IF NOT EXISTS quote_items(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      quote_id INTEGER NOT NULL,
      description TEXT NOT NULL,
      quantity REAL NOT NULL DEFAULT 1,
      unit_price_cents INTEGER NOT NULL DEFAULT 0,
      line_total_cents INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS invoices(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at TEXT NOT NULL,
      customer_id INTEGER NOT NULL,
      property_id INTEGER,
      quote_id INTEGER,
      invoice_number TEXT NOT NULL UNIQUE,
      status TEXT NOT NULL DEFAULT 'Open',
      due_date TEXT,
      subtotal_cents INTEGER NOT NULL DEFAULT 0,
      tax_cents INTEGER NOT NULL DEFAULT 0,
      total_cents INTEGER NOT NULL DEFAULT 0,
      amount_paid_cents INTEGER NOT NULL DEFAULT 0,
      notes TEXT
    );
    CREATE TABLE IF NOT EXISTS invoice_items(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      invoice_id INTEGER NOT NULL,
      description TEXT NOT NULL,
      quantity REAL NOT NULL DEFAULT 1,
      unit_price_cents INTEGER NOT NULL DEFAULT 0,
      line_total_cents INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS service_records(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at TEXT NOT NULL,
      customer_id INTEGER NOT NULL,
      property_id INTEGER NOT NULL,
      asset_id INTEGER,
      technician_user_id INTEGER,
      service_type TEXT NOT NULL,
      result TEXT NOT NULL DEFAULT 'Completed',
      notes TEXT,
      next_due TEXT,
      certificate_ref TEXT
    );
    CREATE TABLE IF NOT EXISTS account_notes(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at TEXT NOT NULL,
      customer_id INTEGER NOT NULL,
      user_id INTEGER,
      note TEXT NOT NULL
    );
    '''); c.commit(); c.close()
init_business_ops()

def audit(event_type, object_type='', object_id='', detail=''):
    try:
        u=current_user(); c=db(); c.execute('INSERT INTO audit_events(created_at,user_id,event_type,object_type,object_id,detail,ip_address) VALUES(?,?,?,?,?,?,?)',(now(),u['id'] if u else None,event_type,object_type,str(object_id or ''),detail[:2000],request.headers.get('X-Forwarded-For',request.remote_addr or '')[:200])); c.commit(); c.close()
    except Exception:
        pass

def cents(v):
    try: return int(round(float(v or 0)*100))
    except Exception: return 0

def money(v): return f'${(int(v or 0)/100):,.2f}'

def num(prefix): return f'{prefix}-{datetime.now():%Y%m%d}-{secrets.token_hex(2).upper()}'

OPS_NAV='''<div style="display:flex;gap:8px;flex-wrap:wrap;margin:0 0 24px"><a class="btn darkbtn" href="/owner/operations">Operations</a><a class="btn darkbtn" href="/owner/quotes">Quotes</a><a class="btn darkbtn" href="/owner/invoices">Invoices</a><a class="btn darkbtn" href="/owner/service-records">Service History</a><a class="btn darkbtn" href="/owner/reminders">Due & Reminders</a><a class="btn darkbtn" href="/owner/audit">Audit Log</a><a class="btn darkbtn" href="/owner/export">Backup Export</a></div>'''

@app.after_request
def inject_ops_link(resp):
    try:
        u=current_user()
        if u and u['role'] in ('owner','supervisor') and resp.content_type and resp.content_type.startswith('text/html'):
            s=resp.get_data(as_text=True)
            if '</nav>' in s and '/owner/operations' not in s:
                s=s.replace('</nav>','<a href="/owner/operations">Operations</a></nav>',1); resp.set_data(s)
    except Exception: pass
    return resp

@app.route('/owner/operations')
@role_required('owner','supervisor')
def owner_operations():
    c=db()
    stats={
      'customers':c.execute('SELECT COUNT(*) FROM customers').fetchone()[0],
      'open_jobs':c.execute("SELECT COUNT(*) FROM fire_watch_jobs WHERE status!='Completed'").fetchone()[0],
      'workers':c.execute("SELECT COUNT(*) FROM users WHERE role IN ('worker','supervisor') AND active=1").fetchone()[0],
      'assets':c.execute('SELECT COUNT(*) FROM extinguisher_assets').fetchone()[0],
      'open_invoices':c.execute("SELECT COUNT(*) FROM invoices WHERE status IN ('Open','Partially Paid','Overdue')").fetchone()[0],
    }
    inv=c.execute("SELECT COALESCE(SUM(total_cents-amount_paid_cents),0) FROM invoices WHERE status IN ('Open','Partially Paid','Overdue')").fetchone()[0]
    due=c.execute("SELECT COUNT(*) FROM extinguisher_assets WHERE next_due!='' AND next_due<=date('now','+30 day') AND status!='Retired'").fetchone()[0]
    recent=c.execute('SELECT * FROM audit_events ORDER BY id DESC LIMIT 15').fetchall(); c.close()
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Business OS</span><h1>Operations Center</h1><p class="lead">Dispatch, accounts, quotes, billing, asset service history, reminders and audit records.</p></div></section><section class="section"><div class="wrap">'''+OPS_NAV+'''<div class="card-grid"><article class="card"><span class="eyebrow">Customers</span><h2>{{stats.customers}}</h2></article><article class="card"><span class="eyebrow">Open Watches</span><h2>{{stats.open_jobs}}</h2></article><article class="card"><span class="eyebrow">Workers</span><h2>{{stats.workers}}</h2></article><article class="card"><span class="eyebrow">Tracked Assets</span><h2>{{stats.assets}}</h2></article><article class="card"><span class="eyebrow">Open Invoices</span><h2>{{stats.open_invoices}}</h2><p>{{outstanding}} outstanding</p></article><article class="card"><span class="eyebrow">Due ≤30 Days</span><h2>{{due}}</h2><a href="/owner/reminders">Open reminder queue →</a></article></div><h2>Recent audit activity</h2><div class="table-card table-wrap"><table><tr><th>Time</th><th>Event</th><th>Object</th><th>Detail</th></tr>{% for a in recent %}<tr><td>{{a.created_at}}</td><td>{{a.event_type}}</td><td>{{a.object_type}} {{a.object_id}}</td><td>{{a.detail}}</td></tr>{% else %}<tr><td colspan="4">No audit events yet.</td></tr>{% endfor %}</table></div></div></section>''','Operations Center',stats=stats,outstanding=money(inv),due=due,recent=recent)

@app.route('/owner/quotes',methods=['GET','POST'])
@role_required('owner','supervisor')
def owner_quotes():
    c=db(); customers=c.execute('SELECT id,business_name FROM customers ORDER BY business_name').fetchall(); props=c.execute('SELECT p.id,p.name,p.customer_id,c.business_name FROM properties p JOIN customers c ON c.id=p.customer_id ORDER BY c.business_name,p.name').fetchall()
    if request.method=='POST':
        cid=request.form.get('customer_id'); pid=request.form.get('property_id') or None; desc=request.form.get('description','').strip(); qty=float(request.form.get('quantity') or 1); unit=cents(request.form.get('unit_price')); scope=request.form.get('scope','').strip(); terms=request.form.get('terms','').strip(); valid=request.form.get('valid_until','')
        if not cid or not desc: c.close(); flash('Customer and first line-item description are required.'); return redirect(request.path)
        total=int(round(qty*unit)); qn=num('Q'); u=current_user(); c.execute('INSERT INTO quotes(created_at,customer_id,property_id,created_by,quote_number,status,valid_until,subtotal_cents,total_cents,scope,terms) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(now(),cid,pid,u['id'],qn,'Draft',valid,total,total,scope,terms)); qid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; c.execute('INSERT INTO quote_items(quote_id,description,quantity,unit_price_cents,line_total_cents) VALUES(?,?,?,?,?)',(qid,desc,qty,unit,total)); c.commit(); c.close(); audit('quote_created','quote',qid,qn); return redirect('/owner/quotes/'+str(qid))
    rows=c.execute('''SELECT q.*,c.business_name,p.name property_name FROM quotes q JOIN customers c ON c.id=q.customer_id LEFT JOIN properties p ON p.id=q.property_id ORDER BY q.id DESC''').fetchall(); c.close()
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Sales</span><h1>Quotes</h1></div></section><section class="section"><div class="wrap">'''+OPS_NAV+'''<div class="table-card table-wrap"><table><tr><th>Quote</th><th>Customer</th><th>Status</th><th>Valid Until</th><th>Total</th></tr>{% for q in rows %}<tr><td><a href="/owner/quotes/{{q.id}}"><b>{{q.quote_number}}</b></a></td><td>{{q.business_name}}<br>{{q.property_name or ''}}</td><td>{{q.status}}</td><td>{{q.valid_until}}</td><td>{{money(q.total_cents)}}</td></tr>{% else %}<tr><td colspan="5">No quotes yet.</td></tr>{% endfor %}</table></div><div class="form-shell" style="margin-top:24px"><h3>Create quote</h3><form method="post" class="form-grid"><label>Customer<select name="customer_id" required><option value="">Select</option>{% for c in customers %}<option value="{{c.id}}">{{c.business_name}}</option>{% endfor %}</select></label><label>Property<select name="property_id"><option value="">Optional</option>{% for p in props %}<option value="{{p.id}}">{{p.business_name}} — {{p.name}}</option>{% endfor %}</select></label><label class="span2">First line item<input name="description" placeholder="Fire watch coverage - 8 hours" required></label><label>Quantity<input type="number" step="0.25" min="0" name="quantity" value="1"></label><label>Unit price ($)<input type="number" step="0.01" min="0" name="unit_price" required></label><label>Valid until<input type="date" name="valid_until"></label><label class="span2">Scope<textarea name="scope" rows="4"></textarea></label><label class="span2">Terms<textarea name="terms" rows="3"></textarea></label><div class="span2"><button class="btn primary">Create Quote</button></div></form></div></div></section>''','Quotes',rows=rows,customers=customers,props=props,money=money)

@app.route('/owner/quotes/<int:qid>',methods=['GET','POST'])
@role_required('owner','supervisor')
def quote_detail(qid):
    c=db(); q=c.execute('''SELECT q.*,c.business_name,p.name property_name,p.address property_address FROM quotes q JOIN customers c ON c.id=q.customer_id LEFT JOIN properties p ON p.id=q.property_id WHERE q.id=?''',(qid,)).fetchone()
    if not q: c.close(); abort(404)
    if request.method=='POST':
        action=request.form.get('action')
        if action=='add_item':
            desc=request.form.get('description','').strip(); qty=float(request.form.get('quantity') or 1); unit=cents(request.form.get('unit_price'))
            if desc: c.execute('INSERT INTO quote_items(quote_id,description,quantity,unit_price_cents,line_total_cents) VALUES(?,?,?,?,?)',(qid,desc,qty,unit,int(round(qty*unit))))
        elif action=='status' and request.form.get('status') in ('Draft','Sent','Accepted','Declined','Expired'):
            st=request.form['status']; c.execute('UPDATE quotes SET status=?,accepted_at=? WHERE id=?',(st,now() if st=='Accepted' else q['accepted_at'],qid))
        elif action=='invoice':
            invn=num('INV'); items=c.execute('SELECT * FROM quote_items WHERE quote_id=?',(qid,)).fetchall(); sub=sum(i['line_total_cents'] for i in items); due=(datetime.now()+timedelta(days=30)).date().isoformat(); c.execute('INSERT INTO invoices(created_at,customer_id,property_id,quote_id,invoice_number,status,due_date,subtotal_cents,total_cents,notes) VALUES(?,?,?,?,?,?,?,?,?,?)',(now(),q['customer_id'],q['property_id'],qid,invn,'Open',due,sub,sub,'Created from '+q['quote_number'])); iid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            for i in items: c.execute('INSERT INTO invoice_items(invoice_id,description,quantity,unit_price_cents,line_total_cents) VALUES(?,?,?,?,?)',(iid,i['description'],i['quantity'],i['unit_price_cents'],i['line_total_cents']))
            c.commit(); c.close(); audit('invoice_created','invoice',iid,invn+' from '+q['quote_number']); return redirect('/owner/invoices/'+str(iid))
        items=c.execute('SELECT * FROM quote_items WHERE quote_id=?',(qid,)).fetchall(); sub=sum(i['line_total_cents'] for i in items); c.execute('UPDATE quotes SET subtotal_cents=?,total_cents=? WHERE id=?',(sub,sub,qid)); c.commit(); c.close(); audit('quote_updated','quote',qid,action or ''); return redirect(request.path)
    items=c.execute('SELECT * FROM quote_items WHERE quote_id=? ORDER BY id',(qid,)).fetchall(); c.close()
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">{{q.quote_number}}</span><h1>{{q.business_name}}</h1><p class="lead">{{q.property_name or ''}} {{q.property_address or ''}}</p></div></section><section class="section"><div class="wrap">'''+OPS_NAV+'''<div class="card-grid"><article class="card"><h3>Status</h3><h2>{{q.status}}</h2><form method="post"><input type="hidden" name="action" value="status"><select name="status"><option>Draft</option><option>Sent</option><option>Accepted</option><option>Declined</option><option>Expired</option></select><button class="btn primary" style="margin-top:10px">Update</button></form></article><article class="card"><h3>Total</h3><h2>{{money(q.total_cents)}}</h2><p>Valid until: {{q.valid_until or '—'}}</p></article><article class="card"><h3>Convert</h3><form method="post"><input type="hidden" name="action" value="invoice"><button class="btn primary">Create Invoice</button></form></article></div><div class="table-card table-wrap" style="margin-top:20px"><table><tr><th>Description</th><th>Qty</th><th>Unit</th><th>Total</th></tr>{% for i in items %}<tr><td>{{i.description}}</td><td>{{i.quantity}}</td><td>{{money(i.unit_price_cents)}}</td><td>{{money(i.line_total_cents)}}</td></tr>{% endfor %}</table></div><div class="form-shell" style="margin-top:20px"><h3>Add line item</h3><form method="post" class="form-grid"><input type="hidden" name="action" value="add_item"><label class="span2">Description<input name="description" required></label><label>Quantity<input type="number" step="0.25" name="quantity" value="1"></label><label>Unit price ($)<input type="number" step="0.01" name="unit_price" required></label><div class="span2"><button class="btn primary">Add Item</button></div></form></div><div class="card" style="margin-top:20px"><h3>Scope</h3><p>{{q.scope or '—'}}</p><h3>Terms</h3><p>{{q.terms or '—'}}</p></div></div></section>''','Quote '+q['quote_number'],q=q,items=items,money=money)

@app.route('/owner/invoices')
@role_required('owner','supervisor')
def owner_invoices():
    c=db(); rows=c.execute('''SELECT i.*,c.business_name,p.name property_name FROM invoices i JOIN customers c ON c.id=i.customer_id LEFT JOIN properties p ON p.id=i.property_id ORDER BY i.id DESC''').fetchall(); c.close()
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Billing</span><h1>Invoices</h1></div></section><section class="section"><div class="wrap">'''+OPS_NAV+'''<div class="table-card table-wrap"><table><tr><th>Invoice</th><th>Customer</th><th>Due</th><th>Status</th><th>Total</th><th>Balance</th></tr>{% for i in rows %}<tr><td><a href="/owner/invoices/{{i.id}}"><b>{{i.invoice_number}}</b></a></td><td>{{i.business_name}}<br>{{i.property_name or ''}}</td><td>{{i.due_date or '—'}}</td><td>{{i.status}}</td><td>{{money(i.total_cents)}}</td><td>{{money(i.total_cents-i.amount_paid_cents)}}</td></tr>{% else %}<tr><td colspan="6">No invoices yet.</td></tr>{% endfor %}</table></div></div></section>''','Invoices',rows=rows,money=money)

@app.route('/owner/invoices/<int:iid>',methods=['GET','POST'])
@role_required('owner','supervisor')
def invoice_detail(iid):
    c=db(); inv=c.execute('''SELECT i.*,c.business_name,p.name property_name,p.address property_address FROM invoices i JOIN customers c ON c.id=i.customer_id LEFT JOIN properties p ON p.id=i.property_id WHERE i.id=?''',(iid,)).fetchone()
    if not inv: c.close(); abort(404)
    if request.method=='POST':
        action=request.form.get('action')
        if action=='payment':
            paid=inv['amount_paid_cents']+cents(request.form.get('amount')); status='Paid' if paid>=inv['total_cents'] else ('Partially Paid' if paid>0 else 'Open'); c.execute('UPDATE invoices SET amount_paid_cents=?,status=? WHERE id=?',(paid,status,iid)); audit('payment_recorded','invoice',iid,request.form.get('amount','0'))
        elif action=='status' and request.form.get('status') in ('Open','Partially Paid','Paid','Void','Overdue'):
            c.execute('UPDATE invoices SET status=? WHERE id=?',(request.form['status'],iid))
        c.commit(); c.close(); return redirect(request.path)
    items=c.execute('SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY id',(iid,)).fetchall(); c.close()
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">{{inv.invoice_number}}</span><h1>{{inv.business_name}}</h1><p class="lead">{{inv.property_name or ''}} {{inv.property_address or ''}}</p></div></section><section class="section"><div class="wrap">'''+OPS_NAV+'''<div class="card-grid"><article class="card"><h3>Status</h3><h2>{{inv.status}}</h2><p>Due {{inv.due_date or '—'}}</p></article><article class="card"><h3>Total</h3><h2>{{money(inv.total_cents)}}</h2><p>Paid {{money(inv.amount_paid_cents)}}<br>Balance {{money(inv.total_cents-inv.amount_paid_cents)}}</p></article><article class="card"><h3>Record payment</h3><form method="post"><input type="hidden" name="action" value="payment"><label>Amount ($)<input type="number" step="0.01" min="0" name="amount" required></label><button class="btn primary" style="margin-top:10px">Apply Payment</button></form></article></div><div class="table-card table-wrap" style="margin-top:20px"><table><tr><th>Description</th><th>Qty</th><th>Unit</th><th>Total</th></tr>{% for i in items %}<tr><td>{{i.description}}</td><td>{{i.quantity}}</td><td>{{money(i.unit_price_cents)}}</td><td>{{money(i.line_total_cents)}}</td></tr>{% endfor %}</table></div></div></section>''','Invoice '+inv['invoice_number'],inv=inv,items=items,money=money)

@app.route('/owner/service-records',methods=['GET','POST'])
@role_required('owner','supervisor')
def service_records():
    c=db(); assets=c.execute('''SELECT a.id,a.asset_code,a.property_id,a.customer_id,a.location_text,p.name property_name,c.business_name FROM extinguisher_assets a JOIN properties p ON p.id=a.property_id JOIN customers c ON c.id=a.customer_id ORDER BY c.business_name,p.name,a.asset_code''').fetchall(); users=c.execute("SELECT id,username FROM users WHERE role IN ('worker','supervisor','owner') AND active=1 ORDER BY username").fetchall()
    if request.method=='POST':
        aid=request.form.get('asset_id'); a=c.execute('SELECT * FROM extinguisher_assets WHERE id=?',(aid,)).fetchone()
        if not a: c.close(); flash('Select a valid asset.'); return redirect(request.path)
        typ=request.form.get('service_type','Inspection').strip(); result=request.form.get('result','Completed'); due=request.form.get('next_due',''); tech=request.form.get('technician_user_id') or None; notes=request.form.get('notes','').strip(); cert=request.form.get('certificate_ref','').strip(); c.execute('INSERT INTO service_records(created_at,customer_id,property_id,asset_id,technician_user_id,service_type,result,notes,next_due,certificate_ref) VALUES(?,?,?,?,?,?,?,?,?,?)',(now(),a['customer_id'],a['property_id'],a['id'],tech,typ,result,notes,due,cert));
        if due: c.execute('UPDATE extinguisher_assets SET last_inspection=?,next_due=?,status=? WHERE id=?',(datetime.now().date().isoformat(),due,'In Service' if result=='Completed' else 'Needs Service',a['id']))
        c.commit(); c.close(); audit('service_record_created','asset',aid,typ+' / '+result); return redirect(request.path)
    rows=c.execute('''SELECT s.*,a.asset_code,a.location_text,p.name property_name,c.business_name,u.username technician FROM service_records s LEFT JOIN extinguisher_assets a ON a.id=s.asset_id JOIN properties p ON p.id=s.property_id JOIN customers c ON c.id=s.customer_id LEFT JOIN users u ON u.id=s.technician_user_id ORDER BY s.id DESC LIMIT 250''').fetchall(); c.close()
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Compliance Records</span><h1>Asset Service History</h1></div></section><section class="section"><div class="wrap">'''+OPS_NAV+'''<div class="table-card table-wrap"><table><tr><th>Time</th><th>Asset</th><th>Customer</th><th>Service</th><th>Result</th><th>Next Due</th><th>Technician</th></tr>{% for s in rows %}<tr><td>{{s.created_at}}</td><td>{{s.asset_code}}<br>{{s.location_text}}</td><td>{{s.business_name}}<br>{{s.property_name}}</td><td>{{s.service_type}}</td><td>{{s.result}}</td><td>{{s.next_due}}</td><td>{{s.technician or '—'}}</td></tr>{% else %}<tr><td colspan="7">No service records yet.</td></tr>{% endfor %}</table></div><div class="form-shell" style="margin-top:24px"><h3>Add service record</h3><form method="post" class="form-grid"><label class="span2">Asset<select name="asset_id" required><option value="">Select</option>{% for a in assets %}<option value="{{a.id}}">{{a.business_name}} — {{a.property_name}} — {{a.asset_code}} — {{a.location_text}}</option>{% endfor %}</select></label><label>Service type<select name="service_type"><option>Inspection</option><option>Maintenance</option><option>Recharge</option><option>Repair</option><option>Replacement</option><option>Hydrostatic Test</option><option>Six-Year Maintenance</option></select></label><label>Result<select name="result"><option>Completed</option><option>Deficiency Found</option><option>Out of Service</option><option>Replaced</option></select></label><label>Technician<select name="technician_user_id"><option value="">Not assigned</option>{% for u in users %}<option value="{{u.id}}">{{u.username}}</option>{% endfor %}</select></label><label>Next due<input type="date" name="next_due"></label><label>Certificate / tag ref<input name="certificate_ref"></label><label class="span2">Notes<textarea name="notes"></textarea></label><div class="span2"><button class="btn primary">Save Service Record</button></div></form></div></div></section>''','Service History',rows=rows,assets=assets,users=users)

@app.route('/owner/reminders')
@role_required('owner','supervisor')
def reminders():
    c=db(); rows=c.execute('''SELECT a.*,p.name property_name,p.address,c.business_name,c.contact_name,c.phone,c.email FROM extinguisher_assets a JOIN properties p ON p.id=a.property_id JOIN customers c ON c.id=a.customer_id WHERE a.status!='Retired' AND a.next_due!='' ORDER BY a.next_due ASC''').fetchall(); c.close()
    today=datetime.now().date(); out=[]
    for r in rows:
        d=dict(r); d['days']=99999
        try: d['days']=(datetime.fromisoformat(r['next_due']).date()-today).days
        except Exception: pass
        d['bucket']='Overdue' if d['days']<0 else ('Due ≤30 Days' if d['days']<=30 else ('Due ≤90 Days' if d['days']<=90 else 'Later'))
        out.append(d)
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Recurring Revenue</span><h1>Due & Reminder Queue</h1><p class="lead">Use this list to contact customers before service dates become overdue.</p></div></section><section class="section"><div class="wrap">'''+OPS_NAV+'''<div class="table-card table-wrap"><table><tr><th>Due</th><th>Bucket</th><th>Asset</th><th>Customer</th><th>Contact</th><th>Status</th></tr>{% for a in rows %}<tr><td><b>{{a.next_due}}</b><br>{{a.days}} days</td><td>{{a.bucket}}</td><td><a href="/asset/{{a.asset_code}}">{{a.asset_code}}</a><br>{{a.location_text}}</td><td>{{a.business_name}}<br>{{a.property_name}}<br>{{a.address}}</td><td>{{a.contact_name}}<br>{{a.phone}}<br>{{a.email}}</td><td>{{a.status}}</td></tr>{% else %}<tr><td colspan="6">No dated assets yet.</td></tr>{% endfor %}</table></div></div></section>''','Due & Reminders',rows=out)

@app.route('/owner/audit')
@role_required('owner')
def audit_log():
    c=db(); rows=c.execute('''SELECT a.*,u.username FROM audit_events a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 500''').fetchall(); c.close()
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Security</span><h1>Audit Log</h1></div></section><section class="section"><div class="wrap">'''+OPS_NAV+'''<div class="table-card table-wrap"><table><tr><th>Time</th><th>User</th><th>Event</th><th>Object</th><th>IP</th><th>Detail</th></tr>{% for a in rows %}<tr><td>{{a.created_at}}</td><td>{{a.username or 'system'}}</td><td>{{a.event_type}}</td><td>{{a.object_type}} {{a.object_id}}</td><td>{{a.ip_address}}</td><td>{{a.detail}}</td></tr>{% endfor %}</table></div></div></section>''','Audit Log',rows=rows)

@app.route('/owner/export')
@role_required('owner')
def export_data():
    tables=['service_requests','job_applications','customers','properties','employees','fire_watch_jobs','patrol_logs','incident_logs','users','checkpoints','patrol_v2','worker_locations','extinguisher_assets','quotes','quote_items','invoices','invoice_items','service_records','audit_events']
    mem=io.BytesIO()
    with zipfile.ZipFile(mem,'w',zipfile.ZIP_DEFLATED) as z:
        c=db()
        manifest={'created_at':now(),'tables':{},'warning':'Portable administrative backup export. Photo evidence is intentionally excluded because binary data can be large.'}
        for t in tables:
            try:
                rows=c.execute('SELECT * FROM '+t).fetchall(); manifest['tables'][t]=len(rows)
                if rows:
                    s=io.StringIO(); w=csv.writer(s); keys=rows[0].keys(); w.writerow(keys)
                    for r in rows: w.writerow([r[k] for k in keys])
                    z.writestr(t+'.csv',s.getvalue())
                else: z.writestr(t+'.csv','')
            except Exception as e: manifest['tables'][t]='error'
        c.close(); z.writestr('manifest.json',json.dumps(manifest,indent=2))
    mem.seek(0); audit('backup_exported','system','','ZIP export'); return send_file(mem,mimetype='application/zip',as_attachment=True,download_name='high-desert-fire-backup-'+datetime.now().strftime('%Y%m%d-%H%M')+'.zip')

@app.route('/account/change-password',methods=['GET','POST'])
@auth.login_required
def change_password():
    u=current_user()
    if request.method=='POST':
        from werkzeug.security import check_password_hash, generate_password_hash
        old=request.form.get('old_password',''); new=request.form.get('new_password','')
        if not check_password_hash(u['password_hash'],old): flash('Current password is incorrect.'); return redirect(request.path)
        if len(new)<10: flash('New password must be at least 10 characters.'); return redirect(request.path)
        c=db(); c.execute('UPDATE users SET password_hash=? WHERE id=?',(generate_password_hash(new),u['id'])); c.commit(); c.close(); audit('password_changed','user',u['id'],'self-service'); session.clear(); flash('Password changed. Please sign in again.'); return redirect('/account/login')
    return acct_page('''<section class="page-head"><div class="wrap"><span class="eyebrow">Security</span><h1>Change password</h1></div></section><section class="section"><div class="wrap login-box" style="max-width:620px"><form method="post"><label>Current password<input type="password" name="old_password" required></label><label>New password<input type="password" minlength="10" name="new_password" required></label><button class="btn primary" style="margin-top:16px">Change Password</button></form></div></section>''','Change Password')

@app.route('/health/storage')
def storage_health():
    path=getattr(base,'DB_PATH','')
    return {'database':'sqlite','database_path':path,'database_url_configured':bool(os.environ.get('DATABASE_URL')),'persistent_database_ready':bool(os.environ.get('DATABASE_URL')),'photo_storage':'database_blob','production_note':'A dedicated persistent PostgreSQL database is still recommended before relying on this for business records.'}
