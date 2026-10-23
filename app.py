import os
import sqlite3
import time
import uuid
from datetime import datetime, date, time as dt_time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# ============================================================
# NSE PAPER TRADER — SIMULATION ONLY. NO BROKER ORDER API.
# ============================================================
APP_TITLE = "NSE Multi-Strategy Paper Trader"
DB_PATH = os.getenv("PAPER_DB_PATH", "paper_trades.db")
IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)

# Yahoo Finance symbols. This is a research watchlist, not an
# endorsement or a guarantee of liquidity/tradability.
WATCHLIST = {
    "RELIANCE": "RELIANCE.NS",
    "HDFCBANK": "HDFCBANK.NS",
    "ICICIBANK": "ICICIBANK.NS",
    "SBIN": "SBIN.NS",
    "INFY": "INFY.NS",
    "TCS": "TCS.NS",
    "ITC": "ITC.NS",
    "TATAMOTORS": "TMPV.NS",
    "TATASTEEL": "TATASTEEL.NS",
    "AXISBANK": "AXISBANK.NS",
    "BHARTIARTL": "BHARTIARTL.NS",
    "WIPRO": "WIPRO.NS",
    "ONGC": "ONGC.NS",
    "NTPC": "NTPC.NS",
    "POWERGRID": "POWERGRID.NS",
    "COALINDIA": "COALINDIA.NS",
    "NHPC": "NHPC.NS",
    "IDEA": "IDEA.NS",
    "IOB": "IOB.NS",
    "IRFC": "IRFC.NS",
    "TATAPOWER": "TATAPOWER.NS",
    "BEL": "BEL.NS",
    "PFC": "PFC.NS",
    "RECLTD": "RECLTD.NS",
    "CANBK": "CANBK.NS",
}

st.set_page_config(page_title=APP_TITLE, page_icon="📈", layout="wide")


def now_ist():
    return datetime.now(IST)


def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                yahoo_symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                status TEXT NOT NULL,
                signal_time TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                entry_price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                stop_price REAL NOT NULL,
                target_price REAL NOT NULL,
                score REAL NOT NULL,
                exit_time TEXT,
                exit_price REAL,
                exit_reason TEXT,
                gross_pnl REAL,
                estimated_costs REAL,
                net_pnl REAL,
                last_price REAL,
                last_checked TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT,
                timestamp TEXT NOT NULL,
                event TEXT NOT NULL,
                details TEXT
            )
        """)
        conn.commit()


def log_event(conn, trade_id, event, details=""):
    conn.execute(
        "INSERT INTO events (trade_id, timestamp, event, details) VALUES (?, ?, ?, ?)",
        (trade_id, now_ist().isoformat(timespec="seconds"), event, str(details)[:1000]),
    )


def telegram_config():
    try:
        token = str(st.secrets.get("TELEGRAM_BOT_TOKEN", "")).strip()
        chat_id = str(st.secrets.get("TELEGRAM_CHAT_ID", "")).strip()
        return token, chat_id
    except Exception:
        return "", ""


def send_telegram(message):
    token, chat_id = telegram_config()
    if not token or not chat_id:
        return False, "Telegram not configured"
    try:
        import requests
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            return False, "Telegram API did not confirm delivery"
        return True, "sent"
    except Exception as exc:
        return False, str(exc)[:180]


def safe_float(value, default=np.nan):
    try:
        result = float(value)
        return result if np.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def normalize_yf_frame(df):
    """Flatten recent yfinance MultiIndex columns and normalize OHLCV names."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        # yf.download(single ticker) may return a MultiIndex in newer versions.
        out.columns = [str(col[0]) for col in out.columns]
    out.columns = [str(c).title() for c in out.columns]
    needed = ["Open", "High", "Low", "Close", "Volume"]
    if not all(c in out.columns for c in needed):
        return pd.DataFrame()
    out = out[needed].copy()
    for col in needed:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=needed)
    out = out[(out["Close"] > 0) & (out["High"] > 0) & (out["Low"] > 0)]
    out = out[out["Volume"] >= 0]
    return out.sort_index()


