import asyncio
import json
import os
import random
import sqlite3
import hashlib
import hmac
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Set

import httpx
import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent
DB_PATH = Path(os.getenv("DATABASE_PATH", str(ROOT / "purple_paper_network.db")))
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("ALPACA_API_KEY", "")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_FEED = os.getenv("ALPACA_FEED", "iex").strip().lower() or "iex"
STARTING_CASH = float(os.getenv("STARTING_CASH", "100000"))
SLIPPAGE_BPS = float(os.getenv("SLIPPAGE_BPS", "2"))
ALPACA_STREAM_BASE = "wss://stream.data.alpaca.markets/v2"
ALPACA_DATA = "https://data.alpaca.markets/v2"
ALPACA_CRYPTO_DATA = "https://data.alpaca.markets/v1beta3/crypto/us"
ALPACA_CRYPTO_STREAM = "wss://stream.data.alpaca.markets/v1beta3/crypto/us"
ALPACA_PAPER_API = "https://paper-api.alpaca.markets"

latest_prices: Dict[str, float] = {}
latest_quotes: Dict[str, dict] = {}
subscribed_symbols: Set[str] = {"AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "SPY"}
subscribed_crypto_symbols: Set[str] = {"BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "LTC/USD", "AVAX/USD", "LINK/USD"}
clients: Dict[WebSocket, int] = {}
stream_socket = None
crypto_stream_socket = None
stream_task = None
crypto_stream_task = None
order_task = None


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def add_column(conn, table, column, definition):
    existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY CHECK (id=1),
            cash REAL NOT NULL,
            starting_cash REAL NOT NULL,
            realized_pl REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS positions (
            symbol TEXT PRIMARY KEY,
            qty REAL NOT NULL,
            avg_price REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            qty REAL NOT NULL,
            limit_price REAL,
            stop_price REAL,
            status TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            filled_at TEXT,
            fill_price REAL,
            filled_qty REAL NOT NULL DEFAULT 0,
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            qty REAL NOT NULL,
            price REAL NOT NULL,
            total REAL NOT NULL,
            realized_pl REAL NOT NULL DEFAULT 0,
            executed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            symbol TEXT,
            mood TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id=1),
            slippage_bps REAL NOT NULL DEFAULT 2,
            confirm_orders INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS coach_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS coach_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER,
            symbol TEXT,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'player',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            last_login_at TEXT
        );
        CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS user_accounts (
            user_id INTEGER PRIMARY KEY,
            cash REAL NOT NULL,
            starting_cash REAL NOT NULL,
            realized_pl REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS user_positions (
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            qty REAL NOT NULL,
            avg_price REAL NOT NULL,
            PRIMARY KEY(user_id, symbol),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS user_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            qty REAL NOT NULL,
            limit_price REAL,
            stop_price REAL,
            status TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            filled_at TEXT,
            fill_price REAL,
            filled_qty REAL NOT NULL DEFAULT 0,
            note TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS user_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            order_id INTEGER,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            qty REAL NOT NULL,
            price REAL NOT NULL,
            total REAL NOT NULL,
            realized_pl REAL NOT NULL DEFAULT 0,
            executed_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS user_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            symbol TEXT,
            mood TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS user_coach_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS user_coach_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            trade_id INTEGER,
            symbol TEXT,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """
    )
    add_column(conn, "account", "realized_pl", "REAL NOT NULL DEFAULT 0")
    add_column(conn, "orders", "stop_price", "REAL")
    add_column(conn, "orders", "filled_qty", "REAL NOT NULL DEFAULT 0")
    add_column(conn, "orders", "note", "TEXT")
    add_column(conn, "trades", "realized_pl", "REAL NOT NULL DEFAULT 0")
    if conn.execute("SELECT 1 FROM account WHERE id=1").fetchone() is None:
        conn.execute("INSERT INTO account(id,cash,starting_cash,realized_pl) VALUES(1,?,?,0)", (STARTING_CASH, STARTING_CASH))
    if conn.execute("SELECT 1 FROM settings WHERE id=1").fetchone() is None:
        conn.execute("INSERT INTO settings(id,slippage_bps,confirm_orders) VALUES(1,?,1)", (SLIPPAGE_BPS,))
    conn.commit()
    conn.close()


ROLE_LEVELS = {"player": 0, "coach": 10, "moderator": 20, "admin": 30, "owner": 40}
ROLE_LABELS = {"player":"PLAYER", "coach":"COACH", "moderator":"MODERATOR", "admin":"ADMIN", "owner":"OWNER"}
SESSION_COOKIE = "purple_session"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0").lower() in {"1","true","yes","on"}
HOSTED_MODE = os.getenv("HOSTED_MODE", "0").lower() in {"1","true","yes","on"}
APP_NAME = "Purple Paper Network"
OWNER_SETUP_CODE = os.getenv("OWNER_SETUP_CODE", "").strip()

def _password_hash(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 220_000).hex()

def _new_password(password: str):
    salt = secrets.token_bytes(16).hex()
    return salt, _password_hash(password, salt)

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def public_user(row):
    return {"id": row["id"], "username": row["username"], "role": row["role"],
            "role_label": ROLE_LABELS.get(row["role"], row["role"].upper()),
            "is_active": bool(row["is_active"]), "created_at": row["created_at"], "last_login_at": row["last_login_at"]}

def current_user_from_request(request: Request, required: bool = True):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        if required: raise HTTPException(401, "Sign in required")
        return None
    conn = db()
    row = conn.execute("""SELECT u.* FROM auth_sessions s JOIN users u ON u.id=s.user_id
                        WHERE s.token_hash=? AND s.expires_at>?""", (_token_hash(token), now_iso())).fetchone()
    conn.close()
    if not row or not row["is_active"]:
        if required: raise HTTPException(401, "Session expired or account disabled")
        return None
    return row

def require_role(request: Request, role: str):
    user = current_user_from_request(request)
    if ROLE_LEVELS.get(user["role"], -1) < ROLE_LEVELS[role]:
        raise HTTPException(403, f"{ROLE_LABELS[role].title()} access required")
    return user

def create_session(response: Response, user_id: int):
    raw = secrets.token_urlsafe(32)
    created = datetime.now(timezone.utc)
    expires = created + timedelta(days=30)
    conn = db()
    conn.execute("DELETE FROM auth_sessions WHERE expires_at<=?", (created.isoformat(),))
    conn.execute("INSERT INTO auth_sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                 (_token_hash(raw), user_id, created.isoformat(), expires.isoformat()))
    conn.commit(); conn.close()
    response.set_cookie(SESSION_COOKIE, raw, httponly=True, secure=COOKIE_SECURE, samesite="lax", max_age=30*24*3600, path="/")

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ensure_user_account(user_id: int):
    conn = db()
    row = conn.execute("SELECT * FROM user_accounts WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO user_accounts(user_id,cash,starting_cash,realized_pl,created_at) VALUES(?,?,?,?,?)",
                     (user_id, STARTING_CASH, STARTING_CASH, 0.0, now_iso()))
        conn.commit()
    conn.close()

def current_user_id(request: Request) -> int:
    user = current_user_from_request(request)
    ensure_user_account(user["id"])
    return int(user["id"])

def market_session():
    # Informational US/Eastern approximation without extra timezone dependency.
    now = datetime.now(timezone.utc)
    # DST exactness is not used for order validation; feed availability remains authoritative.
    eastern = now - timedelta(hours=4)
    weekday = eastern.weekday()
    mins = eastern.hour * 60 + eastern.minute
    if weekday >= 5:
        return {"status": "closed", "label": "Weekend", "is_open": False}
    if 240 <= mins < 570:
        return {"status": "pre", "label": "Pre-market", "is_open": False}
    if 570 <= mins < 960:
        return {"status": "open", "label": "Market open", "is_open": True}
    if 960 <= mins < 1200:
        return {"status": "after", "label": "After-hours", "is_open": False}
    return {"status": "closed", "label": "Market closed", "is_open": False}


def account_snapshot(user_id: int):
    ensure_user_account(user_id)
    conn = db()
    acct = conn.execute("SELECT * FROM user_accounts WHERE user_id=?", (user_id,)).fetchone()
    rows = conn.execute("SELECT * FROM user_positions WHERE user_id=? ORDER BY symbol", (user_id,)).fetchall()
    conn.close()
    positions = []
    market_value = 0.0
    for r in rows:
        price = latest_prices.get(r["symbol"], r["avg_price"])
        mv = r["qty"] * price
        cost = r["qty"] * r["avg_price"]
        market_value += mv
        positions.append({
            "symbol": r["symbol"], "qty": r["qty"], "avg_price": r["avg_price"],
            "price": price, "market_value": mv, "unrealized_pl": mv - cost,
            "unrealized_pl_pct": ((price / r["avg_price"]) - 1) * 100 if r["avg_price"] else 0
        })
    positions.sort(key=lambda x: x["market_value"], reverse=True)
    equity = acct["cash"] + market_value
    unrealized = sum((p["price"] - p["avg_price"]) * p["qty"] for p in positions)
    return {
        "cash": acct["cash"], "starting_cash": acct["starting_cash"], "market_value": market_value,
        "equity": equity, "total_pl": equity - acct["starting_cash"],
        "total_pl_pct": ((equity / acct["starting_cash"]) - 1) * 100 if acct["starting_cash"] else 0,
        "realized_pl": acct["realized_pl"], "unrealized_pl": unrealized,
        "positions": positions, "session": market_session()
    }


def coach_metrics(user_id: int):
    a = account_snapshot(user_id)
    conn = db()
    trades = [dict(r) for r in conn.execute("SELECT * FROM user_trades WHERE user_id=? ORDER BY id DESC LIMIT 100", (user_id,)).fetchall()]
    orders = [dict(r) for r in conn.execute("SELECT * FROM user_orders WHERE user_id=? ORDER BY id DESC LIMIT 100", (user_id,)).fetchall()]
    journal_count = conn.execute("SELECT COUNT(*) c FROM user_journal WHERE user_id=?", (user_id,)).fetchone()["c"]
    conn.close()
    sells = [t for t in trades if t["side"] == "sell"]
    wins = [t for t in sells if (t.get("realized_pl") or 0) > 0]
    losses = [t for t in sells if (t.get("realized_pl") or 0) < 0]
    gross_win = sum(t.get("realized_pl") or 0 for t in wins)
    gross_loss = abs(sum(t.get("realized_pl") or 0 for t in losses))
    win_rate = (len(wins) / len(sells) * 100) if sells else 0
    profit_factor = (gross_win / gross_loss) if gross_loss else (999 if gross_win else 0)
    concentration = 0
    biggest = None
    if a["positions"] and a["equity"]:
        biggest = max(a["positions"], key=lambda x: x["market_value"])
        concentration = biggest["market_value"] / a["equity"] * 100
    recent = trades[:10]
    recent_loss_count = sum(1 for t in recent if (t.get("realized_pl") or 0) < 0)
    advanced = sum(1 for o in orders if o["order_type"] in {"limit","stop","stop_limit"})
    risk_score = 100
    if concentration > 25: risk_score -= min(30, int((concentration-25)*1.2))
    if recent_loss_count >= 3: risk_score -= 15
    if journal_count == 0 and len(trades) >= 3: risk_score -= 10
    if len(trades) >= 15 and advanced == 0: risk_score -= 10
    risk_score = max(0, min(100, risk_score))
    return {
        "account": a, "trades": trades, "orders": orders, "journal_count": journal_count,
        "closed_trades": len(sells), "wins": len(wins), "losses": len(losses),
        "win_rate": win_rate, "profit_factor": profit_factor, "gross_win": gross_win,
        "gross_loss": gross_loss, "concentration": concentration,
        "biggest_symbol": biggest["symbol"] if biggest else None, "risk_score": risk_score,
        "advanced_orders": advanced, "recent_loss_count": recent_loss_count
    }


def trader_tier_metrics(user_id: int):
    conn = db()
    trades = [dict(r) for r in conn.execute("SELECT * FROM user_trades WHERE user_id=? ORDER BY id ASC", (user_id,)).fetchall()]
    conn.close()
    lifetime_volume = sum(abs(float(t.get("total") or 0)) for t in trades)
    tiers = [
        {"id":"starter","name":"Starter","threshold":0,"perk":"Standard XP and core coach analysis","xp_mult":1.00},
        {"id":"bronze","name":"Bronze Desk","threshold":100_000,"perk":"+5% career XP and Bronze badge frame","xp_mult":1.05},
        {"id":"silver","name":"Silver Desk","threshold":1_000_000,"perk":"+10% career XP and expanded coach diagnostics","xp_mult":1.10},
        {"id":"gold","name":"Gold Desk","threshold":10_000_000,"perk":"+15% career XP and advanced challenge cards","xp_mult":1.15},
        {"id":"platinum","name":"Platinum Desk","threshold":100_000_000,"perk":"+20% career XP and prestige badge frame","xp_mult":1.20},
        {"id":"legend","name":"Purple Institutional","threshold":1_000_000_000,"perk":"+25% career XP and institutional career title","xp_mult":1.25},
    ]
    current = tiers[0]; next_tier = None
    for t in tiers:
        if lifetime_volume >= t["threshold"]: current = t
        elif next_tier is None: next_tier = t
    progress = 100.0
    if next_tier:
        span = max(1, next_tier["threshold"] - current["threshold"])
        progress = max(0.0, min(100.0, (lifetime_volume-current["threshold"])/span*100))
    return {"lifetime_volume":lifetime_volume,"current":current,"next":next_tier,"progress":progress,"tiers":tiers}


def adaptive_coach_metrics(user_id: int):
    m = coach_metrics(user_id)
    trades = list(reversed(m["trades"]))
    totals = [abs(float(t.get("total") or 0)) for t in trades]
    avg_ticket = sum(totals)/len(totals) if totals else 0
    sell_results = [float(t.get("realized_pl") or 0) for t in trades if t.get("side")=="sell"]
    loss_streak = 0
    for x in reversed(sell_results):
        if x < 0: loss_streak += 1
        else: break
    size_escalations = 0; prev_loss = False; rolling = []
    for t in trades:
        size = abs(float(t.get("total") or 0))
        baseline = sum(rolling[-5:])/len(rolling[-5:]) if rolling[-5:] else 0
        if prev_loss and baseline and size > baseline*1.5: size_escalations += 1
        prev_loss = (t.get("side")=="sell" and float(t.get("realized_pl") or 0) < 0)
        rolling.append(size)
    symbol_volume = {}
    for t in trades: symbol_volume[t["symbol"]] = symbol_volume.get(t["symbol"],0)+abs(float(t.get("total") or 0))
    top_symbol = max(symbol_volume, key=symbol_volume.get) if symbol_volume else None
    total_volume = sum(symbol_volume.values()) or 0
    top_share = symbol_volume.get(top_symbol,0)/total_volume*100 if top_symbol and total_volume else 0
    advanced_ratio = (m["advanced_orders"]/len(m["orders"])*100) if m["orders"] else 0
    profile=[]
    if loss_streak>=3: profile.append({"kind":"warn","title":"Loss streak detected","text":f"You have {loss_streak} consecutive realized losing exits in the recent sample. Slow the next decision down and review the original invalidation rules."})
    if size_escalations: profile.append({"kind":"warn","title":"Post-loss sizing escalation","text":f"The coach detected {size_escalations} case(s) where trade size increased sharply after a realized loss. That can resemble revenge-trading behavior."})
    if top_share>50: profile.append({"kind":"warn","title":"Repeated-symbol bias","text":f"{top_symbol} represents {top_share:.1f}% of recent traded notional. Practice across different conditions so one symbol does not dominate the learning sample."})
    if advanced_ratio<20 and len(m["orders"])>=5: profile.append({"kind":"info","title":"Execution variety","text":f"Only {advanced_ratio:.0f}% of recent orders use limit/stop logic. Practice execution controls rather than relying mostly on market orders."})
    if not profile: profile.append({"kind":"good","title":"Process looks stable","text":"No major escalation, concentration, or execution-pattern warnings were detected in the recent sample. Keep journaling your reason and invalidation."})
    return {"loss_streak":loss_streak,"size_escalations":size_escalations,"average_ticket":avg_ticket,"top_symbol":top_symbol,"top_symbol_share":top_share,"advanced_ratio":advanced_ratio,"observations":profile}


def coach_reply(user_id: int, message: str):
    m = coach_metrics(user_id); q = message.lower().strip(); a=m["account"]
    notice = " Coach analysis can be wrong or incomplete; you make the final trade decision."
    if not q: return "Ask me about your risk, recent trades, concentration, win rate, losses, or how to review a setup." + notice
    if any(k in q for k in ["risk", "safe", "danger", "exposure"]):
        extra = f" Your largest position is {m['biggest_symbol']} at {m['concentration']:.1f}% of equity." if m['biggest_symbol'] else " You do not currently hold a position."
        return f"Your current practice risk score is {m['risk_score']}/100.{extra} This is a behavioral training indicator, not a prediction.{notice}"
    if any(k in q for k in ["win rate", "winning", "loss rate", "stats", "performance"]):
        if not m['closed_trades']: return "You do not have closed trades yet, so there is no meaningful win-rate sample. Close several paper positions first." + notice
        pf = "∞" if m['profit_factor'] >= 999 else f"{m['profit_factor']:.2f}"
        return f"Across {m['closed_trades']} closed paper trades, your win rate is {m['win_rate']:.1f}% with {m['wins']} wins and {m['losses']} losses. Profit factor is {pf}. Treat small samples cautiously.{notice}"
    if any(k in q for k in ["loss", "losing", "mistake", "wrong"]):
        return f"Your realized P/L is ${a['realized_pl']:,.2f}. You have {m['recent_loss_count']} realized losses among the 10 most recent fills. Review entry reason, invalidation, position size, and whether you changed the plan after entering.{notice}"
    if any(k in q for k in ["concentration", "position size", "too much", "allocation"]):
        if not m['biggest_symbol']: return "There are no current positions to analyze for concentration." + notice
        return f"{m['biggest_symbol']} is currently your largest position at {m['concentration']:.1f}% of total equity. Use the simulator to test how a single-asset move changes total portfolio P/L.{notice}"
    if any(k in q for k in ["journal", "discipline", "plan"]):
        return f"You have {m['journal_count']} journal entries for {len(m['trades'])} recent fills. Before a trade, record the setup and invalidation point; afterward, record whether you followed the plan.{notice}"
    if any(k in q for k in ["order", "stop", "limit", "slippage"]):
        return f"You have used {m['advanced_orders']} advanced paper orders. Practice market, limit, stop, and stop-limit orders in different spreads so you can see how triggers and fills differ.{notice}"
    if any(k in q for k in ["behavior", "adaptive", "revenge", "overtrade", "pattern"]):
        aco = adaptive_coach_metrics(user_id); lead = aco["observations"][0]["text"] if aco["observations"] else "No major behavioral flags are present."
        return f"Adaptive review: {lead} Average recent ticket size is ${aco['average_ticket']:,.2f}; advanced-order usage is {aco['advanced_ratio']:.0f}%.{notice}"
    if any(k in q for k in ["buy", "sell", "should i", "what stock", "recommend", "invest in"]):
        return "I can help you compare market liquidity, volatility, spread, concentration, position size, entry logic, stop logic, and your simulated history, but I will not execute the trade for you. Treat any candidate or setup analysis as research support, not certainty." + notice
    return f"Right now your simulated equity is ${a['equity']:,.2f}, total P/L is ${a['total_pl']:,.2f}, and your practice risk score is {m['risk_score']}/100. Ask me about risk, performance, concentration, losses, order execution, or journaling.{notice}"


def create_trade_review(user_id: int, trade_id: int, symbol: str, side: str, qty: float, price: float, realized: float):
    m = coach_metrics(user_id); severity='good'; title=f"{symbol} fill reviewed"
    if side == 'sell' and realized < 0:
        severity='warn'; body=f"Closed {qty:g} {'units' if '/' in symbol else 'shares'} at ${price:,.2f} for a realized paper loss of ${realized:,.2f}. Review whether the exit matched the invalidation rule you intended before entry."
    elif side == 'sell' and realized > 0:
        body=f"Closed {qty:g} {'units' if '/' in symbol else 'shares'} at ${price:,.2f} for a realized paper gain of ${realized:,.2f}. Record whether the exit followed the plan instead of judging the trade only by profit."
    else:
        severity='info'; body=f"Opened/added {qty:g} {'units' if '/' in symbol else 'shares'} at a simulated fill of ${price:,.2f}. Current largest-position concentration is {m['concentration']:.1f}%. Check size and invalidation before adding more exposure."
    conn=db(); conn.execute("INSERT INTO user_coach_reviews(user_id,trade_id,symbol,severity,title,body,created_at) VALUES(?,?,?,?,?,?,?)",(user_id,trade_id,symbol,severity,title,body,now_iso())); conn.commit(); conn.close()


async def broadcast(payload: dict, user_id: int | None = None):
    if not clients: return
    dead=[]; msg=json.dumps(payload)
    for ws, uid in list(clients.items()):
        if user_id is not None and uid != user_id: continue
        try: await ws.send_text(msg)
        except Exception: dead.append(ws)
    for ws in dead: clients.pop(ws, None)


async def broadcast_accounts():
    for uid in sorted(set(clients.values())):
        try: await broadcast({"type":"account","data":account_snapshot(uid)}, uid)
        except Exception: pass


async def fetch_crypto_snapshot(symbol: str):
    """Prime a crypto symbol from Alpaca's 24/7 crypto snapshot endpoint."""
    symbol = symbol.strip().upper()
    if not API_KEY or not SECRET_KEY:
        return None
    headers = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET_KEY}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{ALPACA_CRYPTO_DATA}/snapshots", headers=headers, params={"symbols": symbol})
        if r.status_code >= 400:
            return None
        payload = r.json()
        snapshots = payload.get("snapshots") if isinstance(payload, dict) else None
        if snapshots is None and isinstance(payload, dict):
            snapshots = payload
        data = (snapshots or {}).get(symbol) or {}
        trade = data.get("latestTrade") or data.get("latest_trade") or {}
        quote = data.get("latestQuote") or data.get("latest_quote") or {}
        price = trade.get("p")
        if price is None:
            bar = data.get("minuteBar") or data.get("minute_bar") or data.get("dailyBar") or data.get("daily_bar") or {}
            price = bar.get("c")
        if price is not None:
            latest_prices[symbol] = float(price)
        if quote:
            latest_quotes[symbol] = {
                "bid": quote.get("bp"), "ask": quote.get("ap"),
                "bid_size": quote.get("bs"), "ask_size": quote.get("as"),
                "timestamp": quote.get("t"), "asset_type": "crypto"
            }
        return {"price": latest_prices.get(symbol), "quote": latest_quotes.get(symbol)}
    except Exception:
        return None


async def fetch_latest_snapshot(symbol: str):
    """Prime the simulator with the latest stock or crypto quote/trade."""
    symbol = symbol.strip().upper()
    if "/" in symbol:
        return await fetch_crypto_snapshot(symbol)
    if not API_KEY or not SECRET_KEY:
        return None
    headers = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET_KEY}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{ALPACA_DATA}/stocks/{symbol}/snapshot", headers=headers, params={"feed": ALPACA_FEED})
        if r.status_code >= 400:
            return None
        data = r.json()
        trade = data.get("latestTrade") or {}
        quote = data.get("latestQuote") or {}
        price = trade.get("p")
        if price is None:
            bar = data.get("minuteBar") or data.get("dailyBar") or {}
            price = bar.get("c")
        if price is not None:
            latest_prices[symbol] = float(price)
        if quote:
            latest_quotes[symbol] = {
                "bid": quote.get("bp"), "ask": quote.get("ap"),
                "bid_size": quote.get("bs"), "ask_size": quote.get("as"),
                "timestamp": quote.get("t"), "asset_type": "stock"
            }
        return {"price": latest_prices.get(symbol), "quote": latest_quotes.get(symbol)}
    except Exception:
        return None


async def subscribe_new_symbols(symbols):
    global stream_socket
    if not stream_socket:
        return
    try:
        await stream_socket.send(json.dumps({"action": "subscribe", "trades": list(symbols), "quotes": list(symbols)}))
    except Exception:
        pass


async def subscribe_new_crypto_symbols(symbols):
    global crypto_stream_socket
    if not crypto_stream_socket:
        return
    try:
        await crypto_stream_socket.send(json.dumps({"action": "subscribe", "trades": list(symbols), "quotes": list(symbols), "bars": list(symbols)}))
    except Exception:
        pass


async def crypto_stream_loop():
    global crypto_stream_socket
    while True:
        if not API_KEY or not SECRET_KEY:
            await broadcast({"type": "crypto_status", "connected": False, "message": "Add market-data keys for live crypto"})
            await asyncio.sleep(5)
            continue
        try:
            async with websockets.connect(ALPACA_CRYPTO_STREAM, ping_interval=20, ping_timeout=20) as ws:
                crypto_stream_socket = ws
                await ws.send(json.dumps({"action": "auth", "key": API_KEY, "secret": SECRET_KEY}))
                auth = json.loads(await ws.recv())
                if any(x.get("T") == "error" for x in auth):
                    raise RuntimeError(str(auth))
                syms = sorted(subscribed_crypto_symbols)
                await ws.send(json.dumps({"action": "subscribe", "trades": syms, "quotes": syms, "bars": syms}))
                await broadcast({"type": "crypto_status", "connected": True, "message": "Crypto live • 24/7"})
                async for raw in ws:
                    for item in json.loads(raw):
                        typ = item.get("T")
                        symbol = item.get("S")
                        if typ == "t" and symbol:
                            price = float(item["p"])
                            latest_prices[symbol] = price
                            await broadcast({"type": "trade", "asset_type": "crypto", "symbol": symbol, "price": price, "size": item.get("s"), "timestamp": item.get("t")})
                            await broadcast_accounts()
                        elif typ == "q" and symbol:
                            latest_quotes[symbol] = {"bid": item.get("bp"), "ask": item.get("ap"), "bid_size": item.get("bs"), "ask_size": item.get("as"), "timestamp": item.get("t"), "asset_type": "crypto"}
                            await broadcast({"type": "quote", "asset_type": "crypto", "symbol": symbol, **latest_quotes[symbol]})
                        elif typ == "b" and symbol:
                            await broadcast({"type": "crypto_bar", "symbol": symbol, "bar": {"t": item.get("t"), "o": item.get("o"), "h": item.get("h"), "l": item.get("l"), "c": item.get("c"), "v": item.get("v", 0)}})
        except Exception as exc:
            crypto_stream_socket = None
            await broadcast({"type": "crypto_status", "connected": False, "message": f"Crypto reconnecting: {str(exc)[:70]}"})
            await asyncio.sleep(3)


async def market_stream_loop():
    global stream_socket
    while True:
        if not API_KEY or not SECRET_KEY:
            await broadcast({"type": "status", "connected": False, "message": "Add market-data keys for live prices"})
            await asyncio.sleep(5)
            continue
        try:
            stream_url = f"{ALPACA_STREAM_BASE}/{ALPACA_FEED}"
            async with websockets.connect(stream_url, ping_interval=20, ping_timeout=20) as ws:
                stream_socket = ws
                await ws.send(json.dumps({"action": "auth", "key": API_KEY, "secret": SECRET_KEY}))
                auth = json.loads(await ws.recv())
                if any(x.get("T") == "error" for x in auth):
                    raise RuntimeError(str(auth))
                await ws.send(json.dumps({"action": "subscribe", "trades": sorted(subscribed_symbols), "quotes": sorted(subscribed_symbols)}))
                await broadcast({"type": "status", "connected": True, "message": f"Live {ALPACA_FEED.upper()} stream"})
                async for raw in ws:
                    for item in json.loads(raw):
                        typ = item.get("T")
                        symbol = item.get("S")
                        if typ == "t" and symbol:
                            price = float(item["p"])
                            latest_prices[symbol] = price
                            await broadcast({"type": "trade", "asset_type": "stock", "symbol": symbol, "price": price, "size": item.get("s"), "timestamp": item.get("t")})
                            await broadcast_accounts()
                        elif typ == "q" and symbol:
                            latest_quotes[symbol] = {"bid": item.get("bp"), "ask": item.get("ap"), "bid_size": item.get("bs"), "ask_size": item.get("as"), "timestamp": item.get("t")}
                            await broadcast({"type": "quote", "asset_type": "stock", "symbol": symbol, **latest_quotes[symbol]})
        except Exception as exc:
            stream_socket = None
            await broadcast({"type": "status", "connected": False, "message": f"Reconnecting: {str(exc)[:80]}"})
            await asyncio.sleep(3)


def simulated_fill_price(symbol: str, side: str, reference: float):
    q = latest_quotes.get(symbol) or {}
    if side == "buy":
        base = float(q.get("ask") or reference)
        slip = base * (SLIPPAGE_BPS / 10000)
        return base + slip
    base = float(q.get("bid") or reference)
    slip = base * (SLIPPAGE_BPS / 10000)
    return max(0.0001, base - slip)


def execute_fill(user_id: int, order_id: int, symbol: str, side: str, qty: float, price: float):
    ensure_user_account(user_id)
    conn = db()
    acct = conn.execute("SELECT * FROM user_accounts WHERE user_id=?", (user_id,)).fetchone()
    pos = conn.execute("SELECT * FROM user_positions WHERE user_id=? AND symbol=?", (user_id, symbol)).fetchone()
    total = qty * price
    realized = 0.0
    if side == "buy":
        if total > acct["cash"] + 1e-9:
            conn.execute("UPDATE user_orders SET status='rejected',note='Insufficient fake cash' WHERE id=? AND user_id=?", (order_id,user_id))
            conn.commit(); conn.close(); return False, "Insufficient fake cash"
        old_qty = pos["qty"] if pos else 0; old_avg = pos["avg_price"] if pos else 0
        new_qty = old_qty + qty; new_avg = ((old_qty * old_avg) + (qty * price)) / new_qty
        conn.execute("UPDATE user_accounts SET cash=cash-? WHERE user_id=?", (total,user_id))
        conn.execute("INSERT INTO user_positions(user_id,symbol,qty,avg_price) VALUES(?,?,?,?) ON CONFLICT(user_id,symbol) DO UPDATE SET qty=excluded.qty, avg_price=excluded.avg_price", (user_id,symbol,new_qty,new_avg))
    else:
        if not pos or qty > pos["qty"] + 1e-9:
            conn.execute("UPDATE user_orders SET status='rejected',note='Not enough shares/units to sell' WHERE id=? AND user_id=?", (order_id,user_id))
            conn.commit(); conn.close(); return False, "Not enough shares/units to sell"
        realized = (price - pos["avg_price"]) * qty; new_qty = pos["qty"] - qty
        conn.execute("UPDATE user_accounts SET cash=cash+?, realized_pl=realized_pl+? WHERE user_id=?", (total,realized,user_id))
        if new_qty <= 1e-9: conn.execute("DELETE FROM user_positions WHERE user_id=? AND symbol=?", (user_id,symbol))
        else: conn.execute("UPDATE user_positions SET qty=? WHERE user_id=? AND symbol=?", (new_qty,user_id,symbol))
    ts=now_iso()
    conn.execute("UPDATE user_orders SET status='filled',filled_at=?,fill_price=?,filled_qty=? WHERE id=? AND user_id=?", (ts,price,qty,order_id,user_id))
    cur=conn.execute("INSERT INTO user_trades(user_id,order_id,symbol,side,qty,price,total,realized_pl,executed_at) VALUES(?,?,?,?,?,?,?,?,?)", (user_id,order_id,symbol,side,qty,price,total,realized,ts))
    trade_id=cur.lastrowid; conn.commit(); conn.close()
    create_trade_review(user_id, trade_id, symbol, side, qty, price, realized)
    return True, "filled"


def should_trigger(order, price):
    typ, side = order["order_type"], order["side"]
    limit_price, stop_price = order["limit_price"], order["stop_price"]
    if typ == "limit":
        return (side == "buy" and price <= limit_price) or (side == "sell" and price >= limit_price)
    if typ in {"stop", "stop_limit"}:
        hit_stop = (side == "buy" and price >= stop_price) or (side == "sell" and price <= stop_price)
        if not hit_stop:
            return False
        if typ == "stop":
            return True
        return (side == "buy" and price <= limit_price) or (side == "sell" and price >= limit_price)
    return False


async def pending_order_loop():
    while True:
        conn=db(); rows=conn.execute("SELECT * FROM user_orders WHERE status='open'").fetchall(); conn.close()
        for r in rows:
            p=latest_prices.get(r["symbol"])
            if p is None or not should_trigger(r,p): continue
            fill=simulated_fill_price(r["symbol"],r["side"],p)
            if r["order_type"] in {"limit","stop_limit"} and r["limit_price"] is not None:
                fill=min(fill,r["limit_price"]) if r["side"]=="buy" else max(fill,r["limit_price"])
            ok,msg=execute_fill(r["user_id"],r["id"],r["symbol"],r["side"],r["qty"],fill)
            await broadcast({"type":"order_update","order_id":r["id"],"status":"filled" if ok else "rejected","message":msg}, r["user_id"])
            await broadcast({"type":"account","data":account_snapshot(r["user_id"])}, r["user_id"])
        await asyncio.sleep(0.2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global stream_task, crypto_stream_task, order_task
    init_db()
    stream_task = asyncio.create_task(market_stream_loop())
    crypto_stream_task = asyncio.create_task(crypto_stream_loop())
    order_task = asyncio.create_task(pending_order_loop())
    yield
    for task in (stream_task, crypto_stream_task, order_task):
        if task: task.cancel()


app = FastAPI(title="Purple Paper V8 Network", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    setup_code: str | None = Field(default=None, max_length=256)

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)

class RoleUpdateRequest(BaseModel):
    role: str

class ActiveUpdateRequest(BaseModel):
    is_active: bool

class SubscribeRequest(BaseModel):
    symbol: str
    asset_type: str | None = None


class OrderRequest(BaseModel):
    symbol: str
    side: str
    asset_type: str | None = None
    order_type: str = "market"
    qty: float = Field(gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)


class CoachChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class JournalRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=4000)
    symbol: str | None = Field(default=None, max_length=12)
    mood: str | None = Field(default="neutral", max_length=30)


class MarketDataConfigRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=256)
    secret_key: str = Field(min_length=1, max_length=256)
    feed: str = Field(default="iex", max_length=16)


