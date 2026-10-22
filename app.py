
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Paper Trading Bot", layout="centered")
st.title("🤖 Algo Paper Trader")

st.subheader("1. Risk Management")
capital = st.number_input("Total Capital (₹)", value=50000, step=1000)
risk_pct = st.number_input("Risk Per Trade (%)", value=1.0, step=0.1)

st.subheader("2. Live Screener")
st.write("Scanning Reliance for momentum setups...")

stock = yf.Ticker("RELIANCE.NS")
df = stock.history(period="20d")

if len(df) > 10:
    latest_close = round(df['Close'].iloc[-1], 2)
    stop_loss = round(latest_close * 0.98, 2)
    target = round(latest_close * 1.04, 2)
    
    st.success("**Signal Found:** RELIANCE")
    st.write(f"**Live Entry:** ₹{latest_close} | **SL:** ₹{stop_loss} | **Target:** ₹{target}")
    
    risk_amount = capital * (risk_pct / 100)
    risk_per_share = latest_close - stop_loss
    
    if risk_per_share > 0:
        quantity = int(risk_amount / risk_per_share)
    else:
        quantity = 0
        
    st.subheader("3. Position Sizing")
    st.metric(label="Calculated Quantity to Buy", value=quantity)
    
    st.subheader("4. Execution")
    if st.button("Trigger Paper Trade"):
        if quantity > 0:
            st.success("Trade Executed Successfully!")
            st.code(f"🟢 BUY {quantity} shares at ₹{latest_close}", language="markdown")
        else:
            st.error("Invalid Setup. Risk per share is 0.")
else:
    st.warning("Market data currently unavailable.")
