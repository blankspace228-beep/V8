import random
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

CAREERS={
    'student':{'label':'Student','income':1200},
    'emt':{'label':'EMT','income':4000},
    'firefighter':{'label':'Firefighter','income':6200},
    'teacher':{'label':'Teacher','income':5100},
    'developer':{'label':'Software Developer','income':8200},
    'entrepreneur':{'label':'Entrepreneur','income':3500},
}
BUSINESS_TYPES={
    'junk_removal':{'label':'Junk Removal','startup':6500,'base_revenue':7200,'base_cost':4100},
    'security':{'label':'Security / Patrol','startup':9000,'base_revenue':9800,'base_cost':6100},
    'cleaning':{'label':'Cleaning Company','startup':3200,'base_revenue':5800,'base_cost':3000},
    'landscaping':{'label':'Landscaping','startup':5400,'base_revenue':7600,'base_cost':4300},
    'ecommerce':{'label':'E-commerce','startup':4500,'base_revenue':6400,'base_cost':3900},
    'tech':{'label':'Technology Startup','startup':18000,'base_revenue':12000,'base_cost':10500},
}

class LifeSetup(BaseModel):
    age:int=Field(default=20,ge=16,le=90)
    career:str=Field(default='student',max_length=40)
    cash:float=Field(default=5000,ge=0,le=10_000_000)
    monthly_housing:float=Field(default=1200,ge=0,le=100_000)
    monthly_transport:float=Field(default=450,ge=0,le=100_000)
    monthly_other:float=Field(default=800,ge=0,le=100_000)
    debt:float=Field(default=0,ge=0,le=10_000_000)
    credit_score:int=Field(default=650,ge=300,le=850)

class BusinessSetup(BaseModel):
    name:str=Field(min_length=2,max_length=60)
    business_type:str=Field(max_length=40)

class MonthAction(BaseModel):
    save_extra:float=Field(default=0,ge=0,le=1_000_000)
    debt_payment:float=Field(default=0,ge=0,le=1_000_000)
    business_marketing:float=Field(default=0,ge=0,le=1_000_000)


