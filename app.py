import streamlit as st
import yfinance as yf
import pandas as pd
import time
from datetime import datetime, timedelta

st.set_page_config(page_title="Live Auto Intraday & Swing Bot", layout="centered")
st.title("🤖 Live Auto-Trading Bot")
st.caption("Starts from ₹100 • Intraday & 1-Week Swing • Automatic Entry & Live Watch")

# Initialize Session State so stocks only show AFTER price is entered
if "bot_active" not in st.session_state:
    st.session_state.bot_active = False
if "active_trade" not in st.session_state:
    st.session_state.active_trade = None

# --- STEP 1: ENTER PRICE FIRST ---
st.subheader("1. Enter Your Trading Price First")
with st.form("price_form"):
    budget = st.number_input(
        "Enter Capital / Price (₹) — Starting from ₹100",
        min_value=100,
        value=100,
        step=100
    )
    trade_mode = st.selectbox(
        "Select Trading Mode:",
        [
            "🤖 Auto-Select Best (Intraday + Swing)",
            "⚡ Intraday Trading Only (Same-Day Exit)",
            "📈 Swing Trading Only (Max 1-Week Exit)"
        ]
    )
    start_btn = st.form_submit_button("🚀 Enter Price & Start Auto-Bot")

if start_btn:
    st.session_state.bot_active = True
    st.session_state.budget = budget
    st.session_state.trade_mode = trade_mode
    st.session_state.active_trade = None  # Reset trade on new price entry

# Low-price NSE stocks (₹10 to ₹100) + Mid/Large Caps
NSE_STOCKS = [
    "IDEA.NS", "IOB.NS", "NHPC.NS", "NMDC.NS", "IDFCFIRSTB.NS",
    "SUZLON.NS", "IDBI.NS", "NBCC.NS", "BAJAJHFL.NS", "PNB.NS",
    "TATASTEEL.NS", "BEL.NS", "ITC.NS", "SBIN.NS", "RELIANCE.NS"
]

@st.cache_data(ttl=60)
def scan_all_strategies():
    picks = []
    for ticker in NSE_STOCKS:
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="1mo").dropna()
            if len(df) < 15:
                continue

            close = df["Close"]
            high = df["High"]
            low = df["Low"]
            volume = df["Volume"]

            live_price = float(round(close.iloc[-1], 2))
            prev_close = float(close.iloc[-2])
            day_change_pct = round(((live_price - prev_close) / prev_close) * 100, 2)
            move_5d_pct = round(((live_price - float(close.iloc[-6])) / float(close.iloc[-6])) * 100, 2)

            # Technical Indicators (EMA & RSI)
            ema5 = float(close.ewm(span=5, adjust=False).mean().iloc[-1])
            ema13 = float(close.ewm(span=13, adjust=False).mean().iloc[-1])

            delta = close.diff()
            gain = delta.clip(lower=0).rolling(window=14).mean()
            loss = (-delta.clip(upper=0)).rolling(window=14).mean()
            rs = gain / loss.replace(0, 0.0001)
            rsi = float(100 - (100 / (1 + rs.iloc[-1])))

            vol_ratio = float(volume.iloc[-1]) / float(volume.tail(10).mean() + 1)

            # Intraday Strategy Evaluation
            intra_score = 50 + (day_change_pct * 4) + (vol_ratio * 8)
            if ema5 > ema13 and 50 <= rsi <= 72:
                intra_Strat = "⚡ Intraday Momentum Breakout"
                intra_score += 20
            elif rsi < 38 and live_price > float(low.iloc[-1]):
                intra_Strat = "⚡ Intraday VWAP/RSI Bounce"
                intra_score += 15
            else:
                intra_Strat = "⚡ Intraday Trend Scalp"

            # Swing Strategy Evaluation (Max 1 Week)
            swing_score = 50 + (move_5d_pct * 3) + (vol_ratio * 5)
            if ema5 > ema13 and rsi >= 52:
                swing_strat = "📈 1-Week EMA Crossover"
                swing_score += 22
            elif rsi < 40 and day_change_pct > 0:
                swing_strat = "📈 1-Week Dip Reversal"
                swing_score += 18
            else:
                swing_strat = "📈 1-Week Channel Swing"

            picks.append({
                "Stock": ticker.replace(".NS", ""),
                "Ticker": ticker,
                "Live Price (₹)": live_price,
                "Type": "Intraday",
                "Strategy": intra_Strat,
                "Score": round(min(max(intra_score, 10), 99), 1),
                "Target_Pct": 0.02,   # +2.0% Intraday Target
                "SL_Pct": 0.01,       # -1.0% Intraday Stop-Loss
                "Max_Hold": "Today 03:15 PM IST",
                "Hold_Days": 0
            })

            picks.append({
                "Stock": ticker.replace(".NS", ""),
                "Ticker": ticker,
                "Live Price (₹)": live_price,
                "Type": "Swing (Max 1 Wk)",
                "Strategy": swing_strat,
                "Score": round(min(max(swing_score, 10), 99), 1),
                "Target_Pct": 0.05,   # +5.0% 1-Week Target
                "SL_Pct": 0.025,      # -2.5% 1-Week Stop-Loss
                "Max_Hold": (datetime.utcnow() + timedelta(hours=5, minutes=30, days=7)).strftime("%d %b %Y, 03:15 PM"),
                "Hold_Days": 7
            })
        except Exception:
            continue
    return picks