def masked_key(value: str):
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "•" * min(16, len(value)-8) + value[-4:]


def save_market_env(api_key: str, secret_key: str, feed: str):
    env_path = ROOT / ".env"
    existing = {}
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in raw and not raw.lstrip().startswith("#"):
                k,v = raw.split("=",1); existing[k.strip()] = v.strip()
    existing["ALPACA_API_KEY"] = api_key
    existing["ALPACA_SECRET_KEY"] = secret_key
    existing["ALPACA_FEED"] = feed
    existing.setdefault("STARTING_CASH", str(STARTING_CASH))
    existing.setdefault("SLIPPAGE_BPS", str(SLIPPAGE_BPS))
    tmp = env_path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(f"{k}={v}" for k,v in existing.items()) + "\n", encoding="utf-8")
    tmp.replace(env_path)


@app.get("/api/auth/status")
def auth_status(request: Request):
    conn = db(); count = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]; conn.close()
    user = current_user_from_request(request, required=False)
    return {"needs_owner_setup": count == 0, "owner_setup_code_required": bool(count == 0 and HOSTED_MODE and OWNER_SETUP_CODE), "authenticated": bool(user), "user": public_user(user) if user else None}

@app.post("/api/auth/signup")
def signup(req: SignupRequest, response: Response):
    username = req.username.strip()
    if not username.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Username may use letters, numbers, underscores, and hyphens")
    conn = db()
    if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        conn.close(); raise HTTPException(409, "Username already exists")
    count = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    if count == 0 and HOSTED_MODE and OWNER_SETUP_CODE:
        supplied = (req.setup_code or "").strip()
        if not hmac.compare_digest(supplied, OWNER_SETUP_CODE):
            conn.close(); raise HTTPException(403, "Owner setup code is required for the first hosted account")
    role = "owner" if count == 0 else "player"
    salt, ph = _new_password(req.password)
    cur = conn.execute("INSERT INTO users(username,password_hash,password_salt,role,is_active,created_at) VALUES(?,?,?,?,1,?)",
                       (username, ph, salt, role, now_iso()))
    uid = cur.lastrowid; conn.commit(); row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone(); conn.close()
    ensure_user_account(uid)
    create_session(response, uid)
    return {"ok": True, "user": public_user(row), "owner_created": role == "owner"}