def register(app,base):
    def ensure():
        c=base.db()
        c.execute('''CREATE TABLE IF NOT EXISTS purple_life_profiles(
            user_id INTEGER PRIMARY KEY,age INTEGER NOT NULL,career TEXT NOT NULL,cash REAL NOT NULL,
            monthly_income REAL NOT NULL,monthly_housing REAL NOT NULL,monthly_transport REAL NOT NULL,
            monthly_other REAL NOT NULL,debt REAL NOT NULL,credit_score INTEGER NOT NULL,
            sim_month INTEGER NOT NULL DEFAULT 1,sim_year INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS purple_businesses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,name TEXT NOT NULL,business_type TEXT NOT NULL,
            cash REAL NOT NULL,revenue REAL NOT NULL,costs REAL NOT NULL,employees INTEGER NOT NULL DEFAULT 1,
            customers INTEGER NOT NULL DEFAULT 8,reputation REAL NOT NULL DEFAULT 50,marketing REAL NOT NULL DEFAULT 0,
            valuation REAL NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS purple_world_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,sim_year INTEGER NOT NULL,sim_month INTEGER NOT NULL,
            category TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,impact REAL NOT NULL DEFAULT 0,created_at TEXT NOT NULL)''')
        c.commit();c.close()
    ensure()

    def uid(request):
        try:return int(base.current_user_id(request))
        except Exception:raise HTTPException(401,'Login required')

    def life_row(c,user_id):
        return c.execute('SELECT * FROM purple_life_profiles WHERE user_id=?',(user_id,)).fetchone()

    def business_row(c,user_id):
        return c.execute('SELECT * FROM purple_businesses WHERE user_id=? ORDER BY id DESC LIMIT 1',(user_id,)).fetchone()

    def dashboard(user_id):
        ensure();c=base.db();life=life_row(c,user_id);biz=business_row(c,user_id)
        events=[dict(x) for x in c.execute('SELECT * FROM purple_world_events WHERE user_id=? ORDER BY id DESC LIMIT 8',(user_id,)).fetchall()]
        if not life:
            c.close();return {'configured':False,'careers':CAREERS,'business_types':BUSINESS_TYPES,'events':[]}
        life=dict(life);b=dict(biz) if biz else None
        net=life['cash']-life['debt']+(b['valuation'] if b else 0)
        monthly_expenses=life['monthly_housing']+life['monthly_transport']+life['monthly_other']
        burn=monthly_expenses-life['monthly_income']
        c.close()
        return {'configured':True,'life':life,'business':b,'events':events,'careers':CAREERS,'business_types':BUSINESS_TYPES,
                'summary':{'net_worth':round(net,2),'monthly_expenses':round(monthly_expenses,2),'monthly_surplus':round(-burn,2)}}

    @app.get('/api/world/dashboard')
    def world_dashboard(request:Request):
        return dashboard(uid(request))

    @app.post('/api/world/life/setup')
    def life_setup(req:LifeSetup,request:Request):
        user_id=uid(request);career=req.career if req.career in CAREERS else 'student';income=CAREERS[career]['income'];c=base.db()
        c.execute('''INSERT INTO purple_life_profiles(user_id,age,career,cash,monthly_income,monthly_housing,monthly_transport,monthly_other,debt,credit_score,sim_month,sim_year,updated_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?,1,1,?)
                     ON CONFLICT(user_id) DO UPDATE SET age=excluded.age,career=excluded.career,cash=excluded.cash,monthly_income=excluded.monthly_income,
                     monthly_housing=excluded.monthly_housing,monthly_transport=excluded.monthly_transport,monthly_other=excluded.monthly_other,debt=excluded.debt,
                     credit_score=excluded.credit_score,updated_at=excluded.updated_at''',
                  (user_id,req.age,career,req.cash,income,req.monthly_housing,req.monthly_transport,req.monthly_other,req.debt,req.credit_score,base.now_iso()))
        c.commit();c.close();return dashboard(user_id)

    @app.post('/api/world/business/start')
    def start_business(req:BusinessSetup,request:Request):
        user_id=uid(request);kind=req.business_type
        if kind not in BUSINESS_TYPES:raise HTTPException(400,'Unknown business type')
        c=base.db();life=life_row(c,user_id)
        if not life:c.close();raise HTTPException(409,'Create your Purple Life profile first')
        existing=business_row(c,user_id)
        if existing:c.close();raise HTTPException(409,'You already operate a simulated business')
        spec=BUSINESS_TYPES[kind];startup=float(spec['startup'])
        if float(life['cash'])<startup:c.close();raise HTTPException(409,f'You need ${startup:,.0f} simulated cash to launch this business')
        c.execute('UPDATE purple_life_profiles SET cash=cash-?,updated_at=? WHERE user_id=?',(startup,base.now_iso(),user_id))
        valuation=startup*1.15
        c.execute('''INSERT INTO purple_businesses(user_id,name,business_type,cash,revenue,costs,employees,customers,reputation,marketing,valuation,created_at,updated_at)
                     VALUES(?,?,?,?,?,?,1,8,50,0,?,?,?)''',(user_id,req.name.strip(),kind,startup*.35,spec['base_revenue'],spec['base_cost'],valuation,base.now_iso(),base.now_iso()))
        c.execute('INSERT INTO purple_world_events(user_id,sim_year,sim_month,category,title,body,impact,created_at) VALUES(?,?,?,"business",?,?,?,?)',
                  (user_id,int(life['sim_year']),int(life['sim_month']),'Company launched',f'{req.name.strip()} entered the Purple Economy.',-startup,base.now_iso()))
        c.commit();c.close();return dashboard(user_id)

    @app.post('/api/world/advance-month')
    def advance_month(req:MonthAction,request:Request):
        user_id=uid(request);c=base.db();life=life_row(c,user_id)
        if not life:c.close();raise HTTPException(409,'Create your Purple Life profile first')
        life=dict(life);biz=business_row(c,user_id);biz=dict(biz) if biz else None
        expenses=float(life['monthly_housing'])+float(life['monthly_transport'])+float(life['monthly_other'])
        debt_pay=min(float(req.debt_payment),float(life['debt']),max(0,float(life['cash'])))
        life_cash=float(life['cash'])+float(life['monthly_income'])-expenses-debt_pay-float(req.save_extra)
        debt=max(0,float(life['debt'])-debt_pay)
        score=int(life['credit_score'])
        if debt_pay>0:score=min(850,score+2)
        if life_cash<0:score=max(300,score-5)
        year,month=int(life['sim_year']),int(life['sim_month'])+1
        if month>12:month=1;year+=1
        event_title='Normal month';event_body='Income and expenses stayed close to plan.';impact=0.0
        roll=random.random()
        if roll<.12:
            shock=random.choice([350,600,900,1400]);life_cash-=shock;impact=-shock;event_title='Unexpected expense';event_body=f'An unplanned ${shock:,.0f} expense hit your household budget.'
        elif roll>.90:
            bonus=random.choice([250,500,800]);life_cash+=bonus;impact=bonus;event_title='Income opportunity';event_body=f'You earned ${bonus:,.0f} from an extra simulated opportunity.'
        if biz:
            spec=BUSINESS_TYPES.get(biz['business_type'],{'base_revenue':biz['revenue'],'base_cost':biz['costs']})
            marketing=float(req.business_marketing)
            demand=random.uniform(.82,1.20)+(min(marketing,5000)/5000)*.18+(float(biz['reputation'])-50)/500
            revenue=max(0,float(spec['base_revenue'])*demand)
            costs=float(spec['base_cost'])+marketing+max(0,int(biz['employees'])-1)*2800
            profit=revenue-costs
            biz_cash=float(biz['cash'])+profit
            customers=max(0,int(round(float(biz['customers'])*random.uniform(.94,1.12)+marketing/350)))
            reputation=max(0,min(100,float(biz['reputation'])+random.uniform(-2,3)))
            valuation=max(1000,(revenue*12)*max(.35,1.1+(reputation-50)/100)+max(0,biz_cash)*.5)
            c.execute('UPDATE purple_businesses SET cash=?,revenue=?,costs=?,customers=?,reputation=?,marketing=?,valuation=?,updated_at=? WHERE id=?',
                      (biz_cash,revenue,costs,customers,reputation,marketing,valuation,base.now_iso(),biz['id']))
            if abs(profit)>2500:
                event_title='Business surge' if profit>0 else 'Business pressure'
                event_body=f"{biz['name']} produced ${profit:,.0f} in simulated monthly {'profit' if profit>0 else 'losses'}."
                impact+=profit
        c.execute('UPDATE purple_life_profiles SET age=?,cash=?,debt=?,credit_score=?,sim_month=?,sim_year=?,updated_at=? WHERE user_id=?',
                  (int(life['age'])+(1 if month==1 else 0),life_cash,debt,score,month,year,base.now_iso(),user_id))
        c.execute('INSERT INTO purple_world_events(user_id,sim_year,sim_month,category,title,body,impact,created_at) VALUES(?,?,?,?,?,?,?,?)',
                  (user_id,year,month,'economy',event_title,event_body,impact,base.now_iso()))
        c.commit();c.close();return dashboard(user_id)
