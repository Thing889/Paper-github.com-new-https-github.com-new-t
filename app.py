# ======================================================================
#  NSE PAPER TRADING BOT - single-file Streamlit app (app.py)
#  Paper trading only. Live Zerodha orders stay OFF unless you enable them.
# ======================================================================
import json
import math
import os
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

# ----------------------------- CONFIG ---------------------------------
IST = ZoneInfo("Asia/Kolkata")
STATE_FILE = "paper_state.json"
REFRESH_SECONDS = 10
MARKET_OPEN, MARKET_CLOSE = dtime(9, 15), dtime(15, 30)
ENTRY_START = dtime(9, 30)
NO_NEW_INTRADAY_AFTER = dtime(14, 30)
NO_NEW_ENTRY_AFTER = dtime(15, 10)
SWING_MAX_DAYS = 7
STALE_MINUTES = 60
MIN_AVG_VOLUME = 300_000
MIN_AVG_TURNOVER = 2e7  # Rs 2 crore traded per day

UNIVERSE = list(dict.fromkeys([
    # ---- budget stocks (roughly Rs 10-150) ----
    "IDEA", "IOB", "NHPC", "NMDC", "SUZLON", "IDFCFIRSTB", "PNB", "NBCC",
    "YESBANK", "SAIL", "BANKBARODA", "IRFC", "RVNL", "GAIL", "TATAPOWER",
    "UNIONBANK", "BHEL", "ONGC", "NTPC", "COALINDIA", "POWERGRID", "WIPRO",
    "HINDALCO", "VEDL", "CANBK", "UCOBANK", "CENTRALBK", "MAHABANK", "PSB",
    "BANKINDIA", "INDIANB", "IDBI", "BANDHANBNK", "RBLBANK", "FEDERALBNK",
    "SOUTHBANK", "KARURVYSYA", "CUB", "DCBBANK", "UJJIVANSFB", "EQUITASBNK",
    "PFC", "RECLTD", "IREDA", "JPPOWER", "RPOWER", "RELINFRA", "JIOFIN",
    "NATIONALUM", "HINDCOPPER", "SJVN", "NLCINDIA", "HUDCO", "IRCON",
    "RAILTEL", "ITI", "HFCL", "MOTHERSON", "ASHOKLEY", "GMRAIRPORT",
    "JSWENERGY", "NYKAA", "PAYTM", "ETERNAL", "SWIGGY", "POLICYBZR",
    "OLAELEC", "IEX", "IGL", "PETRONET", "OIL", "GUJGASLTD", "MGL", "NCC",
    "PNCINFRA", "IRB", "HCC", "JPASSOCIAT", "RENUKA", "BALRAMCHIN",
    "PCJEWELLER", "RCF", "NFL", "FACT", "GRSE", "MOIL", "GMDCLTD", "WELCORP",
    "ZEEL", "NETWORK18", "TV18BRDCST", "SUNTV", "PVRINOX", "SAREGAMA",
    "MANAPPURAM", "MUTHOOTFIN", "IIFL", "PNBHOUSING", "LICHSGFIN",
    "ABCAPITAL", "POONAWALLA", "TATATECH", "KALYANKJIL", "INOXWIND",
    "TRIDENT", "HINDZINC", "IOC", "BPCL", "HINDPETRO", "ADANIPOWER",
    "ADANIGREEN", "TATACOMM", "CDSL", "ANGELONE", "BSE", "MCX",
    # ---- large and mid caps ----
    "TATASTEEL", "BEL", "ITC", "SBIN", "RELIANCE", "HDFCBANK", "ICICIBANK",
    "INFY", "TCS", "AXISBANK", "JSWSTEEL", "KOTAKBANK", "BHARTIARTL", "LT",
    "HINDUNILVR", "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "ASIANPAINT",
    "NESTLEIND", "BAJFINANCE", "BAJAJFINSV", "HCLTECH", "TECHM", "M&M",
    "ADANIENT", "ADANIPORTS", "DRREDDY", "CIPLA", "DIVISLAB", "EICHERMOT",
    "HEROMOTOCO", "BAJAJ-AUTO", "GRASIM", "SHREECEM", "INDUSINDBK",
    "SBILIFE", "HDFCLIFE", "ICICIPRULI", "ICICIGI", "LICI", "DLF", "LODHA",
    "GODREJPROP", "OBEROIRLTY", "TRENT", "DMART", "HAL", "BDL", "MAZDOCK",
    "COCHINSHIP", "BEML", "CGPOWER", "SIEMENS", "ABB", "HAVELLS", "POLYCAB",
    "KEI", "DIXON", "AMBUJACEM", "ACC", "JINDALSTEL", "APLAPOLLO",
    "PIDILITIND", "BERGEPAINT", "COLPAL", "DABUR", "GODREJCP", "MARICO",
    "TATACONSUM", "VBL", "JUBLFOOD", "PAGEIND", "ZYDUSLIFE", "LUPIN",
    "AUROPHARMA", "BIOCON", "TORNTPHARM", "ALKEM", "GLENMARK", "MAXHEALTH",
    "APOLLOHOSP", "FORTIS", "TVSMOTOR", "BHARATFORG", "BOSCHLTD", "EXIDEIND",
    "PERSISTENT", "COFORGE", "MPHASIS", "LTIM", "NAUKRI", "IRCTC", "CONCOR",
    "INDIGO", "TATAELXSI", "PATANJALI", "SBICARD", "HDFCAMC", "CHOLAFIN",
    "SHRIRAMFIN", "AUBANK", "JSL",
]))