@app.post("/api/auth/login")
def login(req: LoginRequest, response: Response):
    conn = db(); row = conn.execute("SELECT * FROM users WHERE username=?", (req.username.strip(),)).fetchone()
    if not row or not hmac.compare_digest(row["password_hash"], _password_hash(req.password, row["password_salt"])):
        conn.close(); raise HTTPException(401, "Invalid username or password")
    if not row["is_active"]: conn.close(); raise HTTPException(403, "This account is disabled")
    conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (now_iso(), row["id"])); conn.commit(); row=conn.execute("SELECT * FROM users WHERE id=?",(row["id"],)).fetchone(); conn.close()
    create_session(response, row["id"]); return {"ok": True, "user": public_user(row)}

@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        conn=db(); conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (_token_hash(token),)); conn.commit(); conn.close()
    response.delete_cookie(SESSION_COOKIE, path="/"); return {"ok": True}

@app.get("/api/auth/me")
def auth_me(request: Request):
    return {"user": public_user(current_user_from_request(request))}

@app.get("/api/admin/users")
def admin_users(request: Request):
    require_role(request, "moderator")
    conn=db(); rows=conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall(); conn.close()
    return {"users": [public_user(r) for r in rows], "roles": ["player","coach","moderator","admin","owner"]}

@app.post("/api/admin/users/{user_id}/role")
def admin_set_role(user_id: int, req: RoleUpdateRequest, request: Request):
    actor = require_role(request, "admin")
    role=req.role.strip().lower()
    if role not in ROLE_LEVELS: raise HTTPException(400, "Unknown role")
    conn=db(); target=conn.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone()
    if not target: conn.close(); raise HTTPException(404,"User not found")
    if target["role"] == "owner" and actor["role"] != "owner": conn.close(); raise HTTPException(403,"Only the Owner can modify an Owner account")
    if role == "owner" and actor["role"] != "owner": conn.close(); raise HTTPException(403,"Only the Owner can grant Owner rank")
    if actor["id"] == user_id and actor["role"] == "owner" and role != "owner": conn.close(); raise HTTPException(400,"The primary Owner cannot demote their own account")
    conn.execute("UPDATE users SET role=? WHERE id=?",(role,user_id)); conn.commit(); row=conn.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone(); conn.close()
    return {"ok":True,"user":public_user(row)}

