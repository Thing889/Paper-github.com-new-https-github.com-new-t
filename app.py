import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, time as dtime, timedelta
import pytz
import requests
import time

# ==============================================================================
# 1. PAGE CONFIG & MOBILE-FIRST CSS STYLING
# ==============================================================================
st.set_page_config(
    page_title="NSE Pro Algo Bot | Entry & Exit Alert Engine",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 3rem !important;
        max-width: 720px;
    }
    .bot-card {
        background: linear-gradient(145deg, #111827, #1f2937);
        border: 1px solid #374151;
        border-radius: 14px;
        padding: 16px;
        margin-bottom: 14px;
        color: #f9fafb;
        box-shadow: 0 4px 12px rgba(0,0,0,0.35);
    }
    .top-pick-card {
        background: linear-gradient(145deg, #064e3b, #022c22);
        border: 2px solid #10b981;
        border-radius: 16px;
        padding: 18px;
        margin-bottom: 16px;
        color: #ecfdf5;
        box-shadow: 0 6px 18px rgba(16,185,129,0.25);
    }
    .alert-entry-now {
        background: linear-gradient(145deg, #065f46, #047857);
        border: 2px solid #34d399;
        border-radius: 14px;
        padding: 18px;
        margin: 12px 0;
        color: #ffffff;
        text-align: center;
        animation: pulse-green 1.8s infinite;
    }
    .alert-exit-now {
        background: linear-gradient(145deg, #7f1d1d, #991b1b);
        border: 2px solid #f87171;
        border-radius: 14px;
        padding: 18px;
        margin: 12px 0;
        color: #ffffff;
        text-align: center;
        animation: pulse-red 1.5s infinite;
    }
    .alert-wait-box {
        background: linear-gradient(145deg, #1e293b, #0f172a);
        border: 1px solid #f59e0b;
        border-radius: 14px;
        padding: 16px;
        margin: 12px 0;
        color: #fef3c7;
        text-align: center;
    }
    @keyframes pulse-green {
        0% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.6); }
        70% { box-shadow: 0 0 0 12px rgba(52, 211, 153, 0); }
        100% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0); }
    }
    @keyframes pulse-red {
        0% { box-shadow: 0 0 0 0 rgba(248, 113, 113, 0.7); }
        70% { box-shadow: 0 0 0 12px rgba(248, 113, 113, 0); }
        100% { box-shadow: 0 0 0 0 rgba(248, 113, 113, 0); }
    }
    .badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 700;
        margin-right: 6px;
        margin-bottom: 4px;
    }
    .badge-green { background-color: #10b981; color: #022c22; }
    .badge-yellow { background-color: #f59e0b; color: #451a03; }
    .badge-red { background-color: #ef4444; color: #ffffff; }
    .badge-blue { background-color: #3b82f6; color: #ffffff; }
    .metric-row {
        display: flex;
        justify-content: space-between;
        border-bottom: 1px solid rgba(255,255,255,0.1);
        padding: 6px 0;
        font-size: 0.92rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ==============================================================================
# 2. NSE STOCK UNIVERSE (₹10–₹100 BUDGET + MID/LARGE CAPS)
# ==============================================================================
NSE_STOCK_UNIVERSE = {
    # Budget & Low-Ticket Liquid NSE Stocks (₹10 - ₹150 range)
    "IDEA.NS": {"name": "Vodafone Idea", "tier": "Budget (₹10–₹100)", "fallback_price": 14.20},
    "IOB.NS": {"name": "Indian Overseas Bank", "tier": "Budget (₹10–₹100)", "fallback_price": 56.40},
    "SUZLON.NS": {"name": "Suzlon Energy", "tier": "Budget (₹10–₹100)", "fallback_price": 62.80},
    "NHPC.NS": {"name": "NHPC Ltd", "tier": "Budget (₹10–₹100)", "fallback_price": 84.50},
    "IDFCFIRSTB.NS": {"name": "IDFC First Bank", "tier": "Budget (₹10–₹100)", "fallback_price": 72.30},
    "PNB.NS": {"name": "Punjab National Bank", "tier": "Budget (₹10–₹150)", "fallback_price": 104.20},
    "NBCC.NS": {"name": "NBCC (India)", "tier": "Budget (₹10–₹150)", "fallback_price": 94.60},
    "NMDC.NS": {"name": "NMDC Ltd", "tier": "Budget/Mid (₹60–₹250)", "fallback_price": 74.80},
    "UCOBANK.NS": {"name": "UCO Bank", "tier": "Budget (₹10–₹100)", "fallback_price": 46.90},
    "MAHABANK.NS": {"name": "Bank of Maharashtra", "tier": "Budget (₹10–₹100)", "fallback_price": 54.10},
    # Liquid Large Caps (₹150+)
    "TATASTEEL.NS": {"name": "Tata Steel", "tier": "Large Cap", "fallback_price": 152.40},
    "BEL.NS": {"name": "Bharat Electronics", "tier": "Large Cap", "fallback_price": 292.50},
    "ITC.NS": {"name": "ITC Ltd", "tier": "Large Cap", "fallback_price": 438.00},
    "ONGC.NS": {"name": "ONGC Ltd", "tier": "Large Cap", "fallback_price": 264.00},
    "NTPC.NS": {"name": "NTPC Ltd", "tier": "Large Cap", "fallback_price": 362.00},
    "SBIN.NS": {"name": "State Bank of India", "tier": "Large Cap", "fallback_price": 812.00},
    "TATAMOTORS.NS": {"name": "Tata Motors", "tier": "Large Cap", "fallback_price": 785.00},
    "RELIANCE.NS": {"name": "Reliance Industries", "tier": "Large Cap", "fallback_price": 1320.00},
}

# ==============================================================================
# 3. SESSION STATE INITIALIZATION
# ==============================================================================
if "capital_submitted" not in st.session_state:
    st.session_state.capital_submitted = False
if "user_capital" not in st.session_state:
    st.session_state.user_capital = 500.0
if "strategy_choice" not in st.session_state:
    st.session_state.strategy_choice = "BOTH (Auto-Rank Best)"
if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = None
if "selected_strategy" not in st.session_state:
    st.session_state.selected_strategy = None
if "stock_locked" not in st.session_state:
    st.session_state.stock_locked = False
if "trade_start_time" not in st.session_state:
    st.session_state.trade_start_time = None
if "highest_price_seen" not in st.session_state:
    st.session_state.highest_price_seen = 0.0
if "trailing_sl_price" not in st.session_state:
    st.session_state.trailing_sl_price = 0.0
if "trailing_sl_stage" not in st.session_state:
    st.session_state.trailing_sl_stage = "Initial SL"
if "sent_alerts" not in st.session_state:
    st.session_state.sent_alerts = set()
if "enable_sound" not in st.session_state:
    st.session_state.enable_sound = True
if "tg_bot_token" not in st.session_state:
    st.session_state.tg_bot_token = ""
if "tg_chat_id" not in st.session_state:
    st.session_state.tg_chat_id = ""

# ==============================================================================
# 4. SMART IST MARKET CLOCK & OPENING TRAP ENGINE
# ==============================================================================
def get_ist_now() -> datetime:
    ist_tz = pytz.timezone("Asia/Kolkata")
    return datetime.now(ist_tz)


def get_market_clock_status() -> dict:
    now = get_ist_now()
    weekday = now.weekday()  # 0 = Mon ... 6 = Sun
    current_t = now.time()

    t_open = dtime(9, 15)
    t_trap_end = dtime(9, 25)
    t_morning_end = dtime(11, 30)
    t_midday_end = dtime(13, 30)
    t_entry_cutoff = dtime(15, 0)
    t_square_off = dtime(15, 15)
    t_close = dtime(15, 30)

    def format_td(target_dt: datetime) -> str:
        diff = max(0, int((target_dt - now).total_seconds()))
        hrs, rem = divmod(diff, 3600)
        mins, secs = divmod(rem, 60)
        if hrs > 0:
            return f"{hrs}h {mins}m {secs}s"
        return f"{mins}m {secs}s"

    # Weekend check
    if weekday >= 5:
        days_ahead = 7 - weekday
        next_open = (now + timedelta(days=days_ahead)).replace(
            hour=9, minute=15, second=0, microsecond=0
        )
        return {
            "now_str": now.strftime("%d %b %Y | %I:%M:%S %p IST"),
            "phase": "WEEKEND_CLOSED",
            "badge": "🌙 MARKET CLOSED (WEEKEND)",
            "color": "yellow",
            "can_enter_intraday": False,
            "is_opening_trap": False,
            "is_square_off": False,
            "message": "NSE is closed for the weekend. Bot is scanning Friday's closing data so you can lock your stock and test alerts.",
            "countdown_label": "Next NSE Opening (Mon 9:15 AM IST)",
            "countdown": format_td(next_open),
        }

    # Pre-market (< 9:15 AM)
    if current_t < t_open:
        today_safe = now.replace(hour=9, minute=25, second=0, microsecond=0)
        return {
            "now_str": now.strftime("%d %b %Y | %I:%M:%S %p IST"),
            "phase": "PRE_MARKET",
            "badge": "⏳ PRE-MARKET PREP",
            "color": "yellow",
            "can_enter_intraday": False,
            "is_opening_trap": False,
            "is_square_off": False,
            "message": "Market opens at 9:15 AM IST. Wait until 9:25 AM IST to avoid the Opening Trap.",
            "countdown_label": "Safe Entry Window Starts In",
            "countdown": format_td(today_safe),
        }

    # Opening Trap (9:15 AM - 9:25 AM)
    if t_open <= current_t < t_trap_end:
        trap_end_dt = now.replace(hour=9, minute=25, second=0, microsecond=0)
        return {
            "now_str": now.strftime("%d %b %Y | %I:%M:%S %p IST"),
            "phase": "OPENING_TRAP",
            "badge": "🚨 OPENING TRAP FILTER ACTIVE (9:15–9:25 AM)",
            "color": "red",
            "can_enter_intraday": False,
            "is_opening_trap": True,
            "is_square_off": False,
            "message": "DO NOT BUY YET! Institutional stop-hunting & wide spreads occur between 9:15–9:25 AM IST. Bot has locked Entry Alerts until 9:25 AM.",
            "countdown_label": "Safe Entry Unlocks In",
            "countdown": format_td(trap_end_dt),
        }

    # Prime Morning Window (9:25 AM - 11:30 AM)
    if t_trap_end <= current_t < t_morning_end:
        sq_dt = now.replace(hour=15, minute=15, second=0, microsecond=0)
        return {
            "now_str": now.strftime("%d %b %Y | %I:%M:%S %p IST"),
            "phase": "PRIME_MORNING",
            "badge": "🟢 PRIME ENTRY WINDOW (9:25–11:30 AM)",
            "color": "green",
            "can_enter_intraday": True,
            "is_opening_trap": False,
            "is_square_off": False,
            "message": "High-probability institutional momentum window active. Enter when price + volume criteria match.",
            "countdown_label": "Intraday Square-Off (3:15 PM) In",
            "countdown": format_td(sq_dt),
        }

    # Mid-Day Zone (11:30 AM - 1:30 PM)
    if t_morning_end <= current_t < t_midday_end:
        aft_dt = now.replace(hour=13, minute=30, second=0, microsecond=0)
        return {
            "now_str": now.strftime("%d %b %Y | %I:%M:%S %p IST"),
            "phase": "MIDDAY_LULL",
            "badge": "🟡 MID-DAY CONSOLIDATION (11:30 AM–1:30 PM)",
            "color": "yellow",
            "can_enter_intraday": True,
            "is_opening_trap": False,
            "is_square_off": False,
            "message": "Mid-day volume lull. Bot strictly requires Volume-Backed Fakeout Filter >= 1.0x before firing Entry Alert.",
            "countdown_label": "Afternoon Breakout Window In",
            "countdown": format_td(aft_dt),
        }

    # Afternoon Breakout Window (1:30 PM - 3:00 PM)
    if t_midday_end <= current_t < t_entry_cutoff:
        sq_dt = now.replace(hour=15, minute=15, second=0, microsecond=0)
        return {
            "now_str": now.strftime("%d %b %Y | %I:%M:%S %p IST"),
            "phase": "AFTERNOON_SESSION",
            "badge": "🟢 AFTERNOON BREAKOUT WINDOW (1:30–3:00 PM)",
            "color": "green",
            "can_enter_intraday": True,
            "is_opening_trap": False,
            "is_square_off": False,
            "message": "Strong window for 1-Week Swing entries and final Intraday momentum breakouts.",
            "countdown_label": "Intraday Square-Off (3:15 PM) In",
            "countdown": format_td(sq_dt),
        }

    # Late Session Warning (3:00 PM - 3:15 PM)
    if t_entry_cutoff <= current_t < t_square_off:
        sq_dt = now.replace(hour=15, minute=15, second=0, microsecond=0)
        return {
            "now_str": now.strftime("%d %b %Y | %I:%M:%S %p IST"),
            "phase": "PRE_SQUAREOFF",
            "badge": "🟠 NO NEW INTRADAY ENTRIES (3:00–3:15 PM)",
            "color": "yellow",
            "can_enter_intraday": False,
            "is_opening_trap": False,
            "is_square_off": False,
            "message": "Too close to 3:15 PM Intraday auto-square-off. Only 1-Week Swing (Delivery) entries are safe now.",
            "countdown_label": "Mandatory Intraday Exit In",
            "countdown": format_td(sq_dt),
        }

    # Intraday Square-Off Window (3:15 PM - 3:30 PM)
    if t_square_off <= current_t <= t_close:
        close_dt = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return {
            "now_str": now.strftime("%d %b %Y | %I:%M:%S %p IST"),
            "phase": "SQUARE_OFF_NOW",
            "badge": "🔴 INTRADAY SQUARE-OFF TIME (3:15 PM HIT)",
            "color": "red",
            "can_enter_intraday": False,
            "is_opening_trap": False,
            "is_square_off": True,
            "message": "3:15 PM IST reached! Exit all Intraday MIS positions immediately to avoid Zerodha ₹50 + GST auto-square-off penalty.",
            "countdown_label": "Market Closes In",
            "countdown": format_td(close_dt),
        }

    # Post-Market (> 3:30 PM)
    next_days = 3 if weekday == 4 else 1
    next_open = (now + timedelta(days=next_days)).replace(
        hour=9, minute=15, second=0, microsecond=0
    )
    return {
        "now_str": now.strftime("%d %b %Y | %I:%M:%S %p IST"),
        "phase": "POST_MARKET",
        "badge": "🌙 AFTER-HOURS ANALYSIS & PREP MODE",
        "color": "blue",
        "can_enter_intraday": False,
        "is_opening_trap": False,
        "is_square_off": False,
        "message": "Market is closed (3:30 PM IST). Showing latest confirmed NSE closing prices. Use the Live Simulator in Step 3 to test Entry/Exit alerts.",
        "countdown_label": "Next Market Open In",
        "countdown": format_td(next_open),
    }


# ==============================================================================
# 5. ZERODHA REAL NET PROFIT & TAX CALCULATOR
# ==============================================================================
def calculate_zerodha_net_profit(
    buy_price: float,
    sell_price: float,
    qty: int,
    strategy_type: str,
) -> dict:
    """
    Calculates exact Zerodha Brokerage, STT, NSE Transaction Charges,
    SEBI Charges, Stamp Duty, and 18% GST for Intraday (MIS) vs Swing (CNC).
    """
    qty = max(1, int(qty))
    buy_turnover = float(buy_price) * qty
    sell_turnover = float(sell_price) * qty
    total_turnover = buy_turnover + sell_turnover
    gross_pnl = sell_turnover - buy_turnover

    if "Intraday" in strategy_type:
        # Zer