MOMENTUM = {"EMA Crossover", "RSI Momentum", "Volume Breakout"}
REGIME_MULT = {"BULLISH": 1.0, "NEUTRAL": 0.95, "UNKNOWN": 0.95, "BEARISH": 0.85}
REGIME_ICON = {"BULLISH": "🟢", "NEUTRAL": "🟡", "BEARISH": "🟠", "CRASH": "🔴", "UNKNOWN": "⚪"}

# tp / sl are ATR multiples; horizon = bars used when back-testing a strategy
MODE_CFG = {
    "Intraday": dict(interval="5m", period="5d", tp=4.0, sl=2.5, horizon=36),
    "Swing": dict(interval="1d", period="6mo", tp=2.5, sl=1.5, horizon=5),
}

# Zerodha-style charges (edit here if Zerodha changes its rates)
CHG = {
    "Intraday": dict(brk_pct=0.0003, brk_cap=20.0, stt_buy=0.0, stt_sell=0.00025,
                     txn=0.000019, stamp_buy=0.00003, dp=0.0),
    "Swing": dict(brk_pct=0.0, brk_cap=0.0, stt_buy=0.001, stt_sell=0.001,
                  txn=0.0000322, stamp_buy=0.00015, dp=15.34),
}
SEBI_PER_CRORE = 10.0
GST_RATE = 0.18

TRADE_COLS = ["id", "symbol", "mode", "strategy", "win_score", "entry_time", "exit_time",
              "qty", "entry_price", "exit_price", "gross_pnl", "charges", "net_pnl",
              "exit_reason", "wallet_after"]


# ----------------------------- HELPERS --------------------------------
def inr(x, d=2):
    try:
        x = float(x)
    except Exception:
        return "—"
    if not math.isfinite(x):
        return "—"
    return f"{'-' if x < 0 else ''}₹{abs(x):,.{d}f}"


def inr_signed(x):
    try:
        x = float(x)
    except Exception:
        return None
    if not math.isfinite(x):
        return None
    return f"{'+' if x >= 0 else '-'}₹{abs(x):,.2f}"


def fmt_td(td):
    s = int(td.total_seconds())
    if s <= 0:
        return "0m"
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    return (f"{d}d " if d else "") + (f"{h}h " if (h or d) else "") + f"{m}m"


def round_tick(x, tick=0.05):
    return round(round(float(x) / tick) * tick, 2)


def secret(name, default=""):
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


def market_is_open(now):
    return now.weekday() < 5 and MARKET_OPEN <= now.time() < MARKET_CLOSE


def intraday_deadline(now):
    d = now.replace(hour=15, minute=15, second=0, microsecond=0)
    if now >= d:
        d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


# ------------------------ BROKERAGE & TAX CALC -------------------------
def calc_charges(mode, buy_price, sell_price, qty):
    c = CHG["Swing" if mode == "Swing" else "Intraday"]
    buy_val, sell_val = float(buy_price) * qty, float(sell_price) * qty
    turnover = buy_val + sell_val
    if c["brk_cap"] > 0:
        brokerage = min(c["brk_cap"], c["brk_pct"] * buy_val) + min(c["brk_cap"], c["brk_pct"] * sell_val)
    else:
        brokerage = 0.0
    stt = c["stt_buy"] * buy_val + c["stt_sell"] * sell_val
    txn = c["txn"] * turnover
    sebi = SEBI_PER_CRORE / 1e7 * turnover
    gst = GST_RATE * (brokerage + sebi + txn)
    stamp = c["stamp_buy"] * buy_val
    dp = c["dp"]
    total = brokerage + stt + txn + sebi + gst + stamp + dp
    return dict(brokerage=brokerage, stt=stt, txn=txn, sebi=sebi, gst=gst,
                stamp=stamp, dp=dp, total=total)


# --------------------------- DATA LAYER --------------------------------
def clean(df):
    """Normalise yfinance output: OHLCV only, numeric, no NaN, IST index."""
    if df is None or len(df) == 0:
        return None
    try:
        d = df.copy()
        keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in d.columns]
        if not {"Open", "High", "Low", "Close"}.issubset(keep):
            return None
        d = d[keep].copy()
        for c in keep:
            d[c] = pd.to_numeric(d[c], errors="coerce")
        if "Volume" not in d.columns:
            d["Volume"] = 0.0
        d = d.dropna(subset=["Open", "High", "Low", "Close"])
        d = d[d["Close"] > 0].copy()
        d["Volume"] = d["Volume"].fillna(0.0)
        if len(d) == 0:
            return None
        idx = pd.DatetimeIndex(d.index)
        idx = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
        d.index = idx
        d = d[~d.index.duplicated(keep="last")].sort_index()
        return d
    except Exception:
        return None