@app.post("/api/admin/users/{user_id}/active")
def admin_set_active(user_id: int, req: ActiveUpdateRequest, request: Request):
    actor=require_role(request,"moderator")
    conn=db(); target=conn.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone()
    if not target: conn.close(); raise HTTPException(404,"User not found")
    if target["role"] in {"admin","owner"} and actor["role"] != "owner": conn.close(); raise HTTPException(403,"Owner access required for that account")
    if actor["id"] == user_id and not req.is_active: conn.close(); raise HTTPException(400,"You cannot disable your own account")
    conn.execute("UPDATE users SET is_active=? WHERE id=?",(1 if req.is_active else 0,user_id))
    if not req.is_active: conn.execute("DELETE FROM auth_sessions WHERE user_id=?",(user_id,))
    conn.commit(); row=conn.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone(); conn.close(); return {"ok":True,"user":public_user(row)}

@app.get("/")
async def home():
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control":"no-store, max-age=0"})


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(ROOT / "static" / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/service-worker.js")
async def sw():
    return FileResponse(ROOT / "static" / "service-worker.js", media_type="application/javascript", headers={"Cache-Control":"no-store, max-age=0"})


@app.get("/api/market-data/config")
async def market_data_config(request: Request):
    user=current_user_from_request(request)
    is_owner=user["role"] == "owner"
    return {
        "configured": bool(API_KEY and SECRET_KEY),
        "api_key_masked": masked_key(API_KEY) if is_owner else "",
        "secret_key_masked": masked_key(SECRET_KEY) if is_owner else "",
        "can_configure": is_owner,
        "feed": ALPACA_FEED,
        "connected": bool(stream_socket),
        "provider": "Alpaca",
    }


@app.post("/api/market-data/config")
async def update_market_data_config(req: MarketDataConfigRequest, request: Request):
    require_role(request, "owner")
    global API_KEY, SECRET_KEY, ALPACA_FEED, stream_socket, crypto_stream_socket, stream_task, crypto_stream_task
    api_key = req.api_key.strip()
    secret = req.secret_key.strip()
    feed = req.feed.strip().lower() or "iex"
    if feed not in {"iex", "sip"}:
        raise HTTPException(400, "Feed must be IEX or SIP")
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{ALPACA_DATA}/stocks/AAPL/snapshot", headers=headers, params={"feed": feed})
    except Exception as exc:
        raise HTTPException(502, f"Could not reach Alpaca: {str(exc)[:120]}")
    if r.status_code >= 400:
        detail = "Credentials or feed access were rejected"
        try:
            payload = r.json(); detail = payload.get("message") or detail
        except Exception:
            pass
        raise HTTPException(r.status_code if r.status_code < 500 else 502, detail)
    data = r.json()
    trade = data.get("latestTrade") or {}
    quote = data.get("latestQuote") or {}
    API_KEY, SECRET_KEY, ALPACA_FEED = api_key, secret, feed
    save_market_env(API_KEY, SECRET_KEY, ALPACA_FEED)
    # Prime AAPL immediately from the successful validation response.
    price = trade.get("p") or (data.get("minuteBar") or {}).get("c") or (data.get("dailyBar") or {}).get("c")
    if price is not None:
        latest_prices["AAPL"] = float(price)
    if quote:
        latest_quotes["AAPL"] = {"bid": quote.get("bp"), "ask": quote.get("ap"), "bid_size": quote.get("bs"), "ask_size": quote.get("as"), "timestamp": quote.get("t")}
    old_socket = stream_socket
    stream_socket = None
    if old_socket:
        try:
            await old_socket.close()
        except Exception:
            pass
    if stream_task and not stream_task.done():
        stream_task.cancel()
        try:
            await stream_task
        except BaseException:
            pass
    stream_task = asyncio.create_task(market_stream_loop())
    if crypto_stream_task and not crypto_stream_task.done():
        crypto_stream_task.cancel()
        try:
            await crypto_stream_task
        except BaseException:
            pass
    crypto_stream_socket = None
    crypto_stream_task = asyncio.create_task(crypto_stream_loop())
    for symbol in sorted(subscribed_symbols):
        await fetch_latest_snapshot(symbol)
    for symbol in sorted(subscribed_crypto_symbols):
        await fetch_crypto_snapshot(symbol)
    await broadcast({"type":"snapshot","prices":latest_prices,"quotes":latest_quotes})
    await broadcast({"type":"status","connected":False,"message":"Credentials saved • connecting live feed…"})
    return {"ok": True, "configured": True, "feed": ALPACA_FEED, "provider": "Alpaca", "test_symbol": "AAPL", "test_price": latest_prices.get("AAPL"), "message": "Credentials verified and saved. Live stream is reconnecting."}


@app.post("/api/market-data/test")
async def test_market_data(request: Request):
    current_user_from_request(request)
    if not API_KEY or not SECRET_KEY:
        raise HTTPException(400, "Market-data credentials are not configured")
    snap = await fetch_latest_snapshot("AAPL")
    if not snap or snap.get("price") is None:
        raise HTTPException(502, "Alpaca responded but no AAPL price was available")
    return {"ok": True, "symbol": "AAPL", "price": snap.get("price"), "quote": snap.get("quote"), "feed": ALPACA_FEED, "connected": bool(stream_socket)}


@app.get("/api/account")
async def get_account(request: Request):
    return account_snapshot(current_user_id(request))


@app.get("/api/orders")
async def get_orders(request: Request):
    uid=current_user_id(request); conn=db(); rows=conn.execute("SELECT * FROM user_orders WHERE user_id=? ORDER BY id DESC LIMIT 200",(uid,)).fetchall(); conn.close(); return [dict(r) for r in rows]


@app.get("/api/trades")
async def get_trades(request: Request):
    uid=current_user_id(request); conn=db(); rows=conn.execute("SELECT * FROM user_trades WHERE user_id=? ORDER BY id DESC LIMIT 200",(uid,)).fetchall(); conn.close(); return [dict(r) for r in rows]


@app.get("/api/journal")
async def get_journal(request: Request):
    uid=current_user_id(request); conn=db(); rows=conn.execute("SELECT * FROM user_journal WHERE user_id=? ORDER BY id DESC LIMIT 100",(uid,)).fetchall(); conn.close(); return [dict(r) for r in rows]


@app.post("/api/journal")
async def add_journal(req: JournalRequest, request: Request):
    uid=current_user_id(request); conn=db(); cur=conn.execute("INSERT INTO user_journal(user_id,title,body,symbol,mood,created_at) VALUES(?,?,?,?,?,?)",(uid,req.title.strip(),req.body.strip(),(req.symbol or "").upper() or None,req.mood,now_iso())); conn.commit(); conn.close(); return {"ok":True,"id":cur.lastrowid}


@app.delete("/api/journal/{entry_id}")
async def delete_journal(entry_id: int, request: Request):
    uid=current_user_id(request); conn=db(); cur=conn.execute("DELETE FROM user_journal WHERE id=? AND user_id=?",(entry_id,uid)); conn.commit(); conn.close();
    if not cur.rowcount: raise HTTPException(404,"Journal entry not found")
    return {"ok":True}


@app.get("/api/game/tier")
async def game_tier(request: Request):
    return trader_tier_metrics(current_user_id(request))


@app.get("/api/coach/adaptive")
async def coach_adaptive(request: Request):
    return adaptive_coach_metrics(current_user_id(request))


@app.get("/api/practice-credit-packs")
async def practice_credit_packs(request: Request):
    current_user_from_request(request)
    return {"redeemable":False,"payment_enabled":False,"packs":[
        {"id":"spark","label":"Spark Pack","display_price":"$1","practice_cash":10000},
        {"id":"desk","label":"Desk Pack","display_price":"$10","practice_cash":100000},
        {"id":"pro","label":"Pro Pack","display_price":"$100","practice_cash":1000000},
        {"id":"institutional","label":"Institutional Pack","display_price":"$1,000","practice_cash":10000000}
    ],"note":"Practice-credit storefront preview. No real payment or cash-out is connected; credits cannot be redeemed for money."}


@app.get("/api/coach")
async def coach(request: Request):
    uid=current_user_id(request); m=coach_metrics(uid); a=m["account"]; insights=[]
    if not m["trades"]: insights.append({"kind":"info","title":"Build a sample","text":"Place a few paper trades so the coach can analyze execution, concentration, outcomes, and discipline."})
    if m["biggest_symbol"] and m["concentration"]>25: insights.append({"kind":"warn","title":"Concentration","text":f"{m['biggest_symbol']} is {m['concentration']:.1f}% of total equity. Use the simulator to see how one-position drawdowns affect the whole account."})
    if m["closed_trades"]: insights.append({"kind":"good" if m["win_rate"]>=50 else "info","title":"Closed-trade sample","text":f"{m['closed_trades']} closed trades • {m['win_rate']:.1f}% win rate • realized P/L ${a['realized_pl']:,.2f}. Keep process quality separate from outcome."})
    if m["journal_count"] < max(1,len(m["trades"])//3) and len(m["trades"])>=3: insights.append({"kind":"warn","title":"Journal gap","text":f"{m['journal_count']} journal entries for {len(m['trades'])} recent fills. Documenting entry logic and invalidation gives the coach more context."})
    if m["advanced_orders"]==0 and len(m["orders"])>=3: insights.append({"kind":"info","title":"Execution practice","text":"All recent orders are basic. Practice limit, stop, and stop-limit orders to study spread, triggers, and simulated slippage."})
    if len(insights)<4: insights.append({"kind":"good","title":"Risk score","text":f"Practice risk score: {m['risk_score']}/100. Behavioral training signal only; Purple Coach can make mistakes."})
    return insights[:4]


@app.get("/api/coach/summary")
async def coach_summary(request: Request):
    m=coach_metrics(current_user_id(request)); return {k:v for k,v in m.items() if k not in {"account","trades","orders"}} | {"equity":m["account"]["equity"],"total_pl":m["account"]["total_pl"],"realized_pl":m["account"]["realized_pl"]}


@app.get("/api/coach/history")
async def coach_history(request: Request):
    uid=current_user_id(request); conn=db(); msgs=[dict(r) for r in conn.execute("SELECT * FROM user_coach_messages WHERE user_id=? ORDER BY id DESC LIMIT 40",(uid,)).fetchall()][::-1]; reviews=[dict(r) for r in conn.execute("SELECT * FROM user_coach_reviews WHERE user_id=? ORDER BY id DESC LIMIT 12",(uid,)).fetchall()]; conn.close(); return {"messages":msgs,"reviews":reviews}


@app.post("/api/coach/chat")
async def coach_chat(req: CoachChatRequest, request: Request):
    uid=current_user_id(request); message=req.message.strip(); answer=coach_reply(uid,message); conn=db(); ts=now_iso(); conn.execute("INSERT INTO user_coach_messages(user_id,role,body,created_at) VALUES(?, 'user',?,?)",(uid,message,ts)); conn.execute("INSERT INTO user_coach_messages(user_id,role,body,created_at) VALUES(?, 'coach',?,?)",(uid,answer,now_iso())); conn.commit(); conn.close(); return {"reply":answer,"notice":"Purple Coach can make mistakes. You make the final trade decision."}


@app.post("/api/coach/clear")
async def coach_clear(request: Request):
    uid=current_user_id(request); conn=db(); conn.execute("DELETE FROM user_coach_messages WHERE user_id=?",(uid,)); conn.commit(); conn.close(); return {"ok":True}


@app.get("/api/session-report")
async def session_report(request: Request):
    uid=current_user_id(request); m=coach_metrics(uid); a=m["account"]; conn=db(); recent=[dict(r) for r in conn.execute("SELECT * FROM user_trades WHERE user_id=? ORDER BY id DESC LIMIT 20",(uid,)).fetchall()]; conn.close()
    filled=len(recent); sells=[t for t in recent if t["side"]=="sell"]; realized_recent=sum(float(t.get("realized_pl") or 0) for t in recent); max_position=m["concentration"]; grade=100
    if max_position>25: grade-=min(30,int((max_position-25)*1.2))
    if filled>=3 and m["journal_count"]==0: grade-=15
    if m["recent_loss_count"]>=3: grade-=15
    if len(m["orders"])>=4 and m["advanced_orders"]==0: grade-=10
    grade=max(0,min(100,grade)); label="Elite discipline" if grade>=90 else "Controlled" if grade>=75 else "Developing" if grade>=60 else "High-risk habits"
    return {"grade":grade,"label":label,"equity":a["equity"],"total_pl":a["total_pl"],"total_pl_pct":a["total_pl_pct"],"realized_recent":realized_recent,"fills":filled,"closed":len(sells),"win_rate":m["win_rate"],"concentration":max_position,"journal_count":m["journal_count"],"advanced_orders":m["advanced_orders"],"feed_configured":bool(API_KEY and SECRET_KEY),"feed":f"Alpaca {ALPACA_FEED.upper()}" if API_KEY and SECRET_KEY else "No live key configured","session":market_session()}


@app.get("/api/network/status")
async def network_status(request: Request):
    user=current_user_from_request(request); conn=db(); user_count=conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]; conn.close()
    return {"hosted_mode":HOSTED_MODE,"database_path":str(DB_PATH),"user_count":user_count,"account_scope":"server-backed per-user","current_user":public_user(user),"coach_notice":"Purple Coach can make mistakes or miss context. You make the final trade decision."}


@app.get("/api/feed-health")
async def feed_health(request: Request):
    current_user_from_request(request); newest=None; symbol=None
    for sym,q in latest_quotes.items():
        ts=q.get("timestamp")
        if ts and (newest is None or ts>newest): newest,symbol=ts,sym
    return {"configured":bool(API_KEY and SECRET_KEY),"stream_connected":bool(stream_socket),"crypto_stream_connected":bool(crypto_stream_socket),"feed":ALPACA_FEED.upper(),"crypto_feed":"Alpaca Crypto US","latest_quote_timestamp":newest,"latest_quote_symbol":symbol,"subscribed":sorted(subscribed_symbols),"crypto_subscribed":sorted(subscribed_crypto_symbols)}


@app.post("/api/subscribe")
async def subscribe(req: SubscribeRequest, request: Request):
    current_user_from_request(request); symbol=req.symbol.strip().upper(); asset_type=(req.asset_type or ("crypto" if "/" in symbol else "stock")).lower()
    if asset_type=="crypto":
        if not symbol or len(symbol)>24 or "/" not in symbol or not symbol.replace("/","").replace("-","").isalnum(): raise HTTPException(400,"Invalid crypto pair")
        is_new=symbol not in subscribed_crypto_symbols; subscribed_crypto_symbols.add(symbol); await fetch_crypto_snapshot(symbol)
        if is_new: await subscribe_new_crypto_symbols([symbol])
    else:
        if not symbol or len(symbol)>12 or not symbol.replace(".","").replace("-","").isalnum(): raise HTTPException(400,"Invalid ticker")
        is_new=symbol not in subscribed_symbols; subscribed_symbols.add(symbol); await fetch_latest_snapshot(symbol)
        if is_new: await subscribe_new_symbols([symbol])
    return {"symbol":symbol,"asset_type":asset_type,"price":latest_prices.get(symbol),"quote":latest_quotes.get(symbol)}


@app.post("/api/order")
async def place_order(req: OrderRequest, request: Request):
    uid=current_user_id(request); symbol=req.symbol.strip().upper(); side=req.side.lower(); order_type=req.order_type.lower()
    if side not in {"buy","sell"}: raise HTTPException(400,"Side must be buy or sell")
    if order_type not in {"market","limit","stop","stop_limit"}: raise HTTPException(400,"Unsupported order type")
    if order_type in {"limit","stop_limit"} and req.limit_price is None: raise HTTPException(400,"Limit price required")
    if order_type in {"stop","stop_limit"} and req.stop_price is None: raise HTTPException(400,"Stop price required")
    asset_type=(req.asset_type or ("crypto" if "/" in symbol else "stock")).lower()
    if asset_type=="crypto": subscribed_crypto_symbols.add(symbol); await fetch_crypto_snapshot(symbol); await subscribe_new_crypto_symbols([symbol])
    else: subscribed_symbols.add(symbol); await fetch_latest_snapshot(symbol); await subscribe_new_symbols([symbol])
    p=latest_prices.get(symbol); conn=db(); cur=conn.execute("INSERT INTO user_orders(user_id,symbol,side,order_type,qty,limit_price,stop_price,status,submitted_at) VALUES(?,?,?,?,?,?,?,'open',?)",(uid,symbol,side,order_type,req.qty,req.limit_price,req.stop_price,now_iso())); order_id=cur.lastrowid; conn.commit(); conn.close()
    if order_type=="market":
        if p is None:
            conn=db(); conn.execute("UPDATE user_orders SET status='rejected',note='No live price available' WHERE id=? AND user_id=?",(order_id,uid)); conn.commit(); conn.close(); raise HTTPException(409,"No live price yet. Select the asset and wait for the live market feed.")
        fill=simulated_fill_price(symbol,side,p); ok,msg=execute_fill(uid,order_id,symbol,side,req.qty,fill)
        if not ok: raise HTTPException(400,msg)
    await broadcast({"type":"account","data":account_snapshot(uid)},uid); await broadcast({"type":"order_update","order_id":order_id,"status":"filled" if order_type=="market" else "open"},uid); return {"ok":True,"order_id":order_id}


@app.post("/api/cancel/{order_id}")
async def cancel_order(order_id: int, request: Request):
    uid=current_user_id(request); conn=db(); r=conn.execute("SELECT * FROM user_orders WHERE id=? AND user_id=?",(order_id,uid)).fetchone()
    if not r: conn.close(); raise HTTPException(404,"Order not found")
    if r["status"]!="open": conn.close(); raise HTTPException(400,"Only open orders can be cancelled")
    conn.execute("UPDATE user_orders SET status='cancelled' WHERE id=? AND user_id=?",(order_id,uid)); conn.commit(); conn.close(); return {"ok":True}


@app.post("/api/reset")
async def reset_account(request: Request):
    uid=current_user_id(request); conn=db()
    for table in ["user_positions","user_orders","user_trades","user_journal","user_coach_messages","user_coach_reviews"]: conn.execute(f"DELETE FROM {table} WHERE user_id=?",(uid,))
    conn.execute("UPDATE user_accounts SET cash=?,starting_cash=?,realized_pl=0 WHERE user_id=?",(STARTING_CASH,STARTING_CASH,uid)); conn.commit(); conn.close(); await broadcast({"type":"account","data":account_snapshot(uid)},uid); return {"ok":True}


@app.get("/api/crypto/assets")
async def crypto_assets(request: Request):
    current_user_from_request(request)
    fallback = [
        {"symbol":"BTC/USD","name":"Bitcoin","base":"BTC"},
        {"symbol":"ETH/USD","name":"Ethereum","base":"ETH"},
        {"symbol":"SOL/USD","name":"Solana","base":"SOL"},
        {"symbol":"DOGE/USD","name":"Dogecoin","base":"DOGE"},
        {"symbol":"LTC/USD","name":"Litecoin","base":"LTC"},
        {"symbol":"AVAX/USD","name":"Avalanche","base":"AVAX"},
        {"symbol":"LINK/USD","name":"Chainlink","base":"LINK"},
    ]
    if not API_KEY or not SECRET_KEY:
        return {"assets": fallback, "dynamic": False}
    headers = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET_KEY}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{ALPACA_PAPER_API}/v2/assets", headers=headers, params={"status":"active", "asset_class":"crypto"})
        if r.status_code >= 400:
            return {"assets": fallback, "dynamic": False}
        rows = r.json() if isinstance(r.json(), list) else []
        assets=[]
        seen=set()
        for item in rows:
            sym=(item.get("symbol") or "").upper()
            if not sym or "/" not in sym or not sym.endswith("/USD") or sym in seen:
                continue
            seen.add(sym)
            assets.append({"symbol":sym,"name":item.get("name") or sym.split("/")[0],"base":sym.split("/")[0],"tradable":bool(item.get("tradable", True))})
        assets.sort(key=lambda x: (0 if x["base"] in {"BTC","ETH","SOL","XRP","DOGE"} else 1, x["base"]))
        return {"assets": assets or fallback, "dynamic": bool(assets)}
    except Exception:
        return {"assets": fallback, "dynamic": False}


