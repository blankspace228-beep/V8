import math
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field


def register(app, base):
    CURRENCY='Purple Credit'
    SYMBOL='PC'
    MAX_SUPPLY=10000
    CASH_PER_CREDIT=250.0
    TRADES_PER_LEVEL=5
    MAX_LEVEL=100
    MIN_TRADE_NOTIONAL=25.0
    STARTER_GRANT=1000.0

    def ensure():
        conn=base.db()
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS purple_currency_supply(
          id INTEGER PRIMARY KEY CHECK(id=1), max_supply INTEGER NOT NULL,
          minted INTEGER NOT NULL DEFAULT 0, burned INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS user_purple_currency(
          user_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0,
          lifetime_earned INTEGER NOT NULL DEFAULT 0, lifetime_burned INTEGER NOT NULL DEFAULT 0,
          highest_rewarded_level INTEGER NOT NULL DEFAULT 0,
          starter_grant_claimed INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS purple_currency_ledger(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          delta INTEGER NOT NULL, reason TEXT NOT NULL, level INTEGER,
          trade_count INTEGER, created_at TEXT NOT NULL,
          UNIQUE(user_id, reason, level));
        ''')
        conn.execute('INSERT OR IGNORE INTO purple_currency_supply(id,max_supply,minted,burned) VALUES(1,?,0,0)',(MAX_SUPPLY,));s=conn.execute('SELECT minted FROM purple_currency_supply WHERE id=1').fetchone()
        if s and int(s['minted'] or 0)>MAX_SUPPLY:conn.close();raise RuntimeError('Existing Purple Coin supply exceeds the 10,000 PPC cap; migration required.')
        conn.execute('UPDATE purple_currency_supply SET max_supply=? WHERE id=1',(MAX_SUPPLY,));conn.commit();conn.close()

    def qualifying_trades(conn,uid):
        r=conn.execute('SELECT COUNT(*) c FROM user_trades WHERE user_id=? AND ABS(total)>=?',(uid,MIN_TRADE_NOTIONAL)).fetchone();return int(r['c'] or 0)

    def level_for(trades): return min(MAX_LEVEL,trades//TRADES_PER_LEVEL)
    def reward_for(level): return max(0,min(level,MAX_LEVEL))

    def sync(uid):
        ensure();conn=base.db()
        try:
            conn.execute('BEGIN IMMEDIATE');conn.execute('INSERT OR IGNORE INTO user_purple_currency(user_id) VALUES(?)',(uid,));wallet=conn.execute('SELECT * FROM user_purple_currency WHERE user_id=?',(uid,)).fetchone();trades=qualifying_trades(conn,uid);level=level_for(trades);last=int(wallet['highest_rewarded_level'] or 0);supply=conn.execute('SELECT * FROM purple_currency_supply WHERE id=1').fetchone();remaining=max(0,MAX_SUPPLY-int(supply['minted']));minted_now=0;rewarded_to=last
            for lv in range(last+1,level+1):
                reward=min(reward_for(lv),remaining-minted_now)
                if reward<=0:break
                try:conn.execute('INSERT INTO purple_currency_ledger(user_id,delta,reason,level,trade_count,created_at) VALUES(?,?,?,?,?,?)',(uid,reward,'LEVEL_REWARD',lv,trades,base.now_iso()))
                except Exception:continue
                minted_now+=reward;rewarded_to=lv
            if minted_now:
                conn.execute('UPDATE user_purple_currency SET balance=balance+?,lifetime_earned=lifetime_earned+?,highest_rewarded_level=? WHERE user_id=?',(minted_now,minted_now,rewarded_to,uid));conn.execute('UPDATE purple_currency_supply SET minted=minted+? WHERE id=1',(minted_now,))
            conn.commit()
        except Exception:conn.rollback();raise
        finally:conn.close()
        return status(uid)

    def status(uid):
        ensure();conn=base.db();conn.execute('INSERT OR IGNORE INTO user_purple_currency(user_id) VALUES(?)',(uid,));conn.commit();w=conn.execute('SELECT * FROM user_purple_currency WHERE user_id=?',(uid,)).fetchone();s=conn.execute('SELECT * FROM purple_currency_supply WHERE id=1').fetchone();trades=qualifying_trades(conn,uid);level=level_for(trades);recent=[dict(x) for x in conn.execute('SELECT delta,reason,level,trade_count,created_at FROM purple_currency_ledger WHERE user_id=? ORDER BY id DESC LIMIT 12',(uid,)).fetchall()];conn.close();circulating=int(s['minted'])-int(s['burned'])
        return {'currency':CURRENCY,'symbol':SYMBOL,'balance':int(w['balance']),'level':level,'qualifying_trades':trades,'trades_to_next_level':0 if level>=MAX_LEVEL else TRADES_PER_LEVEL-(trades%TRADES_PER_LEVEL),'next_level_reward':0 if level>=MAX_LEVEL else reward_for(level+1),'highest_rewarded_level':int(w['highest_rewarded_level']),'supply':{'hard_cap':MAX_SUPPLY,'minted_ever':int(s['minted']),'burned':int(s['burned']),'circulating':circulating,'unminted':max(0,MAX_SUPPLY-int(s['minted']))},'exchange':{'fake_cash_per_credit':CASH_PER_CREDIT,'redeemable_for_real_money':False},'starter_grant_available':not bool(w['starter_grant_claimed']),'recent_ledger':recent}

    class ExchangeReq(BaseModel): amount:int=Field(ge=1,le=10000)

    @app.get('/api/economy/purple-credit')
    def get_credit(request:Request):uid=base.current_user_id(request);return sync(uid)

    @app.post('/api/economy/purple-credit/exchange')
    def exchange(req:ExchangeReq,request:Request):
        uid=base.current_user_id(request);ensure();conn=base.db()
        try:
            conn.execute('BEGIN IMMEDIATE');conn.execute('INSERT OR IGNORE INTO user_purple_currency(user_id) VALUES(?)',(uid,));w=conn.execute('SELECT * FROM user_purple_currency WHERE user_id=?',(uid,)).fetchone()
            if int(w['balance'])<req.amount:raise HTTPException(409,'Not enough Purple Credits')
            fake=req.amount*CASH_PER_CREDIT;conn.execute('UPDATE user_purple_currency SET balance=balance-?,lifetime_burned=lifetime_burned+? WHERE user_id=?',(req.amount,req.amount,uid));conn.execute('UPDATE purple_currency_supply SET burned=burned+? WHERE id=1',(req.amount,));conn.execute('UPDATE user_accounts SET cash=cash+? WHERE user_id=?',(fake,uid));conn.execute('INSERT INTO purple_currency_ledger(user_id,delta,reason,level,trade_count,created_at) VALUES(?,?,?,?,?,?)',(uid,-req.amount,'FAKE_CASH_EXCHANGE',None,qualifying_trades(conn,uid),base.now_iso()));conn.commit()
        except HTTPException:conn.rollback();raise
        except Exception:conn.rollback();raise
        finally:conn.close()
        return {'ok':True,'fake_cash_added':fake,'wallet':status(uid),'account':base.account_snapshot(uid),'note':'Purple Credits convert only to Purple Paper simulated cash. They have no real-money cash-out value.'}

    @app.post('/api/economy/starter-grant')
    def starter_grant(request:Request):
        uid=base.current_user_id(request);ensure();conn=base.db()
        try:
            conn.execute('BEGIN IMMEDIATE');conn.execute('INSERT OR IGNORE INTO user_purple_currency(user_id) VALUES(?)',(uid,));w=conn.execute('SELECT * FROM user_purple_currency WHERE user_id=?',(uid,)).fetchone();acct=conn.execute('SELECT cash FROM user_accounts WHERE user_id=?',(uid,)).fetchone()
            if w['starter_grant_claimed']:raise HTTPException(409,'Starter practice grant already claimed')
            if acct and float(acct['cash'])>0:raise HTTPException(409,'Starter grant is only for zero-cash accounts')
            conn.execute('UPDATE user_accounts SET cash=cash+? WHERE user_id=?',(STARTER_GRANT,uid));conn.execute('UPDATE user_purple_currency SET starter_grant_claimed=1 WHERE user_id=?',(uid,));conn.commit()
        except HTTPException:conn.rollback();raise
        except Exception:conn.rollback();raise
        finally:conn.close()
        return {'ok':True,'fake_cash_added':STARTER_GRANT,'account':base.account_snapshot(uid),'note':'One-time simulated starter capital. It does not mint Purple Credits.'}

    base.v93_currency_sync=sync
