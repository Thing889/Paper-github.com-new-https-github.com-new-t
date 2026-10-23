
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(
    page_title="Algo Paper Trader",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Algo Paper Trader")
st.caption("Swing-trading research dashboard · Paper trading only")

st.warning(
    "SIMULATION ONLY — This app does not connect to Zerodha, "
    "does not fetch live prices, and cannot place real orders. "
    "Signals are for research, not financial advice."
)

# -------------------- Sidebar settings --------------------
st.sidebar.header("Strategy settings")

capital = st.sidebar.number_input(
    "Virtual starting capital (₹)",
    min_value=1000,
    max_value=10000000,
    value=25000,
    step=1000,
)

fast_window = st.sidebar.slider(
    "Fast moving average (days)", 2, 50, 10
)
slow_window = st.sidebar.slider(
    "Slow moving average (days)", 5, 200, 30
)

cost_bps = st.sidebar.number_input(
    "Estimated cost per trade side (basis points)",
    min_value=0.0,
    max_value=100.0,
    value=10.0,
    step=1.0,
    help="10 basis points = 0.10%. This is an assumption, not a quote.",
)

if fast_window >= slow_window:
    st.sidebar.error("Fast moving average must be shorter than slow.")
    st.stop()

# -------------------- Demo data --------------------
def make_demo_data():
    """Synthetic example prices. These are NOT real market prices."""
    rng = np.random.default_rng(7)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=300)
    daily_returns = rng.normal(0.0004, 0.018, len(dates))
    close = 200 * np.cumprod(1 + daily_returns)

    return pd.DataFrame({
        "date": dates,
        "symbol": "DEMO",
        "open": close * (1 + rng.normal(0, 0.003, len(dates))),
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": rng.integers(100000, 1000000, len(dates)),
    })

# -------------------- Data input --------------------
st.subheader("1. Choose your price data")

data_source = st.radio(
    "Data source",
    ["Try synthetic demo data", "Upload historical CSV"],
    horizontal=True,
)

st.caption(
    "Demo prices are randomly generated for testing the dashboard. "
    "They are not actual NSE prices and must not be used to judge "
    "whether the strategy is profitable."
)

uploaded_file = None
if data_source == "Upload historical CSV":
    uploaded_file = st.file_uploader(
        "Upload a CSV file",
        type=["csv"],
        help=(
            "Required columns: date, symbol, open, high, low, "
            "close, volume. Dates and prices must be valid."
        ),
    )

    if uploaded_file is None:
        st.info("Upload your CSV to run a backtest.")
        st.stop()

    try:
        raw = pd.read_csv(uploaded_file)
    except Exception as exc:
        st.error(f"Could not read the CSV: {exc}")
        st.stop()
else:
    raw = make_demo_data()

raw.columns = [str(c).strip().lower() for c in raw.columns]

required = {"date", "symbol", "close"}
missing = required - set(raw.columns)
if missing:
    st.error(
        "Your CSV is missing required column(s): "
        + ", ".join(sorted(missing))
    )
    st.stop()

raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
raw["symbol"] = raw["symbol"].astype(str).str.strip().str.upper()
raw["close"] = pd.to_numeric(raw["close"], errors="coerce")

raw = raw.dropna(subset=["date", "symbol", "close"])
raw = raw[(raw["symbol"] != "") & (raw["close"] > 0)]
raw = raw.sort_values(["symbol", "date"])

if raw.empty:
    st.error("No valid price rows found in the data.")
    st.stop()

symbols = sorted(raw["symbol"].unique().tolist())
selected_symbol = st.selectbox("Select a symbol", symbols)

prices = raw[raw["symbol"] == selected_symbol].copy()
prices = prices.drop_duplicates(subset=["date"], keep="last")
prices = prices.sort_values("date").reset_index(drop=True)

if len(prices) <= slow_window + 2:
    st.error(
        f"Not enough data for a {slow_window}-day moving average. "
        f"Please upload more historical rows."
    )
    st.stop()

# -------------------- Backtest --------------------
prices["fast_ma"] = prices["close"].rolling(
    window=fast_window, min_periods=fast_window
).mean()

prices["slow_ma"] = prices["close"].rolling(
    window=slow_window, min_periods=slow_window
).mean()

# Signal is 1 when fast MA is above slow MA; otherwise stay out.
prices["signal"] = (
    (prices["fast_ma"] > prices["slow_ma"])
    & prices["slow_ma"].notna()
).astype(int)

# Use yesterday's signal for today's return to avoid look-ahead bias.
prices["position"] = prices["signal"].shift(1).fillna(0)

prices["market_return"] = prices["close"].pct_change().fillna(0)
prices["turnover"] = prices["position"].diff().abs()
prices["turnover"] = prices["turnover"].fillna(0)

cost_rate = cost_bps / 10000.0
prices["strategy_return"] = (
    prices["position"] * prices["market_return"]
    - prices["turnover"] * cost_rate
)

prices["equity"] = capital * (1 + prices["strategy_return"]).cumprod()
prices["buy_hold_equity"] = capital * (
    1 + prices["market_return"]
).cumprod()