@st.cache_data(ttl=45, show_spinner=False)
def fetch_data(yahoo_symbol, interval):
    try:
        if interval == "5m":
            raw = yf.download(
                yahoo_symbol, period="5d", interval="5m", auto_adjust=True,
                progress=False, threads=False, prepost=False, timeout=12,
            )
        else:
            raw = yf.download(
                yahoo_symbol, period="6mo", interval="1d", auto_adjust=True,
                progress=False, threads=False, prepost=False, timeout=12,
            )
        return normalize_yf_frame(raw)
    except Exception:
        return pd.DataFrame()


def indicators(df):
    out = df.copy()
    out["EMA5"] = out["Close"].ewm(span=5, adjust=False).mean()
    out["EMA9"] = out["Close"].ewm(span=9, adjust=False).mean()
    out["EMA13"] = out["Close"].ewm(span=13, adjust=False).mean()
    out["EMA21"] = out["Close"].ewm(span=21, adjust=False).mean()
    delta = out["Close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, np.nan)
    out["RSI"] = 100 - (100 / (1 + rs))
    out["VolAvg20"] = out["Volume"].rolling(20, min_periods=10).mean()
    out["High20"] = out["High"].rolling(20, min_periods=10).max().shift(1)
    out["Low20"] = out["Low"].rolling(20, min_periods=10).min().shift(1)
    return out


def last_timestamp_is_recent(df, interval):
    if df.empty:
        return False
    stamp = df.index[-1]
    try:
        ts = pd.Timestamp(stamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize(IST)
        else:
            ts = ts.tz_convert(IST)
        age = now_ist() - ts.to_pydatetime()
        # Intraday quotes older than 25 minutes are not used to open positions
        # during market hours. Daily data is judged by trading date instead.
        if interval == "5m":
            if now_ist().weekday() >= 5:
                return True
            return age <= timedelta(minutes=25) or now_ist().time() < MARKET_OPEN
        return ts.date() >= (now_ist().date() - timedelta(days=4))
    except Exception:
        return False


def score_swing(df):
    if len(df) < 35:
        return None
    x = indicators(df).dropna(subset=["EMA9", "EMA21", "RSI"])
    if len(x) < 3:
        return None
    cur, prev = x.iloc[-1], x.iloc[-2]
    close = safe_float(cur["Close"])
    if not np.isfinite(close) or close <= 0:
        return None
    bullish = cur["EMA9"] > cur["EMA21"] and close > cur["EMA21"]
    cross = prev["EMA9"] <= prev["EMA21"] and cur["EMA9"] > cur["EMA21"]
    rsi = safe_float(cur["RSI"], 50)
    vol_avg = safe_float(cur["VolAvg20"], 0)
    volume_ok = vol_avg > 0 and safe_float(cur["Volume"], 0) >= vol_avg * 1.15
    dip_bounce = 35 <= rsi <= 52 and close > safe_float(prev["Close"], close)
    if not (bullish or dip_bounce):
        return None
    score = 45
    score += 20 if cross else 0
    score += 12 if bullish else 0
    score += 10 if volume_ok else 0
    score += 8 if 45 <= rsi <= 65 else 0
    score += 5 if dip_bounce else 0
    score = min(score, 100)
    stop_pct = 0.025
    target_pct = 0.05
    if rsi >= 72:
        return None
    return {
        "strategy": "Swing",
        "price": close,
        "score": float(score),
        "stop_pct": stop_pct,
        "target_pct": target_pct,
        "rsi": rsi,
        "volume_ok": volume_ok,
        "signal_time": str(x.index[-1]),
        "reason": "EMA trend / momentum",
    }


def score_intraday(df):
    if len(df) < 35:
        return None
    x = indicators(df).dropna(subset=["EMA5", "EMA13", "RSI"])
    if len(x) < 3:
        return None
    cur, prev = x.iloc[-1], x.iloc[-2]
    close = safe_float(cur["Close"])
    if not np.isfinite(close) or close <= 0:
        return None
    rsi = safe_float(cur["RSI"], 50)
    bullish = cur["EMA5"] > cur["EMA13"] and close > cur["EMA5"]
    cross = prev["EMA5"] <= prev["EMA13"] and cur["EMA5"] > cur["EMA13"]
    vol_avg = safe_float(cur["VolAvg20"], 0)
    volume_ok = vol_avg > 0 and safe_float(cur["Volume"], 0) >= vol_avg * 1.25
    breakout = safe_float(cur["High20"], np.nan)
    breakout_ok = np.isfinite(breakout) and close > breakout
    if not (bullish and (cross or volume_ok or breakout_ok) and 42 <= rsi <= 72):
        return None
    score = 48 + (18 if cross else 0) + (14 if volume_ok else 0) + (12 if breakout_ok else 0)
    score += 8 if 50 <= rsi <= 65 else 0
    return {
        "strategy": "Intraday",
        "price": close,
        "score": float(min(score, 100)),
        "stop_pct": 0.012,
        "target_pct": 0.025,
        "rsi": rsi,
        "volume_ok": volume_ok,
        "signal_time": str(x.index[-1]),
        "reason": "EMA momentum / volume confirmation",
    }


def scan_market():
    candidates = []
    errors = []
    progress = st.progress(0, text="Scanning watchlist…")
    total = len(WATCHLIST)
    for i, (symbol, yahoo_symbol) in enumerate(WATCHLIST.items(), start=1):
        daily = fetch_data(yahoo_symbol, "1d")
        if not daily.empty:
            signal = score_swing(daily)
            if signal:
                candidates.append({**signal, "symbol": symbol, "yahoo_symbol": yahoo_symbol, "data_interval": "1d"})
        intraday = fetch_data(yahoo_symbol, "5m")
        if not intraday.empty and last_timestamp_is_recent(intraday, "5m"):
            # Only create intraday entries during the regular market session.
            local_now = now_ist()
            if local_now.weekday() < 5 and MARKET_OPEN <= local_now.time() <= MARKET_CLOSE:
                signal = score_intraday(intraday)
                if signal:
                    candidates.append({**signal, "symbol": symbol, "yahoo_symbol": yahoo_symbol, "data_interval": "5m"})
        if daily.empty and intraday.empty:
            errors.append(symbol)
        progress.progress(i / total, text=f"Scanned {i}/{total}: {symbol}")
    progress.empty()
    if candidates:
        result = pd.DataFrame(candidates)
        result = result.sort_values(["score", "strategy"], ascending=[False, True]).reset_index(drop=True)
    else:
        result = pd.DataFrame()
    return result, errors


def estimate_costs(entry, exit_price, qty):
    # Approximation only; not a broker contract note or tax calculation.
    turnover = max(0.0, entry * qty) + max(0.0, exit_price * qty)
    brokerage = min(20.0, entry * qty * 0.0003) + min(20.0, exit_price * qty * 0.0003)
    exchange_and_tax_estimate = turnover * 0.0012
    slippage_estimate = turnover * 0.001
    return brokerage + exchange_and_tax_estimate + slippage_estimate


def available_capital(budget, conn):
    row = conn.execute("SELECT COALESCE(SUM(entry_price * quantity), 0) AS used FROM trades WHERE status='OPEN'").fetchone()
    used = float(row["used"] or 0)
    return max(0.0, float(budget) - used)


def open_trade(candidate, budget, risk_pct, min_score, conn, alerts_enabled):
    price = float(candidate["price"])
    score = float(candidate["score"])
    if score < min_score or price <= 0:
        return False, "No candidate passed the score threshold."
    available = available_capital(budget, conn)
    risk_cash = budget * risk_pct / 100.0
    stop_price = round(price * (1 - float(candidate["stop_pct"])), 2)
    target_price = round(price * (1 + float(candidate["target_pct"])), 2)
    risk_per_share = price - stop_price
    if available < price or risk_per_share <= 0:
        return False, "Insufficient available budget for one share."
    qty_by_cash = int(available // price)
    qty_by_risk = int(risk_cash // risk_per_share) if risk_per_share > 0 else 0
    qty = min(qty_by_cash, qty_by_risk)
    if qty < 1:
        return False, "Risk limit is too small to take even one share; no trade opened."
    trade_id = str(uuid.uuid4())[:8].upper()
    stamp = now_ist().isoformat(timespec="seconds")
    conn.execute("""
        INSERT INTO trades (
            trade_id, symbol, yahoo_symbol, strategy, status, signal_time,
            entry_time, entry_price, quantity, stop_price, target_price,
            score, last_price, last_checked
        ) VALUES (?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade_id, candidate["symbol"], candidate["yahoo_symbol"], candidate["strategy"],
        str(candidate["signal_time"]), stamp, price, qty, stop_price, target_price,
        score, price, stamp,
    ))
    log_event(conn, trade_id, "PAPER_ENTRY", f"{candidate['strategy']} {candidate['symbol']} qty={qty} price={price}")
    conn.commit()
    if alerts_enabled:
        send_telegram(
            f"🟡 PAPER ENTRY\n{candidate['symbol']} ({candidate['strategy']})\n"
            f"Qty: {qty} | Entry: ₹{price:.2f}\nStop: ₹{stop_price:.2f} | Target: ₹{target_price:.2f}\n"
            f"Score: {score:.0f}/100\nSIMULATION ONLY"
        )
    return True, f"Paper position opened: {qty} share(s) of {candidate['symbol']}."


def close_trade(conn, trade, exit_price, reason, alerts_enabled):
    entry = float(trade["entry_price"])
    qty = int(trade["quantity"])
    exit_price = max(0.01, float(exit_price))
    gross = (exit_price - entry) * qty
    costs = estimate_costs(entry, exit_price, qty)
    net = gross - costs
    stamp = now_ist().isoformat(timespec="seconds")
    conn.execute("""
        UPDATE trades SET status='CLOSED', exit_time=?, exit_price=?, exit_reason=?,
            gross_pnl=?, estimated_costs=?, net_pnl=?, last_price=?, last_checked=?
        WHERE trade_id=? AND status='OPEN'
    """, (stamp, exit_price, reason, gross, costs, net, exit_price, stamp, trade["trade_id"]))
    log_event(conn, trade["trade_id"], reason, f"Exit ₹{exit_price:.2f}; estimated net P&L ₹{net:.2f}")
    conn.commit()
    if alerts_enabled:
        send_telegram(
            f"🔴 PAPER EXIT — {reason}\n{trade['symbol']} ({trade['strategy']})\n"
            f"Qty: {qty} | Exit: ₹{exit_price:.2f}\nEstimated net P&L: ₹{net:.2f}\nSIMULATION ONLY"
        )


def manage_open_trades(conn, alerts_enabled):
    rows = conn.execute("SELECT * FROM trades WHERE status='OPEN'").fetchall()
    for trade in rows:
        interval = "5m" if trade["strategy"] == "Intraday" else "1d"
        data = fetch_data(trade["yahoo_symbol"], interval)
        if data.empty:
            continue
        price = safe_float(data["Close"].iloc[-1])
        if not np.isfinite(price) or price <= 0:
            continue
        stamp = now_ist()
        # Do not use stale intraday data as if it were a live quote.
        if interval == "5m" and not last_timestamp_is_recent(data, "5m"):
            continue
        conn.execute(
            "UPDATE trades SET last_price=?, last_checked=? WHERE trade_id=? AND status='OPEN'",
            (price, stamp.isoformat(timespec="seconds"), trade["trade_id"]),
        )
        # Conservative candle handling: if one candle spans both levels,
        # assume stop-loss was hit first. This is a simulation convention.
        latest = data.iloc[-1]
        low = safe_float(latest["Low"], price)
        high = safe_float(latest["High"], price)
        reason = None
        exit_price = None
        # Avoid using the same candle that produced the entry signal to trigger
        # an exit: its high/low may have happened before the simulated entry.
        try:
            entry_dt = datetime.fromisoformat(trade["entry_time"])
            bar_dt = pd.Timestamp(data.index[-1])
            if bar_dt.tzinfo is None:
                bar_dt = bar_dt.tz_localize(IST)
            else:
                bar_dt = bar_dt.tz_convert(IST)
            same_entry_candle = (
                bar_dt.date() == entry_dt.astimezone(IST).date()
                if interval == "1d"
                else bar_dt.to_pydatetime() <= entry_dt.astimezone(IST)
            )
        except Exception:
            same_entry_candle = True
        if not same_entry_candle and low <= float(trade["stop_price"]) and high >= float(trade["target_price"]):
            reason = "STOP_LOSS_AMBIGUOUS_CANDLE"
            exit_price = float(trade["stop_price"])
        elif not same_entry_candle and low <= float(trade["stop_price"]):
            reason = "STOP_LOSS_HIT"
            exit_price = float(trade["stop_price"])
        elif not same_entry_candle and high >= float(trade["target_price"]):
            reason = "TARGET_HIT"
            exit_price = float(trade["target_price"])
        elif trade["strategy"] == "Intraday" and stamp.weekday() < 5 and stamp.time() >= MARKET_CLOSE:
            reason = "INTRADAY_SQUARE_OFF"
            exit_price = price
        elif trade["strategy"] == "Swing":
            try:
                entry_date = datetime.fromisoformat(trade["entry_time"]).date()
                # Exit after five calendar trading weekdays have elapsed; holidays
                # are not individually modeled in this lightweight prototype.
                weekdays_elapsed = sum(
                    1 for n in range(1, (stamp.date() - entry_date).days + 1)
                    if (entry_date + timedelta(days=n)).weekday() < 5
                )
                if weekdays_elapsed >= 5:
                    reason = "MAX_HOLD_EXIT"
                    exit_price = price
            except Exception:
                pass
        if reason:
            close_trade(conn, trade, exit_price, reason, alerts_enabled)
    conn.commit()


def load_trades(status=None, limit=500):
    with db_connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status=? ORDER BY entry_time DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM trades ORDER BY entry_time DESC LIMIT ?", (limit,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def load_events(limit=200):
    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY event_id DESC LIMIT ?", (limit,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def money(value):
    return f"₹{value:,.2f}"


init_db()
st.title("📈 NSE Multi-Strategy Paper Trader")
st.caption("SIMULATION ONLY · Yahoo Finance data · No broker connection · No real orders")

with st.sidebar:
    st.header("Paper trading controls")
    budget = st.number_input("Starting budget (₹)", min_value=100.0, max_value=10000000.0, value=1000.0, step=100.0)
    risk_pct = st.slider("Max planned risk per trade (%)", min_value=0.5, max_value=2.0, value=1.0, step=0.5)
    min_score = st.slider("Minimum setup score", min_value=50, max_value=90, value=65, step=5)
    refresh_seconds = st.select_slider("Dashboard refresh", options=[30, 45, 60, 90, 120], value=60)
    alerts_enabled = st.toggle("Enable Telegram alerts", value=False)
    auto_scan = st.toggle("Auto-scan on refresh", value=False)
    st.caption("Keep auto-scan off if you want to limit Yahoo requests. Refreshing does not guarantee real-time data.")
    st.divider()
    if st.button("🔄 Scan watchlist now", use_container_width=True):
        st.session_state["scan_requested"] = True
    if st.button("🧹 Clear cached market data", use_container_width=True):
        fetch_data.clear()
        st.success("Market-data cache cleared.")

with db_connect() as conn:
    manage_open_trades(conn, alerts_enabled)

open_trades = load_trades("OPEN")
closed_trades = load_trades("CLOSED")
total_closed_net = float(closed_trades["net_pnl"].fillna(0).sum()) if not closed_trades.empty else 0.0
open_pnl = 0.0
if not open_trades.empty:
    for _, row in open_trades.iterrows():
        mark = safe_float(row.get("last_price"), safe_float(row["entry_price"]))
        open_pnl += (mark - float(row["entry_price"])) * int(row["quantity"])

m1, m2, m3, m4 = st.columns(4)
m1.metric("Starting budget", money(budget))
m2.metric("Open positions", str(len(open_trades)))
m3.metric("Open gross P&L*", money(open_pnl))
m4.metric("Closed net P&L*", money(total_closed_net))
st.caption("*Paper estimates only. Costs are approximate and may not reflect actual brokerage, taxes, spreads, or slippage.")

if alerts_enabled:
    token, chat_id = telegram_config()
    if token and chat_id:
        st.success("Telegram alerts enabled and credentials found.")
    else:
        st.warning("Telegram is toggled on, but credentials are missing. Add them in Streamlit Secrets.")

scan_requested = st.session_state.pop("scan_requested", False)
if "candidates" not in st.session_state:
    st.session_state["candidates"] = pd.DataFrame()
    st.session_state["scan_errors"] = []
should_scan = scan_requested or auto_scan
if should_scan:
    with st.spinner("Downloading market data and evaluating strategies…"):
        candidates, errors = scan_market()
        st.session_state["candidates"] = candidates
        st.session_state["scan_errors"] = errors
        st.session_state["scan_time"] = now_ist().strftime("%Y-%m-%d %H:%M:%S IST")

candidates = st.session_state["candidates"]
if st.session_state.get("scan_time"):
    st.caption(f"Last scan: {st.session_state['scan_time']}")
if st.session_state.get("scan_errors"):
    st.info("No usable data returned for: " + ", ".join(st.session_state["scan_errors"][:15]) +
            ("…" if len(st.session_state["scan_errors"]) > 15 else ""))

st.subheader("🎯 Best eligible setup")
if candidates.empty:
    st.info("No scan results yet. Tap **Scan watchlist now**. If the market is closed or data is unavailable, no intraday setup may appear.")
else:
    display_cols = ["symbol", "strategy", "price", "score", "rsi", "volume_ok", "reason"]
    st.dataframe(
        candidates[display_cols].rename(columns={
            "symbol": "Symbol", "strategy": "Strategy", "price": "Price (₹)",
            "score": "Score", "rsi": "RSI", "volume_ok": "Volume confirmed", "reason": "Signal basis",
        }),
        use_container_width=True, hide_index=True,
    )
    eligible = candidates[candidates["score"] >= min_score].copy()
    with db_connect() as conn:
        existing_open = conn.execute("SELECT COUNT(*) AS n FROM trades WHERE status='OPEN'").fetchone()["n"]
    if int(existing_open) > 0:
        st.warning("A paper position is already open. This version opens one position at a time to avoid overlapping exposure.")
    elif eligible.empty:
        st.info(f"No setup meets your minimum score of {min_score}. Waiting is allowed.")
    else:
        best = eligible.iloc[0].to_dict()
        price = float(best["price"])
        stop = round(price * (1 - float(best["stop_pct"])), 2)
        target = round(price * (1 + float(best["target_pct"])), 2)
        risk_per_share = max(0.01, price - stop)
        risk_cash = budget * risk_pct / 100
        qty_cash = int(budget // price)
        qty_risk = int(risk_cash // risk_per_share)
        preview_qty = min(qty_cash, qty_risk)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Selected", f"{best['symbol']} · {best['strategy']}")
        c2.metric("Indicative entry", money(price))
        c3.metric("Stop / Target", f"₹{stop:.2f} / ₹{target:.2f}")
        c4.metric("Estimated quantity", str(max(0, preview_qty)))
        if preview_qty < 1:
            st.warning("This setup does not fit the budget and risk limit. No position will be opened.")
        else:
            st.write(f"Score **{best['score']:.0f}/100** · Planned risk budget **{money(risk_cash)}** · Approximate target gain before costs **{money((target-price)*preview_qty)}**.")
            if st.button("🟡 Open paper position", type="primary", use_container_width=True):
                with db_connect() as conn:
                    ok, message = open_trade(best, budget, risk_pct, min_score, conn, alerts_enabled)
                if ok:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

st.subheader("🟢 Open paper positions")
if open_trades.empty:
    st.write("No open paper positions.")
else:
    view = open_trades.copy()
    view["last_price"] = pd.to_numeric(view["last_price"], errors="coerce")
    view["unrealized_gross_pnl"] = (view["last_price"] - view["entry_price"]) * view["quantity"]
    st.dataframe(view[[
        "trade_id", "symbol", "strategy", "entry_time", "entry_price", "last_price",
        "quantity", "stop_price", "target_price", "score", "unrealized_gross_pnl", "last_checked"
    ]], use_container_width=True, hide_index=True)
    st.caption("Open P&L is gross and excludes estimated exit costs. Prices update when the app refreshes and fresh data is available.")

st.subheader("📒 Trade ledger")
if closed_trades.empty and open_trades.empty:
    st.write("No trades recorded yet.")
else:
    ledger = load_trades(limit=500)
    preferred = [
        "trade_id", "symbol", "strategy", "status", "signal_time", "entry_time",
        "entry_price", "quantity", "stop_price", "target_price", "score",
        "exit_time", "exit_price", "exit_reason", "gross_pnl", "estimated_costs",
        "net_pnl", "last_price", "last_checked"
    ]
    ledger = ledger[[c for c in preferred if c in ledger.columns]]
    st.dataframe(ledger, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ Download trade ledger CSV",
        data=ledger.to_csv(index=False).encode("utf-8"),
        file_name=f"nse_paper_trades_{now_ist().date().isoformat()}.csv",
        mime="text/csv",
        use_container_width=True,
    )

with st.expander("🧾 Event log"):
    events = load_events()
    if events.empty:
        st.write("No events yet.")
    else:
        st.dataframe(events, use_container_width=True, hide_index=True)
        st.download_button(
            "Download event log CSV",
            data=events.to_csv(index=False).encode("utf-8"),
            file_name=f"nse_paper_events_{now_ist().date().isoformat()}.csv",
            mime="text/csv",
        )

with st.expander("ℹ️ Strategy rules and limitations"):
    st.markdown("""
    **Intraday:** 5-minute EMA 5/13 trend, RSI range, and at least one crossover,
    volume-confirmation, or breakout condition. Intraday signals are only considered
    during the regular weekday session and stale 5-minute data is rejected.

    **Swing:** daily EMA 9/21 trend or a limited momentum dip-bounce condition,
    with RSI and volume checks. The simulator applies a maximum five-weekday holding
    rule; exchange holidays are not individually modeled.

    **Scoring:** scores are heuristic filters, not probabilities of winning and not
    evidence of a profitable strategy. Validate using a proper out-of-sample backtest.

    **Execution simulation:** fills are modeled at signal/threshold prices. A candle
    that touches both stop and target is conservatively counted as stop-loss first.
    Gap risk, order-book depth, circuits, real bid/ask spreads, and exact exchange
    charges are not fully modeled.

    **Data:** yfinance/Yahoo Finance data can be delayed, missing, adjusted, or
    inconsistent. It is not an exchange-grade execution feed. `dropna()` is applied
    after OHLCV validation.

    **Hosting:** SQLite on Streamlit Community Cloud is not guaranteed durable across
    all restarts/redeployments. Download your CSV regularly; use external persistent
    storage before relying on records for anything important.

    **Trading:** paper trading only. This application does not connect to Zerodha,
    place real orders, or guarantee returns. It is educational software, not financial advice.
    """)

st.divider()
st.caption("NSE Multi-Strategy Paper Trader · Paper mode only · Never store secrets in GitHub")

# Streamlit rerun refresh is for dashboard updates, not a reliable background scheduler.
if st.toggle("Enable automatic dashboard refresh", value=False, key="dashboard_autorefresh"):
    st.caption(f"Refreshing every {refresh_seconds} seconds. This does not guarantee continuous execution while the app is asleep.")
    time.sleep(int(refresh_seconds))
    st.rerun()