def _extract(raw, ticker):
    if raw is None or len(raw) == 0:
        return None
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            lv0 = raw.columns.get_level_values(0)
            lv1 = raw.columns.get_level_values(1)
            if ticker in lv0:
                df = raw[ticker]
            elif ticker in lv1:
                df = raw.xs(ticker, axis=1, level=1)
            else:
                return None
        else:
            df = raw
        return clean(df)
    except Exception:
        return None


@st.cache_data(ttl=100, show_spinner=False)
def fetch_bulk(symbols, interval, period):
    """Download in small batches so a big stock list never overloads Yahoo."""
    out = {}
    batch = 40
    for i in range(0, len(symbols), batch):
        chunk = list(symbols[i:i + batch])
        tickers = [s + ".NS" for s in chunk]
        try:
            raw = yf.download(tickers, period=period, interval=interval, group_by="ticker",
                              auto_adjust=True, progress=False, threads=True)
        except Exception:
            continue
        for s in chunk:
            d = _extract(raw, s + ".NS")
            if d is not None and len(d):
                out[s] = d
    return out


@st.cache_data(ttl=8, show_spinner=False)
def get_live_price(symbol):
    """Returns (price, timestamp_iso, interval) - never NaN; (None, None, None) if unavailable."""
    tk = yf.Ticker(symbol + ".NS")
    for period, interval in (("1d", "1m"), ("5d", "5m"), ("1mo", "1d")):
        try:
            h = clean(tk.history(period=period, interval=interval, auto_adjust=True))
            if h is not None and len(h):
                p = float(h["Close"].iloc[-1])
                if math.isfinite(p) and p > 0:
                    return p, h.index[-1].isoformat(), interval
        except Exception:
            continue
    return None, None, None


# ------------------------ NIFTY 50 REGIME FILTER -----------------------
@st.cache_data(ttl=120, show_spinner=False)
def get_regime():
    out = dict(state="UNKNOWN", chg=None, last=None, age_min=None)
    try:
        tk = yf.Ticker("^NSEI")
        d = clean(tk.history(period="6mo", interval="1d", auto_adjust=True))
        i = clean(tk.history(period="5d", interval="5m", auto_adjust=True))
    except Exception:
        return out
    if d is None or len(d) < 25:
        return out
    closes = d["Close"]
    last = float(closes.iloc[-1])
    if i is not None and len(i):
        out["age_min"] = (datetime.now(IST) - i.index[-1].to_pydatetime()).total_seconds() / 60.0
        if i.index[-1].date() == d.index[-1].date():
            last = float(i["Close"].iloc[-1])
    prev = float(closes.iloc[-2])
    chg = (last / prev - 1.0) * 100.0
    e20 = float(ema(closes, 20).iloc[-1])
    e50 = float(ema(closes, 50).iloc[-1])
    ret5 = (last / float(closes.iloc[-6]) - 1.0) * 100.0 if len(closes) >= 6 else 0.0
    above20, above50 = last > e20, last > e50
    if chg <= -1.5 or (chg <= -1.0 and not above20):
        state = "CRASH"
    elif (not above20 and not above50) or chg <= -0.7 or ret5 <= -3.0:
        state = "BEARISH"
    elif above20 and above50 and e20 > e50 and chg >= -0.2:
        state = "BULLISH"
    else:
        state = "NEUTRAL"
    out.update(state=state, chg=round(chg, 2), last=round(last, 2))
    return out