prices["peak"] = prices["equity"].cummax()
prices["drawdown"] = prices["equity"] / prices["peak"] - 1

# -------------------- Results --------------------
start_equity = float(prices["equity"].iloc[0])
final_equity = float(prices["equity"].iloc[-1])
net_pnl = final_equity - capital
total_return = (final_equity / capital - 1) * 100
max_drawdown = float(prices["drawdown"].min()) * 100

days = max((prices["date"].iloc[-1] - prices["date"].iloc[0]).days, 1)
years = days / 365.25
if years > 0 and final_equity > 0:
    cagr = ((final_equity / capital) ** (1 / years) - 1) * 100
else:
    cagr = 0.0

entries = (
    (prices["position"] == 1)
    & (prices["position"].shift(1).fillna(0) == 0)
).sum()

exits = (
    (prices["position"] == 0)
    & (prices["position"].shift(1).fillna(0) == 1)
).sum()

st.subheader("2. Backtest results")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Virtual final equity", f"₹{final_equity:,.2f}")
c2.metric("Net P&L vs starting capital", f"₹{net_pnl:,.2f}")
c3.metric("Total return", f"{total_return:.2f}%")
c4.metric("Maximum drawdown", f"{max_drawdown:.2f}%")

c5, c6, c7 = st.columns(3)
c5.metric("Annualized return (approx.)", f"{cagr:.2f}%")
c6.metric("Entry signals", int(entries))
c7.metric("Exit signals", int(exits))

st.caption(
    f"Symbol: {selected_symbol} · "
    f"Rows: {len(prices)} · "
    f"Estimated cost: {cost_bps:.1f} bps per side · "
    f"Strategy: long when fast MA is above slow MA."
)

# -------------------- Charts --------------------
st.subheader("3. Equity curve")

fig_equity = go.Figure()
fig_equity.add_trace(go.Scatter(
    x=prices["date"],
    y=prices["equity"],
    mode="lines",
    name="Strategy (after estimated costs)",
))
fig_equity.add_trace(go.Scatter(
    x=prices["date"],
    y=prices["buy_hold_equity"],
    mode="lines",
    name="Buy and hold (comparison)",
    line=dict(dash="dash"),
))
fig_equity.add_hline(
    y=capital,
    line_dash="dot",
    annotation_text="Starting capital",
)
fig_equity.update_layout(
    xaxis_title="Date",
    yaxis_title="Portfolio value (₹)",
    hovermode="x unified",
    legend_title="",
)
st.plotly_chart(fig_equity, use_container_width=True)

st.subheader("4. Drawdown")

fig_dd = px.area(
    prices,
    x="date",
    y=prices["drawdown"] * 100,
    labels={"date": "Date", "y": "Drawdown (%)"},
)
fig_dd.update_layout(yaxis_title="Drawdown (%)")
st.plotly_chart(fig_dd, use_container_width=True)

# -------------------- Signals and data --------------------
st.subheader("5. Latest signal")

latest = prices.iloc[-1]
if latest["signal"] == 1:
    st.success(
        f"{selected_symbol}: FAST MA ABOVE SLOW MA — "
        "the strategy's current rule is LONG / IN POSITION."
    )
else:
    st.info(
        f"{selected_symbol}: FAST MA NOT ABOVE SLOW MA — "
        "the strategy's current rule is OUT / NO POSITION."
    )

st.caption(
    "This is a rule-based historical signal, not a live quote or "
    "a recommendation to buy or sell. Check current prices and "
    "your own risk limits independently."
)

st.subheader("6. Recent data and simulated positions")

display = prices[[
    "date", "symbol", "close", "fast_ma", "slow_ma",
    "signal", "position", "strategy_return", "equity", "drawdown"
]].copy()

display["date"] = display["date"].dt.strftime("%Y-%m-%d")
display = display.rename(columns={
    "date": "Date",
    "symbol": "Symbol",
    "close": "Close",
    "fast_ma": "Fast MA",
    "slow_ma": "Slow MA",
    "signal": "Signal (0/1)",
    "position": "Position (0/1)",
    "strategy_return": "Daily strategy return",
    "equity": "Virtual equity (₹)",
    "drawdown": "Drawdown (decimal)",
})

st.dataframe(display.tail(30), use_container_width=True)

csv_bytes = prices.to_csv(index=False).encode("utf-8")
st.download_button(
    "Download backtest results as CSV",
    data=csv_bytes,
    file_name=f"{selected_symbol.lower()}_paper_backtest.csv",
    mime="text/csv",
)

st.subheader("7. Important limitations")
st.markdown(
    """
    - This is a simple moving-average crossover example, not a proven
      profitable strategy.
    - Historical simulations do not predict future returns.
    - Brokerage, taxes, slippage, liquidity, and real execution may
      differ from the estimated cost entered above.
    - The simulator models one selected symbol at a time and does not
      calculate portfolio-wide allocation across multiple stocks.
    - No live market feed, Zerodha connection, automatic alerts, or
      real-order execution is included.
    - Demo data is synthetic. Upload reliable historical prices before
      interpreting any backtest.
    """
)

st.caption("Algo Paper Trader · Educational use only")
