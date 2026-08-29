import math
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field


def register(app, base):
    SYMBOL='PPC'
    NAME='Purple Coin'
    HARD_CAP=10000
    START_PRICE=1.00
    MIN_PRICE=0.05
    MAX_PRICE=1000.0
    DAILY_MINT_CAP=15
    MIN_NOTIONAL=50.0
    MIN_HOLD_SECONDS=60

    def ensure():
        c=base.db();c.executescript('''
        CREATE TABLE IF NOT EXISTS purple_coin_market(
          id INTEGER PRIMARY KEY CHECK(id=1), price REAL NOT NULL, prev_price REAL NOT NULL,
          volume REAL NOT NULL DEFAULT 0, buy_pressure REAL NOT NULL DEFAULT 0,
          sell_pressure REAL NOT NULL DEFAULT 0, exchange_reserve INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS purple_coin_price_history(
          id INTEGER PRIMARY KEY AUTOINCREMENT, price REAL NOT NULL, volume REAL NOT NULL,
          reason TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS purple_coin_qualifying_trades(
          user_id INTEGER NOT NULL, trade_id INTEGER NOT NULL, symbol TEXT NOT NULL,
          notional REAL NOT NULL, qualified INTEGER NOT NULL, reason TEXT NOT NULL,
          created_at TEXT NOT NULL, PRIMARY KEY(user_id,trade_id));
        CREATE TABLE IF NOT EXISTS purple_coin_daily_rewards(
          user_id INTEGER NOT NULL, day TEXT NOT NULL, amount INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(user_id,day));
        CREATE TABLE IF NOT EXISTS purple_coin_flags(
          id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,kind TEXT NOT NULL,
          detail TEXT NOT NULL,created_at TEXT NOT NULL);
        ''')
        try:c.execute('ALTER TABLE purple_coin_market ADD COLUMN exchange_reserve INTEGER NOT NULL DEFAULT 0')
        except Exception:pass
        c.execute('INSERT OR IGNORE INTO purple_coin_market(id,price,prev_price,exchange_reserve,updated_at) VALUES(1,?,?,0,?)',(START_PRICE,START_PRICE,base.now_iso()))
        s=c.execute('SELECT minted FROM purple_currency_supply WHERE id=1').fetchone()
        if s and int(s['minted'] or 0)>HARD_CAP:
            c.close();raise RuntimeError('Existing PPC minted supply exceeds the 10,000 PPC V9.9 cap; migration is required before startup.')
        c.execute('UPDATE purple_currency_supply SET max_supply=? WHERE id=1',(HARD_CAP,));c.commit();c.close()

    def market(c=None):
        own=c is None;c=c or base.db();r=c.execute('SELECT * FROM purple_coin_market WHERE id=1').fetchone();out=dict(r)
        if own:c.close()
        return out

    def day(): return datetime.now(timezone.utc).date().isoformat()

    def classify_trade(c,uid,t):
        tid=int(t['id']);old=c.execute('SELECT * FROM purple_coin_qualifying_trades WHERE user_id=? AND trade_id=?',(uid,tid)).fetchone()
        if old:return bool(old['qualified'])
        notional=abs(float(t['total'] or 0));sym=t['symbol'];side=t['side'].lower();qualified=True;reason='meaningful trade'
        if notional<MIN_NOTIONAL:qualified=False;reason='notional below anti-farm minimum'
        recent=c.execute('SELECT symbol,side,total,executed_at FROM user_trades WHERE user_id=? AND id<? ORDER BY id DESC LIMIT 8',(uid,tid)).fetchall();same=[x for x in recent if x['symbol']==sym]
        if len(same)>=5:qualified=False;reason='rapid repeated-symbol churn'
        if same and str(same[0]['side']).lower()!=side:
            try:
                a=datetime.fromisoformat(str(same[0]['executed_at']).replace('Z','+00:00'));b=datetime.fromisoformat(str(t['executed_at']).replace('Z','+00:00'))
                if (b-a).total_seconds()<MIN_HOLD_SECONDS:qualified=False;reason='round trip too fast to earn'
            except Exception:pass
        c.execute('INSERT OR IGNORE INTO purple_coin_qualifying_trades(user_id,trade_id,symbol,notional,qualified,reason,created_at) VALUES(?,?,?,?,?,?,?)',(uid,tid,sym,notional,1 if qualified else 0,reason,base.now_iso()))
        if not qualified:c.execute('INSERT INTO purple_coin_flags(user_id,kind,detail,created_at) VALUES(?,?,?,?)',(uid,'ANTI_FARM',f'{sym}: {reason}',base.now_iso()))
        return qualified

    def meaningful_count(c,uid):
        rows=c.execute('SELECT * FROM user_trades WHERE user_id=? ORDER BY id',(uid,)).fetchall();return sum(1 for t in rows if classify_trade(c,uid,t))

    def sync(uid):
        ensure();c=base.db()
        try:
            c.execute('BEGIN IMMEDIATE');c.execute('INSERT OR IGNORE INTO user_purple_currency(user_id) VALUES(?)',(uid,));w=c.execute('SELECT * FROM user_purple_currency WHERE user_id=?',(uid,)).fetchone();q=meaningful_count(c,uid);level=min(100,q//5);last=int(w['highest_rewarded_level'] or 0);s=c.execute('SELECT * FROM purple_currency_supply WHERE id=1').fetchone();remaining=max(0,HARD_CAP-int(s['minted']));dr=c.execute('SELECT amount FROM purple_coin_daily_rewards WHERE user_id=? AND day=?',(uid,day())).fetchone();daily=int(dr['amount']) if dr else 0;minted=0;to=last
            for lv in range(last+1,level+1):
                reward=min(lv,100,remaining-minted,DAILY_MINT_CAP-daily-minted)
                if reward<=0:break
                try:c.execute('INSERT INTO purple_currency_ledger(user_id,delta,reason,level,trade_count,created_at) VALUES(?,?,?,?,?,?)',(uid,reward,'MEANINGFUL_LEVEL_REWARD',lv,q,base.now_iso()))
                except Exception:continue
                minted+=reward;to=lv
            if minted:
                c.execute('UPDATE user_purple_currency SET balance=balance+?,lifetime_earned=lifetime_earned+?,highest_rewarded_level=? WHERE user_id=?',(minted,minted,to,uid));c.execute('UPDATE purple_currency_supply SET minted=minted+? WHERE id=1',(minted,));c.execute('INSERT INTO purple_coin_daily_rewards(user_id,day,amount) VALUES(?,?,?) ON CONFLICT(user_id,day) DO UPDATE SET amount=amount+excluded.amount',(uid,day(),minted))
            c.commit()
        except Exception:c.rollback();raise
        finally:c.close()
        return status(uid)

    def status(uid):
        ensure();c=base.db();c.execute('INSERT OR IGNORE INTO user_purple_currency(user_id) VALUES(?)',(uid,));c.commit();w=c.execute('SELECT * FROM user_purple_currency WHERE user_id=?',(uid,)).fetchone();s=c.execute('SELECT * FROM purple_currency_supply WHERE id=1').fetchone();m=market(c);q=meaningful_count(c,uid);daily=c.execute('SELECT amount FROM purple_coin_daily_rewards WHERE user_id=? AND day=?',(uid,day())).fetchone();hist=[dict(x) for x in c.execute('SELECT price,volume,reason,created_at FROM purple_coin_price_history ORDER BY id DESC LIMIT 60').fetchall()];flags=c.execute('SELECT COUNT(*) n FROM purple_coin_flags WHERE user_id=?',(uid,)).fetchone()['n'];wallets=int(c.execute('SELECT COALESCE(SUM(balance),0) n FROM user_purple_currency').fetchone()['n']);c.commit();c.close();reserve=int(m.get('exchange_reserve',0));circ=wallets+reserve;cap=float(m['price'])*circ
        return {'name':NAME,'symbol':SYMBOL,'simulation_only':True,'wallet':int(w['balance']),'market':{'price':round(float(m['price']),4),'previous':round(float(m['prev_price']),4),'change_pct':round((float(m['price'])/float(m['prev_price'])-1)*100,2) if float(m['prev_price']) else 0,'market_cap':round(cap,2),'volume':round(float(m['volume']),2),'exchange_reserve':reserve},'supply':{'hard_cap':HARD_CAP,'minted':int(s['minted']),'circulating':circ,'burned':int(s['burned']),'remaining':max(0,HARD_CAP-int(s['minted']))},'earning':{'meaningful_trades':q,'level':min(100,q//5),'daily_earned':int(daily['amount']) if daily else 0,'daily_cap':DAILY_MINT_CAP,'anti_farm_flags':int(flags),'rules':['10,000 PPC absolute in-app cap','minimum $50 simulated notional','rapid same-symbol churn does not qualify','sub-60-second round trips do not qualify','one level reward per level','15 PPC daily mint ceiling per user']},'history':hist,'real_money_value':False}

    class Order(BaseModel): side:str=Field(pattern='^(buy|sell)$');amount:int=Field(ge=1,le=1000)

    @app.get('/api/economy/purple-coin')
    def get_coin(request:Request):return sync(base.current_user_id(request))

    @app.post('/api/economy/purple-coin/trade')
    def trade_coin(req:Order,request:Request):
        uid=base.current_user_id(request);sync(uid);ensure();c=base.db()
        try:
            c.execute('BEGIN IMMEDIATE');m=market(c);price=float(m['price']);qty=int(req.amount);notional=price*qty;c.execute('INSERT OR IGNORE INTO user_purple_currency(user_id) VALUES(?)',(uid,));w=c.execute('SELECT * FROM user_purple_currency WHERE user_id=?',(uid,)).fetchone();acct=c.execute('SELECT cash FROM user_accounts WHERE user_id=?',(uid,)).fetchone();reserve=int(m.get('exchange_reserve',0))
            if req.side=='buy':
                if reserve<qty:raise HTTPException(409,'Not enough PPC is currently offered in the exchange reserve. PPC enters the market through earned rewards and player sells.')
                if not acct or float(acct['cash'])<notional:raise HTTPException(409,'Not enough simulated cash')
                c.execute('UPDATE user_accounts SET cash=cash-? WHERE user_id=?',(notional,uid));c.execute('UPDATE user_purple_currency SET balance=balance+? WHERE user_id=?',(qty,uid));c.execute('UPDATE purple_coin_market SET exchange_reserve=exchange_reserve-? WHERE id=1',(qty,));pressure=qty
            else:
                if int(w['balance'])<qty:raise HTTPException(409,'Not enough Purple Coin')
                c.execute('UPDATE user_purple_currency SET balance=balance-? WHERE user_id=?',(qty,uid));c.execute('UPDATE user_accounts SET cash=cash+? WHERE user_id=?',(notional,uid));c.execute('UPDATE purple_coin_market SET exchange_reserve=exchange_reserve+? WHERE id=1',(qty,));pressure=-qty
            minted=max(1,int(c.execute('SELECT minted FROM purple_currency_supply WHERE id=1').fetchone()['minted']));impact=max(-.08,min(.08,pressure/max(100,minted)*.12));new=max(MIN_PRICE,min(MAX_PRICE,price*(1+impact)));c.execute('UPDATE purple_coin_market SET prev_price=price,price=?,volume=volume+?,buy_pressure=buy_pressure+?,sell_pressure=sell_pressure+?,updated_at=? WHERE id=1',(new,notional,qty if req.side=='buy' else 0,qty if req.side=='sell' else 0,base.now_iso()));c.execute('INSERT INTO purple_coin_price_history(price,volume,reason,created_at) VALUES(?,?,?,?)',(new,notional,req.side.upper(),base.now_iso()));c.execute('INSERT INTO purple_currency_ledger(user_id,delta,reason,level,trade_count,created_at) VALUES(?,?,?,?,?,?)',(uid,qty if req.side=='buy' else -qty,'SIM_MARKET_'+req.side.upper(),None,None,base.now_iso()));c.commit()
        except HTTPException:c.rollback();raise
        except Exception:c.rollback();raise
        finally:c.close()
        return {'ok':True,'coin':status(uid),'account':base.account_snapshot(uid),'note':'Purple Coin market price and market cap are simulated in-app values, not real-world crypto prices.'}

    base.v94_coin_sync=sync
