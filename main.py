import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import time
import plotly.graph_objects as go

st.set_page_config(page_title="Multi-Exchange Intraday Engine", layout="wide")
st.title("🌎 Multi-Exchange Semi-Automated Intraday Engine (TSX/NASDAQ/NYSE)")

# --- SETTINGS ---
INITIAL_CAPITAL = 100000
TOP_N = 5
REFRESH_INTERVAL = 60  # seconds
STOP_LOSS = 0.5
TAKE_PROFIT = 1.0
TRAILING_STOP = True

# --- SESSION STATE ---
if "equity_curve" not in st.session_state:
    st.session_state.equity_curve = [INITIAL_CAPITAL]
if "capital" not in st.session_state:
    st.session_state.capital = INITIAL_CAPITAL
if "positions" not in st.session_state:
    st.session_state.positions = {}
if "alerts" not in st.session_state:
    st.session_state.alerts = []

# --- STOCK LISTS ---
TSX = ["SHOP.TO","SU.TO","RY.TO","TD.TO","BNS.TO","ENB.TO","CNQ.TO","CP.TO","CNR.TO","BAM.TO"]
NASDAQ = ["AAPL","MSFT","AMZN","GOOG","NVDA","TSLA","FB","INTC","AMD","NFLX"]
NYSE = ["JNJ","PG","DIS","V","MA","KO","PFE","BAC","XOM","WMT"]

stocks = {"TSX": TSX, "NASDAQ": NASDAQ, "NYSE": NYSE}

# --- SIGNAL FUNCTION ---
def generate_signal(df):
    df["EMA10"] = ta.trend.ema_indicator(df["Close"], 10)
    df["EMA30"] = ta.trend.ema_indicator(df["Close"], 30)
    df["RSI7"] = ta.momentum.rsi(df["Close"], 7)
    last = df.iloc[-1]
    signal = 0
    score = 0
    if last["EMA10"] > last["EMA30"] and last["RSI7"] < 70:
        signal = 1
        score = ((last["EMA10"] - last["EMA30"]) / last["EMA30"]) * 100 + (70 - last["RSI7"])
    elif last["EMA10"] < last["EMA30"] and last["RSI7"] > 30:
        signal = -1
        score = ((last["EMA30"] - last["EMA10"]) / last["EMA10"]) * 100 + (last["RSI7"] - 30)
    return signal, last["Close"], score, df

# --- FETCH DATA & GENERATE SIGNALS PER EXCHANGE ---
exchange_results = {}
for exchange, tickers in stocks.items():
    results = []
    for ticker in tickers:
        try:
            df = yf.download(ticker, period="7d", interval="5m", progress=False)
            if df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            signal, price, score, df = generate_signal(df)
            results.append({"Stock": ticker, "Signal": signal, "Price": price, "Score": score, "DF": df})
        except Exception as e:
            st.write(f"Error fetching {ticker}: {e}")
    exchange_results[exchange] = pd.DataFrame(results)