@app.get("/api/crypto/bars")
async def crypto_bars(request: Request, symbol: str, timeframe: str = "1Min", limit: int = 180):
    current_user_from_request(request)
    symbol = symbol.strip().upper(); limit = max(20, min(limit, 500))
    if not API_KEY or not SECRET_KEY:
        return {"bars": []}
    headers = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET_KEY}
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=10)
    params = {"symbols": symbol, "timeframe": timeframe, "start": start.isoformat(), "end": end.isoformat(), "limit": limit, "sort":"asc"}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{ALPACA_CRYPTO_DATA}/bars", headers=headers, params=params)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    data = r.json()
    bars_map = data.get("bars") if isinstance(data, dict) else {}
    return {"bars": (bars_map or {}).get(symbol, [])}


@app.get("/api/bars/{symbol}")
async def bars(symbol: str, request: Request, timeframe: str = "1Min", limit: int = 180):
    current_user_from_request(request)
    symbol = symbol.upper(); limit = max(20, min(limit, 500))
    if not API_KEY or not SECRET_KEY: return {"bars": []}
    headers = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET_KEY}
    end = datetime.now(timezone.utc); start = end - timedelta(days=10)
    params = {"timeframe": timeframe, "start": start.isoformat(), "end": end.isoformat(), "limit": limit, "feed": "iex", "adjustment": "raw", "sort": "asc"}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{ALPACA_DATA}/stocks/{symbol}/bars", headers=headers, params=params)
    if r.status_code >= 400: raise HTTPException(r.status_code, r.text)
    return r.json()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    token=ws.cookies.get(SESSION_COOKIE)
    if not token:
        await ws.close(code=4401); return
    conn=db(); row=conn.execute("SELECT u.* FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?",(_token_hash(token),now_iso())).fetchone(); conn.close()
    if not row or not row["is_active"]:
        await ws.close(code=4401); return
    uid=int(row["id"]); ensure_user_account(uid)
    await ws.accept(); clients[ws]=uid
    await ws.send_text(json.dumps({"type":"account","data":account_snapshot(uid)}))
    await ws.send_text(json.dumps({"type":"snapshot","prices":latest_prices,"quotes":latest_quotes}))
    await ws.send_text(json.dumps({"type":"status","connected":bool(stream_socket),"message":f"Live {ALPACA_FEED.upper()} stream" if stream_socket else "Waiting for market-data connection"}))
    await ws.send_text(json.dumps({"type":"crypto_status","connected":bool(crypto_stream_socket),"message":"Crypto live • 24/7" if crypto_stream_socket else "Waiting for crypto stream"}))
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect:
        clients.pop(ws,None)