# ----------------------------- INDICATORS ------------------------------
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(s, n=14):
    dlt = s.diff()
    up = dlt.clip(lower=0.0)
    dn = -dlt.clip(upper=0.0)
    ru = up.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rd = dn.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = ru / rd.replace(0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    out = out.where(~((rd == 0) & (ru > 0)), 100.0)
    return out.fillna(50.0)


def atr(d, n=14):
    pc = d["Close"].shift(1)
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - pc).abs(), (d["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def add_indicators(df):
    if df is None or len(df) < 60:
        return None
    d = df.copy()
    c = d["Close"]
    d["ema9"], d["ema21"], d["ema50"] = ema(c, 9), ema(c, 21), ema(c, 50)
    d["rsi"] = rsi(c, 14)
    d["atr"] = atr(d, 14)
    d["vol_avg"] = d["Volume"].rolling(20).mean()
    d["hh20"] = d["High"].rolling(20).max().shift(1)
    d = d.dropna(subset=["atr", "ema50"])
    return d if len(d) >= 40 else None


# ------------------------------ STRATEGIES -----------------------------
def strategy_signals(d):
    c, o = d["Close"], d["Open"]
    cross = (d["ema9"] > d["ema21"]) & (d["ema9"].shift(1) <= d["ema21"].shift(1))
    return {
        "EMA Crossover": cross & (c > d["ema50"]),
        "RSI Momentum": d["rsi"].between(55, 72) & (d["rsi"] > d["rsi"].shift(3))
                        & (c > d["ema21"]) & (d["ema21"] > d["ema50"]),
        "Oversold Dip Reversal": (d["rsi"].rolling(5).min() < 33) & (d["rsi"] > d["rsi"].shift(1))
                                 & (c > o) & (c > c.shift(1)),
        "Volume Breakout": (c > d["hh20"]) & (d["Volume"] > 1.5 * d["vol_avg"]) & (c > o),
    }


def freshness(s):
    v = [bool(x) for x in s.iloc[-3:].tolist()]
    if v and v[-1]:
        return 1.0
    if len(v) > 1 and v[-2]:
        return 0.8
    if len(v) > 2 and v[-3]:
        return 0.6
    return 0.0


def quality(name, d):
    r = d.iloc[-1]
    rv = float(r["rsi"])
    if name == "EMA Crossover":
        return 0.75 + (0.25 if 50 <= rv <= 70 else 0.0)
    if name == "RSI Momentum":
        return float(np.clip(1 - abs(rv - 62) / 20.0, 0.5, 1.0))
    if name == "Oversold Dip Reversal":
        return float(np.clip(0.6 + (35 - float(d["rsi"].iloc[-6:].min())) / 50.0, 0.6, 1.0))
    va = float(r["vol_avg"])
    ratio = float(r["Volume"]) / va if va > 0 else 1.0
    return float(np.clip(0.5 + (ratio - 1.5) * 0.25, 0.5, 1.0))


def trend_score(d):
    r = d.iloc[-1]
    if r["Close"] > r["ema50"] and r["ema21"] > r["ema50"]:
        return 1.0
    if r["Close"] > r["ema50"]:
        return 0.6
    return 0.3


def rel_volume(d):
    va = float(d["vol_avg"].iloc[-1])
    if not (va > 0):
        return 0.5
    return float(np.clip(d["Volume"].iloc[-3:].mean() / va / 1.5, 0.0, 1.0))


def backtest(d, s, cfg, day_ids=None):
    """Replay a strategy's past signals with the same ATR target/stop. Returns (n, wins)."""
    c, o = d["Close"].values, d["Open"].values
    h, l, a = d["High"].values, d["Low"].values, d["atr"].values
    sig = s.fillna(False).values.astype(bool)
    n = wins = 0
    nxt = 0
    for i in np.flatnonzero(sig[: max(len(sig) - 2, 0)]):
        if i < nxt or not (np.isfinite(a[i]) and a[i] > 0):
            continue
        entry = o[i + 1] if np.isfinite(o[i + 1]) else c[i]
        tp, sl = entry + cfg["tp"] * a[i], entry - cfg["sl"] * a[i]
        last_j = min(i + cfg["horizon"], len(c) - 1)
        outcome = None
        for j in range(i + 1, last_j + 1):
            if day_ids is not None and day_ids[j] != day_ids[i]:
                last_j = j - 1
                break
            if l[j] <= sl:
                outcome = False
                break
            if h[j] >= tp:
                outcome = True
                break
        if outcome is None:
            if last_j <= i:
                continue
            outcome = bool(c[last_j] > entry)
        n += 1
        wins += int(outcome)
        nxt = i + cfg["horizon"]
    return n, wins


def make_plan(mode, entry, atr_v, capital):
    """Size the position and compute target/stop plus NET (after-charges) outcomes."""
    cfg = MODE_CFG[mode]
    if not (entry > 0 and atr_v > 0):
        return None
    qty = int(capital // entry)
    if qty < 1:
        return None
    tp = round_tick(entry + cfg["tp"] * atr_v)
    stop = round_tick(entry - cfg["sl"] * atr_v)
    if tp <= entry or stop <= 0 or stop >= entry:
        return None
    net_tp = (tp - entry) * qty - calc_charges(mode, entry, tp, qty)["total"]
    net_sl = (stop - entry) * qty - calc_charges(mode, entry, stop, qty)["total"]
    if net_tp <= 0:
        return None
    rr = net_tp / abs(net_sl) if net_sl < 0 else 9.0
    return dict(qty=qty, tp=tp, stop=stop, net_tp=net_tp, net_sl=net_sl, rr=rr)


def liquid_ok(dd):
    try:
        t = dd.tail(20)
        return (float(t["Volume"].mean()) >= MIN_AVG_VOLUME
                and float((t["Volume"] * t["Close"]).mean()) >= MIN_AVG_TURNOVER)
    except Exception:
        return False


def build_candidates(sym, df, mode, regime_state, capital, min_score, check_fresh):
    d = add_indicators(df)
    if d is None:
        return []
    price, atr_v = float(d["Close"].iloc[-1]), float(d["atr"].iloc[-1])
    if not (price > 0 and atr_v > 0) or price > capital:
        return []
    if mode == "Intraday" and check_fresh:
        age = (datetime.now(IST) - d.index[-1].to_pydatetime()).total_seconds() / 60.0
        if age > 30:
            return []
    cfg = MODE_CFG[mode]
    day_ids = np.array([t.toordinal() for t in d.index.date]) if mode == "Intraday" else None
    mult = REGIME_MULT.get(regime_state, 0.95)
    out = []
    for name, s in strategy_signals(d).items():
        if regime_state == "BEARISH" and name in MOMENTUM:
            continue
        fresh = freshness(s)
        if fresh <= 0:
            continue
        strength = fresh * quality(name, d)
        n, wins = backtest(d, s, cfg, day_ids)
        wr = (wins + 2.5) / (n + 5.0)  # shrunk toward 50% when few signals
        score = 100.0 * (0.35 * strength + 0.35 * wr + 0.15 * trend_score(d) + 0.15 * rel_volume(d)) * mult
        if score < min_score:
            continue
        plan = make_plan(mode, price, atr_v, capital)
        if not plan or plan["rr"] < 1.0:
            continue
        p = score / 100.0
        ev = p * plan["net_tp"] + (1 - p) * plan["net_sl"]
        if ev <= 0:
            continue
        out.append(dict(symbol=sym, mode=mode, strategy=name, price=price, atr=atr_v,
                        win_score=round(score, 1), hist_wr=int(round(100 * wr)), hist_n=int(n),
                        qty=int(plan["qty"]), target=float(plan["tp"]), stop=float(plan["stop"]),
                        net_tp=float(plan["net_tp"]), net_sl=float(plan["net_sl"]), ev=float(ev)))
    return out


@st.cache_data(ttl=120, show_spinner=False)
def run_scan(capital, allow_intraday, allow_swing, min_score, regime_state, check_fresh):
    daily = fetch_bulk(tuple(UNIVERSE), "1d", "6mo")
    liquid, pool = 0, []
    for sym in UNIVERSE:
        dd = daily.get(sym)
        if dd is None or not liquid_ok(dd):
            continue
        liquid += 1
        if float(dd["Close"].iloc[-1]) <= capital:  # can afford at least 1 share
            pool.append(sym)
    # intraday data is only downloaded for stocks that are liquid AND affordable
    intr = fetch_bulk(tuple(pool), "5m", "5d") if (allow_intraday and pool) else {}
    cands = []
    for sym in pool:
        try:
            if allow_swing:
                cands += build_candidates(sym, daily[sym], "Swing", regime_state, capital, min_score, check_fresh)
            if allow_intraday and sym in intr:
                cands += build_candidates(sym, intr[sym], "Intraday", regime_state, capital, min_score, check_fresh)
        except Exception:
            continue
    cands.sort(key=lambda c: (c["ev"], c["win_score"]), reverse=True)
    return cands, dict(universe=len(UNIVERSE), loaded=len(daily), liquid=liquid, affordable=len(pool))


# --------------------------- STATE / WALLET ----------------------------
def new_state(capital):
    return dict(start_capital=float(capital), cash=float(capital), position=None, trades=[],
                recent_losses={}, armed=True, created=datetime.now(IST).isoformat())


def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                S = json.load(f)
            if isinstance(S, dict) and "cash" in S and "start_capital" in S:
                S.setdefault("position", None)
                S.setdefault("trades", [])
                S.setdefault("recent_losses", {})
                S.setdefault("armed", True)
                return S
    except Exception:
        pass
    return None


def save_state(S):
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(S, f, default=str)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


def restore_state_from_df(df):
    if df is None or df.empty or not {"net_pnl", "wallet_after"}.issubset(df.columns):
        raise ValueError("CSV must be a history file downloaded from this app")
    first, last = df.iloc[0], df.iloc[-1]
    S = new_state(float(first["wallet_after"]) - float(first["net_pnl"]))
    S["cash"] = float(last["wallet_after"])
    S["trades"] = df.to_dict("records")
    return S


# --------------------- TELEGRAM + KITE (EXECUTION) ---------------------
def send_telegram(text):
    token = str(st.session_state.get("tg_token", "") or "").strip()
    chat = str(st.session_state.get("tg_chat", "") or "").strip()
    if not token or not chat:
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text}, timeout=8)
        return r.ok
    except Exception:
        return False


def kite_place_order(api_key, access_token, symbol, side, qty, mode):
    """Real Zerodha order. Needs `kiteconnect` in requirements.txt and a fresh daily access token."""
    try:
        from kiteconnect import KiteConnect
    except Exception:
        return False, "kiteconnect not installed (add it to requirements.txt)"
    try:
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        oid = kite.place_order(
            variety=kite.VARIETY_REGULAR, exchange=kite.EXCHANGE_NSE, tradingsymbol=symbol,
            transaction_type=kite.TRANSACTION_TYPE_BUY if side == "BUY" else kite.TRANSACTION_TYPE_SELL,
            quantity=int(qty),
            product=kite.PRODUCT_MIS if mode == "Intraday" else kite.PRODUCT_CNC,
            order_type=kite.ORDER_TYPE_MARKET)
        return True, str(oid)
    except Exception as e:
        return False, str(e)


def execute_order(side, symbol, qty, mode):
    """Paper by default. A real order is sent only if live mode + confirmation + keys are all set."""
    ss = st.session_state
    if not (ss.get("kite_live") and ss.get("kite_confirm") and ss.get("kite_key") and ss.get("kite_token")):
        return "paper"
    ok, info = kite_place_order(str(ss["kite_key"]).strip(), str(ss["kite_token"]).strip(),
                                symbol, side, qty, mode)
    send_telegram(f"{'✅' if ok else '❌'} Kite {side} {symbol} x{qty}: {info}")
    return info


# --------------------------- TRADE LIFECYCLE ---------------------------
def open_trade(S, c, entry, plan, now, regime_state):
    mode = c["mode"]
    if mode == "Intraday":
        deadline = intraday_deadline(now)
    else:
        deadline = (now + timedelta(days=SWING_MAX_DAYS)).replace(hour=15, minute=15, second=0, microsecond=0)
    S["position"] = dict(
        symbol=c["symbol"], mode=mode, strategy=c["strategy"], win_score=float(c["win_score"]),
        entry_price=float(entry), qty=int(plan["qty"]), entry_time=now.isoformat(),
        target=float(plan["tp"]), stop=float(plan["stop"]), initial_stop=float(plan["stop"]),
        atr=float(c["atr"]), highest=float(entry), last_price=float(entry),
        deadline=deadline.isoformat(), regime=regime_state)
    S["cash"] = float(S["cash"] - entry * plan["qty"])
    save_state(S)
    execute_order("BUY", c["symbol"], plan["qty"], mode)
    send_telegram(f"🟢 BUY {c['symbol']} x{plan['qty']} @ {inr(entry)}\n{mode} · {c['strategy']} · Win Score {c['win_score']}\n"
                  f"🎯 {inr(plan['tp'])}  🛑 {inr(plan['stop'])}")


def close_trade(S, exit_px, reason, now):
    pos = S["position"]
    exit_px = float(exit_px)
    ch = calc_charges(pos["mode"], pos["entry_price"], exit_px, pos["qty"])
    gross = (exit_px - pos["entry_price"]) * pos["qty"]
    net = gross - ch["total"]
    S["cash"] = float(S["cash"] + exit_px * pos["qty"] - ch["total"])
    S["trades"].append(dict(
        id=len(S["trades"]) + 1, symbol=pos["symbol"], mode=pos["mode"], strategy=pos["strategy"],
        win_score=pos["win_score"], entry_time=pos["entry_time"][:16].replace("T", " "),
        exit_time=now.strftime("%Y-%m-%d %H:%M"), qty=pos["qty"],
        entry_price=round(pos["entry_price"], 2), exit_price=round(exit_px, 2),
        gross_pnl=round(gross, 2), charges=round(ch["total"], 2), net_pnl=round(net, 2),
        exit_reason=reason, wallet_after=round(S["cash"], 2)))
    if net < 0:
        S["recent_losses"][pos["symbol"]] = now.date().isoformat()
    S["position"] = None
    S["armed"] = bool(st.session_state.get("auto_next", True))
    save_state(S)
    execute_order("SELL", pos["symbol"], pos["qty"], pos["mode"])
    send_telegram(f"{'✅' if net >= 0 else '🔻'} SELL {pos['symbol']} x{pos['qty']} @ {inr(exit_px)} ({reason})\n"
                  f"Gross {inr(gross)} · Charges {inr(ch['total'])} · NET {inr(net)}\nWallet {inr(S['cash'])}")


def update_trailing(pos, price):
    """ATR trailing stop: ratchets up with the highest price; locks break-even after 50% of the move."""
    cfg = MODE_CFG[pos["mode"]]
    pos["highest"] = max(float(pos.get("highest", pos["entry_price"])), float(price))
    stop = max(float(pos["stop"]), round_tick(pos["highest"] - cfg["sl"] * pos["atr"]))
    span = pos["target"] - pos["entry_price"]
    if span > 0 and (pos["highest"] - pos["entry_price"]) / span >= 0.5:
        per_share = calc_charges(pos["mode"], pos["entry_price"], pos["entry_price"], pos["qty"])["total"] / pos["qty"]
        stop = max(stop, round_tick(pos["entry_price"] + per_share * 1.5))
    pos["stop"] = min(stop, round_tick(pos["target"] - 0.05))


# ------------------------------- UI ------------------------------------
def monitor_position(S, now, open_now, test_mode):
    pos = S["position"]
    price, _, _ = get_live_price(pos["symbol"])
    if price is None or not math.isfinite(price):
        price = pos.get("last_price") or pos["entry_price"]
    price = float(price)
    pos["last_price"] = price
    deadline = datetime.fromisoformat(pos["deadline"])
    reason, exit_px = None, price
    if open_now or test_mode:
        if price >= pos["target"]:
            reason, exit_px = "Target hit", pos["target"]
        else:
            update_trailing(pos, price)
            if price <= pos["stop"]:
                reason = "Trailing stop" if pos["stop"] > pos["initial_stop"] else "Stop-loss"
    if reason is None and now >= deadline:
        reason = "3:15 PM auto-exit" if pos["mode"] == "Intraday" else "7-day limit"
    if reason:
        close_trade(S, exit_px, reason, now)
        return True
    save_state(S)

    entry, qty = pos["entry_price"], pos["qty"]
    gross = (price - entry) * qty
    est = calc_charges(pos["mode"], entry, price, qty)["total"]
    net = gross - est
    st.subheader(f"{'🟢' if net >= 0 else '🔴'} {pos['symbol']} · {pos['mode']}")
    st.caption(f"{pos['strategy']} · Win Score {pos['win_score']} · Nifty regime at entry: {pos['regime']}")
    a, b = st.columns(2)
    a.metric("Live price", inr(price), f"{(price / entry - 1) * 100:+.2f}%")
    b.metric("Entry × Qty", f"{inr(entry)} × {qty}")
    a.metric("Gross P&L", inr(gross))
    b.metric("Real Net P&L", inr(net), inr_signed(net))
    a.metric("🎯 Target", inr(pos["target"]))
    b.metric("🛑 Stop (trailing)", inr(pos["stop"]))
    span = pos["target"] - pos["stop"]
    frac = (price - pos["stop"]) / span if span > 0 else 0.0
    st.progress(float(min(max(frac, 0.0), 1.0)), text="Stop ◀──────▶ Target")
    st.caption(f"Est. exit charges incl. taxes: {inr(est)} · ⏱ auto-exit {deadline:%a %d %b %H:%M} IST "
               f"({fmt_td(deadline - now)} left)")
    if st.button("🚪 Exit now at market price", key="manual_exit"):
        close_trade(S, price, "Manual exit", now)
        return True
    return False


def seek_entry(S, now, open_now, regime, test_mode):
    ss = st.session_state
    state = regime.get("state", "UNKNOWN")
    t = now.time()
    if not S.get("armed", True):
        st.info("Last trade closed. Tap below to let the bot pick the next one.")
        if st.button("🔍 Find next trade", key="find_next"):
            S["armed"] = True
            save_state(S)
            return True
        return False
    if state == "CRASH":
        st.error(f"🔴 Nifty crash filter ON ({regime.get('chg')}% today). Bot is staying in cash.")
        return False
    can_enter = test_mode or (open_now and ENTRY_START <= t < NO_NEW_ENTRY_AFTER)
    allow_intraday = True if not can_enter else (test_mode or t < NO_NEW_INTRADAY_AFTER)
    if not can_enter:
        st.info("🔴 Market closed (or too late to enter). Preview below — the bot auto-enters from "
                "9:30 AM IST on the next trading day while this page stays open.")
    elif not allow_intraday:
        st.info("After 2:30 PM IST: no new Intraday entries. Scanning Swing only.")
    with st.spinner("Scanning NSE universe..."):
        cands, stats = run_scan(round(float(S["cash"]), 2), bool(allow_intraday), True,
                                int(ss.get("min_score", 55)), state, bool(open_now and not test_mode))
    st.caption(f"Scanned {stats['affordable']} stocks you can afford (≤ {inr(S['cash'])}) · "
               f"{stats['liquid']} liquid of {stats['loaded']} loaded · {stats['universe']} in watch-list")
    if not cands:
        st.warning("No setup passes the Win Score + net-of-charges profit test right now. Re-scanning every 2 minutes.")
        if S["cash"] < 500:
            st.caption("Small capital tip: Swing (delivery) pays a flat ₹15.34 DP fee on every sell, so the bot "
                       "only picks Swing when it still profits after charges.")
        return False
    df = pd.DataFrame([{
        "Stock": c["symbol"], "Mode": c["mode"], "Strategy": c["strategy"], "Win Score": c["win_score"],
        "Hist WR %": c["hist_wr"], "Qty": c["qty"], "Target": round(c["target"], 2),
        "Stop": round(c["stop"], 2), "Exp. Net ₹": round(c["ev"], 2)} for c in cands[:5]])
    st.markdown("**🏆 Top picks (ranked by expected net profit)**")
    st.dataframe(df, hide_index=True)
    if not can_enter:
        return False
    today = now.date().isoformat()
    for c in cands[:10]:
        if S["recent_losses"].get(c["symbol"]) == today:
            continue
        px, _, _ = get_live_price(c["symbol"])
        entry = px if px else c["price"]
        if px and abs(px / c["price"] - 1) > 0.03:
            continue
        plan = make_plan(c["mode"], entry, c["atr"], S["cash"])
        if not plan:
            continue
        open_trade(S, c, entry, plan, now, state)
        return True
    st.warning("Top picks could not be entered at live prices. Retrying shortly.")
    return False


@st.fragment(run_every=REFRESH_SECONDS)
def dashboard():
    S = st.session_state.get("S")
    if S is None:
        return
    now = datetime.now(IST)
    top, body = st.container(), st.container()
    rerun = False
    regime = dict(state="UNKNOWN", chg=None, age_min=None)
    open_now = False
    try:
        regime = get_regime()
        age = regime.get("age_min")
        open_now = market_is_open(now) and age is not None and age < STALE_MINUTES
        test_mode = bool(st.session_state.get("test_mode"))
        with body:
            if S["position"]:
                rerun = monitor_position(S, now, open_now, test_mode)
            else:
                rerun = seek_entry(S, now, open_now, regime, test_mode)
    except Exception as e:
        with body:
            st.warning(f"Data hiccup - retrying automatically. ({type(e).__name__}: {e})")
    with top:
        pos = S["position"]
        held = pos["qty"] * float(pos.get("last_price") or pos["entry_price"]) if pos else 0.0
        equity = S["cash"] + held
        pnl = equity - S["start_capital"]
        st.caption(f"{'🟢 Market OPEN' if open_now else '🔴 Market closed / no fresh data'} · "
                   f"{now:%a %d %b %H:%M:%S} IST · refresh every {REFRESH_SECONDS}s")
        chg = regime.get("chg")
        st.caption(f"{REGIME_ICON.get(regime.get('state'), '⚪')} Nifty 50 regime: {regime.get('state')}"
                   + (f" ({chg:+.2f}% today)" if chg is not None else ""))
        a, b = st.columns(2)
        a.metric("💰 Wallet (cash)", inr(S["cash"]))
        b.metric("📊 Equity", inr(equity), inr_signed(pnl))
    if rerun:
        st.rerun()


def history_section(S):
    st.divider()
    st.subheader("🧾 Trade history & wallet")
    trades = S["trades"]
    if not trades:
        st.caption("No closed trades yet.")
        return
    df = pd.DataFrame(trades)
    df = df[[c for c in TRADE_COLS if c in df.columns]]
    n = len(df)
    wins = int((pd.to_numeric(df["net_pnl"], errors="coerce") > 0).sum())
    total_net = float(pd.to_numeric(df["net_pnl"], errors="coerce").sum())
    a, b = st.columns(2)
    a.metric("Trades / Win rate", f"{n} / {wins / n * 100:.0f}%")
    b.metric("Total Net P&L", inr(total_net), inr_signed(total_net))
    if n >= 2:
        st.line_chart(pd.to_numeric(df["wallet_after"], errors="coerce"))
    st.dataframe(df.iloc[::-1], hide_index=True)
    st.download_button("⬇️ Download Trade History (CSV)", df.to_csv(index=False).encode("utf-8"),
                       file_name="trade_history.csv", mime="text/csv")


def sidebar():
    sb = st.sidebar
    sb.header("⚙️ Settings")
    sb.checkbox("Auto-pick next trade after an exit", value=True, key="auto_next")
    sb.slider("Minimum Win Score", 40, 80, 55, key="min_score")
    sb.checkbox("Test mode: allow entries when market is closed", value=False, key="test_mode")
    with sb.expander("📲 Telegram alerts (optional)"):
        st.text_input("Bot token", value=secret("TELEGRAM_TOKEN"), type="password", key="tg_token")
        st.text_input("Chat ID", value=secret("TELEGRAM_CHAT_ID"), key="tg_chat")
        if st.button("Send test alert", key="tg_test"):
            ok = send_telegram("✅ NSE Paper Bot: Telegram alerts are working.")
            st.success("Sent!") if ok else st.error("Failed - check token / chat ID.")
    with sb.expander("🏦 Zerodha Kite live orders (optional)"):
        st.caption("OFF by default. Real money. Needs `kiteconnect` in requirements.txt and a fresh daily access token.")
        st.checkbox("Enable LIVE orders", value=False, key="kite_live")
        st.text_input("API key", value=secret("KITE_API_KEY"), type="password", key="kite_key")
        st.text_input("Access token", value=secret("KITE_ACCESS_TOKEN"), type="password", key="kite_token")
        st.checkbox("I understand orders are real and stops are NOT placed at the broker", value=False, key="kite_confirm")
    with sb.expander("💾 Backup / reset"):
        up = st.file_uploader("Restore from history CSV", type="csv", key="restore_csv")
        if up is not None and st.button("Restore", key="restore_btn"):
            try:
                st.session_state.S = restore_state_from_df(pd.read_csv(up))
                save_state(st.session_state.S)
                st.rerun()
            except Exception as e:
                st.error(f"Restore failed: {e}")
        st.checkbox("Yes, wipe wallet & history", value=False, key="confirm_reset")
        if st.button("🗑 Reset bot", key="reset_btn") and st.session_state.get("confirm_reset"):
            try:
                if os.path.exists(STATE_FILE):
                    os.remove(STATE_FILE)
            except Exception:
                pass
            st.session_state.S = None
            st.rerun()


def start_screen():
    cap = st.number_input("Enter your capital / price (₹)", min_value=100.0, value=100.0, step=50.0, format="%.2f")
    if st.button("▶ Start Bot", type="primary", key="start_btn"):
        st.session_state.S = new_state(cap)
        save_state(st.session_state.S)
        st.rerun()


def main():
    st.set_page_config(page_title="NSE Paper Bot", page_icon="📈", layout="centered",
                       initial_sidebar_state="collapsed")
    if "S" not in st.session_state:
        st.session_state.S = load_state()
    sidebar()
    st.title("📈 NSE Paper Bot")
    S = st.session_state.S
    if S is None:
        start_screen()
    else:
        dashboard()
        history_section(S)


if __name__ == "__main__":
    main()