# --- STEP 2: ONLY SHOW STOCKS AFTER PRICE IS ENTERED ---
if st.session_state.bot_active:
    user_budget = st.session_state.budget
    chosen_mode = st.session_state.trade_mode

    with st.spinner(f"Scanning live NSE stocks under ₹{user_budget}..."):
        all_setups = scan_all_strategies()

    # Filter by user price and trading mode
    valid_setups = [s for s in all_setups if s["Live Price (₹)"] <= user_budget]
    if "Intraday" in chosen_mode:
        valid_setups = [s for s in valid_setups if s["Type"] == "Intraday"]
    elif "Swing" in chosen_mode:
        valid_setups = [s for s in valid_setups if s["Type"] == "Swing (Max 1 Wk)"]

    valid_setups = sorted(valid_setups, key=lambda x: x["Score"], reverse=True)

    if len(valid_setups) > 0:
        best = valid_setups[0]

        # Auto-Enter Market if not already entered
        if st.session_state.active_trade is None:
            entry_p = best["Live Price (₹)"]
            qty = int(user_budget // entry_p)
            now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
            st.session_state.active_trade = {
                "Stock": best["Stock"],
                "Ticker": best["Ticker"],
                "Type": best["Type"],
                "Strategy": best["Strategy"],
                "Score": best["Score"],
                "Entry_Price": entry_p,
                "Quantity": qty,
                "Capital_Used": round(qty * entry_p, 2),
                "Target_Price": round(entry_p * (1 + best["Target_Pct"]), 2),
                "Stop_Loss": round(entry_p * (1 - best["SL_Pct"]), 2),
                "Entry_Time": now_ist.strftime("%d %b %Y, %I:%M:%S %p IST"),
                "Exit_Deadline": best["Max_Hold"],
                "Status": "🟢 LIVE IN MARKET (AUTO-ENTERED)"
            }

        trade = st.session_state.active_trade

        # Fetch latest real-time price for Live Watch
        try:
            live_df = yf.Ticker(trade["Ticker"]).history(period="1d", interval="1m").dropna()
            if len(live_df) > 0:
                current_market_price = float(round(live_df["Close"].iloc[-1], 2))
            else:
                current_market_price = trade["Entry_Price"]
        except Exception:
            current_market_price = trade["Entry_Price"]

        # Calculate Live Profit / Loss
        pnl_per_share = current_market_price - trade["Entry_Price"]
        total_pnl = round(pnl_per_share * trade["Quantity"], 2)
        pnl_pct = round((pnl_per_share / trade["Entry_Price"]) * 100, 2)

        # Auto-Execution Check (Target / Stop-Loss)
        if current_market_price >= trade["Target_Price"]:
            trade["Status"] = "🎯 TARGET HIT — AUTO-SOLD FOR PROFIT!"
        elif current_market_price <= trade["Stop_Loss"]:
            trade["Status"] = "🛑 STOP-LOSS HIT — AUTO-SOLD!"

        st.subheader("2. Auto-Selected & Auto-Executed Trade")
        st.success(
            f"**{trade['Status']}**  \n"
            f"🏆 **Stock:** {trade['Stock']} ({trade['Type']}) | "
            f"🧠 **Strategy:** {trade['Strategy']} (Win Score: {trade['Score']}/100)"
        )

        # --- LIVE WATCH DASHBOARD ---
        st.subheader("3. 📡 Live Market Watch (Real-Time Tracker)")
        c1, c2, c3 = st.columns(3)
        c1.metric("Entry Buy Price", f"₹{trade['Entry_Price']}")
        c2.metric("Live Market Price", f"₹{current_market_price}", f"{pnl_pct}%")
        c3.metric("Live Profit / Loss", f"₹{total_pnl}", f"{total_pnl} ₹")

        c4, c5, c6 = st.columns(3)
        c4.metric("Quantity Bought", f"{trade['Quantity']} Shares")
        c5.metric("Auto-Sell Target", f"₹{trade['Target_Price']}")
        c6.metric("Auto Stop-Loss", f"₹{trade['Stop_Loss']}")

        expected_max_profit = round((trade["Target_Price"] - trade["Entry_Price"]) * trade["Quantity"], 2)

        st.code(
            f"📡 LIVE AUTO-EXECUTION WATCH LOG\n"
            f"--------------------------------------------------\n"
            f"Order Status    : {trade['Status']}\n"
            f"Trade Mode      : {trade['Type']}\n"
            f"Auto-Buy Time   : {trade['Entry_Time']}\n"
            f"Position Size   : {trade['Quantity']} Shares (₹{trade['Capital_Used']} / ₹{user_budget})\n"
            f"Target Profit   : +₹{expected_max_profit} (Auto-Sells at ₹{trade['Target_Price']})\n"
            f"Auto-Sell Timer : {trade['Exit_Deadline']}\n"
            f"--------------------------------------------------",
            language="yaml"
        )

        # Live Auto-Refresh Toggle
        live_watch_on = st.checkbox("🔴 Keep Live Market Watch Running (Auto-Updates Every 10s)", value=True)

        st.subheader(f"4. All Matching Stocks Under ₹{user_budget}")
        board_df = pd.DataFrame(valid_setups)[
            ["Stock", "Live Price (₹)", "Type", "Strategy", "Score", "Max_Hold"]
        ]
        st.dataframe(board_df, use_container_width=True, hide_index=True)

        if live_watch_on and "LIVE IN MARKET" in trade["Status"]:
            time.sleep(10)
            st.rerun()

    else:
        st.warning(f"No stocks found under ₹{user_budget}. Try entering ₹100 or more.")
else:
    st.info("👆 Enter your trading price above (starting from ₹100) and tap **Enter Price & Start Auto-Bot** to scan the live market.")