# --- CREATE TABS PER EXCHANGE ---
tabs = st.tabs(["TSX", "NASDAQ", "NYSE"])
for i, exchange in enumerate(["TSX", "NASDAQ", "NYSE"]):
    with tabs[i]:
        df = exchange_results[exchange]
        if df.empty:
            st.warning(f"No valid intraday data for {exchange} stocks.")
            continue

        # --- TOP BUY SIGNALS ---
        buy_signals = df[df["Signal"]==1].sort_values(by="Score", ascending=False).head(TOP_N)
        top_signals_list = []
        for _, row in buy_signals.iterrows():
            buy_price = row["Price"]
            sell_price = buy_price * (1 + TAKE_PROFIT/100)
            top_signals_list.append({
                "Stock": row["Stock"],
                "Buy Price": round(buy_price,2),
                "Sell Price": round(sell_price,2),
                "Score": round(row["Score"],2)
            })
        df_top_signals = pd.DataFrame(top_signals_list)
        st.subheader(f"🏆 Top {TOP_N} Buy Signals - {exchange}")
        st.dataframe(df_top_signals)

        # --- OPEN POSITIONS BASED ON TOP SIGNALS ---
        total_score = df_top_signals["Score"].sum() if not df_top_signals.empty else 1
        for _, row in df_top_signals.iterrows():
            ticker = row["Stock"]
            price = row["Buy Price"]
            score = row["Score"]
            allocation = st.session_state.capital * (score / total_score)
            shares = allocation // price
            if ticker not in st.session_state.positions:
                st.session_state.positions[ticker] = []
            st.session_state.positions[ticker].append({
                "entry": price,
                "shares": shares,
                "status": "open",
                "stop_loss": price * (1 - STOP_LOSS/100),
                "take_profit": price * (1 + TAKE_PROFIT/100),
                "trailing_stop": price * (1 - STOP_LOSS/100)
            })
            st.session_state.alerts.append(f"🔔 New BUY position for {ticker} at ${price:.2f}")

        # --- INTRADAY CHARTS ---
        st.subheader(f"📊 Intraday Charts - {exchange} Top Buys")
        for _, row in buy_signals.iterrows():
            ticker = row["Stock"]
            df_c = row["DF"]
            pos_list = st.session_state.positions.get(ticker, [])
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=df_c.index, open=df_c["Open"], high=df_c["High"], low=df_c["Low"], close=df_c["Close"], name="Price"))
            fig.add_trace(go.Scatter(x=df_c.index, y=df_c["EMA10"], mode="lines", name="EMA10"))
            fig.add_trace(go.Scatter(x=df_c.index, y=df_c["EMA30"], mode="lines", name="EMA30"))

            buy_idx = df_c[(df_c["EMA10"] > df_c["EMA30"]) & (df_c["RSI7"] < 70)].index
            sell_idx = df_c[(df_c["EMA10"] < df_c["EMA30"]) & (df_c["RSI7"] > 30)].index
            fig.add_trace(go.Scatter(x=buy_idx, y=df_c.loc[buy_idx,"Close"], mode="markers", name="Buy",
                                     marker=dict(symbol="triangle-up", size=12, color="green")))
            fig.add_trace(go.Scatter(x=sell_idx, y=df_c.loc[sell_idx,"Close"], mode="markers", name="Sell",
                                     marker=dict(symbol="triangle-down", size=12, color="red")))

            for pos in pos_list:
                if pos["status"]=="open":
                    fig.add_hline(y=pos["stop_loss"], line_dash="dash", line_color="red", annotation_text="SL")
                    fig.add_hline(y=pos["take_profit"], line_dash="dash", line_color="green", annotation_text="TP")
                    fig.add_hline(y=pos["trailing_stop"], line_dash="dot", line_color="orange", annotation_text="Trailing SL")

            fig.update_layout(xaxis_rangeslider_visible=False, title=f"{ticker} Intraday Chart", height=600)
            st.plotly_chart(fig, use_container_width=True)

# --- CHECK POSITIONS FOR SL/TP/TRAILING STOP ---
for ticker, pos_list in st.session_state.positions.items():
    df_price = None
    for exchange_df in exchange_results.values():
        if ticker in exchange_df["Stock"].values:
            df_price = exchange_df[exchange_df["Stock"]==ticker]["Price"].values[0]
            break
    if df_price is None:
        continue
    for pos in pos_list:
        if pos["status"]=="open":
            if TRAILING_STOP:
                pos["trailing_stop"] = max(pos["trailing_stop"], df_price * (1 - STOP_LOSS/100))
            if df_price <= pos["trailing_stop"]:
                pos["status"]="closed"
                st.session_state.capital += pos["shares"] * df_price
                alert_text = f"⚠️ {ticker} closed by Trailing Stop at ${df_price:.2f}"
                st.session_state.alerts.append(alert_text)
                st.toast(alert_text)
            elif df_price >= pos["take_profit"]:
                pos["status"]="closed"
                st.session_state.capital += pos["shares"] * df_price
                alert_text = f"✅ {ticker} closed by Take-Profit at ${df_price:.2f}"
                st.session_state.alerts.append(alert_text)
                st.toast(alert_text)

# --- UPDATE EQUITY CURVE ---
total_value = st.session_state.capital
for ticker, pos_list in st.session_state.positions.items():
    df_price = None
    for exchange_df in exchange_results.values():
        if ticker in exchange_df["Stock"].values:
            df_price = exchange_df[exchange_df["Stock"]==ticker]["Price"].values[0]
            break
    if df_price is not None:
        for pos in pos_list:
            if pos["status"]=="open":
                total_value += pos["shares"] * df_price
st.session_state.equity_curve.append(total_value)

st.subheader("📈 Portfolio Equity Curve")
st.line_chart(st.session_state.equity_curve)

# --- ALERT LOG ---
st.subheader("📋 Alert Log")
alerts_df = pd.DataFrame({"Time": pd.Timestamp.now(), "Alert": st.session_state.alerts})
st.dataframe(alerts_df)

# --- NEXT REFRESH ---
st.info(f"Next refresh in {REFRESH_INTERVAL} seconds...")
time.sleep(REFRESH_INTERVAL)
st.experimental_rerun()
