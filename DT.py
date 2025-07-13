import streamlit as st
import yfinance as yf
import pandas as pd
import os
import json
import plotly.graph_objects as go
import requests
from bs4 import BeautifulSoup
import time
import threading
import asyncio
import websockets
import requests


# --- Paths for saving persistent data
PORTFOLIO_FILE = "portfolio_data.json"
BALANCE_FILE = "balance_data.txt"
LIMIT_ORDER_FILE = "limit_orders.json"

# --- Helper: Save session data
def save_session():
    """Saves the current portfolio and balance to respective files."""
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(st.session_state.portfolio, f)
    with open(BALANCE_FILE, "w") as f:
        f.write(str(st.session_state.balance))

def load_limit_orders():
    """Loads pending limit orders from a JSON file."""
    if os.path.exists(LIMIT_ORDER_FILE):
        with open(LIMIT_ORDER_FILE, "r") as f:
            return json.load(f)
    return []

def save_limit_orders(orders):
    """Saves the current list of limit orders to a JSON file."""
    with open(LIMIT_ORDER_FILE, "w") as f:
        json.dump(orders, f)

# --- Fetch Top Scripts in View Info Tab
def fetch_from_screener(url):
    """
    Fetches stock data (Top Gainers, Losers, etc.) from screener.in.
    Args:
        url (str): The URL of the screener page.
    Returns:
        pd.DataFrame: A DataFrame containing the top 5 stocks, or None if fetching fails.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table")
        if not table:
            print("[ERROR] Table not found.")
            return None
        df = pd.read_html(str(table))[0]
        df = df.iloc[:, :3]
        df.columns = ["Stock", "LTP ($)", "% Change"]
        return df.head(5)
    except Exception as e:
        print(f"[ERROR] Screener fetch failed: {e}")
        return None

# Defining Top Gainers
def fetch_top_gainers():
    """Fetches top gaining stocks."""
    return fetch_from_screener("https://www.screener.in/screens/49/top-gainers/")

# Defining Top Losers
def fetch_top_losers():
    """Fetches top losing stocks."""
    return fetch_from_screener("https://www.screener.in/screens/50/top-losers/")

# Defining Most Trending
def fetch_trending_stocks():
    """Fetches most active/trending stocks."""
    return fetch_from_screener("https://www.screener.in/screens/326016/most-active/")

# Defining Top Turnover
def fetch_top_turnover():
    """Fetches stocks with top turnover."""
    return fetch_from_screener("https://www.screener.in/screens/326010/top-turnover/")

def render_stock_chart(ticker_symbol, period="1mo", chart_type="Line"):
    """
    Renders a historical stock chart using Plotly.
    Args:
        ticker_symbol (str): The Yahoo Finance ticker symbol.
        period (str): The period for historical data (e.g., "1mo", "1y").
        chart_type (str): "Line" or "Candlestick".
    """
    try:
        stock = yf.Ticker(ticker_symbol)
        hist = stock.history(period=period, interval="1d")  # Force daily interval for better support

        if hist.empty or "Close" not in hist:
            st.warning("⚠️ No historical chart data found for this stock.")
            return

        fig = go.Figure()

        if chart_type == "Line":
            fig.add_trace(go.Scatter(x=hist.index, y=hist["Close"], mode="lines", name="Close Price"))
        elif chart_type == "Candlestick":
            fig.add_trace(go.Candlestick(
                x=hist.index,
                open=hist["Open"],
                high=hist["High"],
                low=hist["Low"],
                close=hist["Close"],
                name="Candlestick"
            ))

        fig.update_layout(
            title=f"{ticker_symbol} - {chart_type} Chart",
            xaxis_title="Date",
            yaxis_title="Price (₹)",
            xaxis_rangeslider_visible=False
        )
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Error loading chart: {e}")

st.set_page_config(page_title="BSE Dummy Trading App", layout="wide")
st.title("📈 BSE Dummy Trading App")

# 🪙 Live Current Balance shown below title
balance_slot = st.empty()

# --- Load persistent data or initialize
if "portfolio" not in st.session_state:
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r") as f:
            st.session_state.portfolio = json.load(f)
    else:
        st.session_state.portfolio = {}

if "balance" not in st.session_state:
    if os.path.exists(BALANCE_FILE):
        with open(BALANCE_FILE, "r") as f:
            st.session_state.balance = float(f.read())
    else:
        st.session_state.balance = 1000000.0  # ₹10 Lakhs default


# --- Execute any matching limit orders
# This function is now ONLY called by the new "Execute Pending Limit Orders" button
def process_limit_orders():
    """
    Checks all pending limit orders and executes them if their conditions are met.
    Updates portfolio, balance, and saves remaining orders.
    """
    orders = load_limit_orders()
    remaining = []
    changed = False

    for order in orders:
        ticker = order["ticker"]
        qty = order["qty"]
        action = order["action"]
        target_price = order["target_price"]

        stock = yf.Ticker(ticker)
        ltp = stock.info.get("regularMarketPrice", None)

        if ltp is None:
            # If LTP cannot be fetched, keep the order pending
            remaining.append(order)
            continue

        # Check if the limit order condition is met
        if (action == "buy" and ltp <= target_price) or \
           (action == "sell" and ltp >= target_price):
            
            p = st.session_state.portfolio.get(ticker, {"qty": 0, "avg_price": 0})
            
            if action == "buy":
                cost = qty * ltp
                if cost <= st.session_state.balance:
                    new_qty = p["qty"] + qty
                    new_avg = (p["qty"] * p["avg_price"] + qty * ltp) / new_qty
                    st.session_state.portfolio[ticker] = {"qty": new_qty, "avg_price": new_avg}
                    st.session_state.balance -= cost
                    changed = True
                    st.toast(f"Executed BUY {qty} of {ticker.replace('.BO', '')} at ₹{ltp:.2f} (Limit Order)", icon="✅")
                else:
                    # Not enough balance, keep the order pending
                    remaining.append(order)
            elif action == "sell":
                if p["qty"] >= qty:
                    p["qty"] -= qty
                    if p["qty"] > 0:
                        st.session_state.portfolio[ticker] = p
                    else:
                        del st.session_state.portfolio[ticker]
                    st.session_state.balance += qty * ltp
                    changed = True
                    st.toast(f"Executed SELL {qty} of {ticker.replace('.BO', '')} at ₹{ltp:.2f} (Limit Order)", icon="✅")
                else:
                    # Not enough shares to sell, keep the order pending
                    remaining.append(order)
        else:
            # Condition not met, keep the order pending
            remaining.append(order)

    if changed:
        save_session()
    save_limit_orders(remaining)
    return changed # Return if any orders were executed


# --- Reset portfolio and Refresh Prices buttons in sidebar
with st.sidebar:
    col1, col2 = st.columns(2)

    if col1.button("🔁 Reset Portfolio"):
        st.session_state.portfolio = {}
        st.session_state.balance = 1000000.0
        save_session()
        # Remove files to ensure a clean reset
        if os.path.exists(PORTFOLIO_FILE): os.remove(PORTFOLIO_FILE)
        if os.path.exists(BALANCE_FILE): os.remove(BALANCE_FILE)
        if os.path.exists(LIMIT_ORDER_FILE): os.remove(LIMIT_ORDER_FILE)
        st.toast("Portfolio reset to ₹10,00,000.", icon="✅")
        st.success("Portfolio has been reset to ₹10,00,000. Interact with the app to see changes.")


    if col2.button("🔄 Refresh Prices"):
        # This button now ONLY refreshes prices and UI, does NOT execute limit orders
        st.toast("Market prices refreshed.", icon="✅")
        st.success("Market prices have been refreshed. Check 'Pending Trades' tab and click 'Execute Pending Limit Orders at Market Price' to process.")


# Show recalculated or loaded balance
st.markdown(f"#### 🪙 Current Balance: ₹{st.session_state.balance:,.2f}")
    
# --- Tabs for navigation
view_tab, trade_tab, portfolio_tab, pending_tab = st.tabs([
    "📊 View Stock Info",
    "💼 Trade Simulator",
    "📁 My Saved Portfolio",
    "📋 Pending Trades"
])

with portfolio_tab:
    st.subheader("📁 My Saved Portfolio")

    if st.session_state.portfolio:
        df = pd.DataFrame.from_dict(st.session_state.portfolio, orient="index")
        # Fetch current prices for portfolio holdings
        current_prices = {}
        for symbol in df.index:
            try:
                stock = yf.Ticker(symbol)
                current_prices[symbol] = stock.info.get("regularMarketPrice", 0)
            except Exception:
                current_prices[symbol] = 0 # Default to 0 if price fetch fails

        df["Current Price"] = df.index.map(lambda s: current_prices.get(s, 0))
        df["Value"] = df["qty"] * df["Current Price"]
        df["P/L"] = (df["Current Price"] - df["avg_price"]) * df["qty"]

        st.dataframe(df.style.format("{:.2f}"))
    else:
        st.info("Your portfolio is currently empty.")

with pending_tab:
    st.subheader("📋 Pending Limit Orders")
    limit_orders = load_limit_orders()

    if limit_orders:
        data = []
        for order in limit_orders:
            ticker = order["ticker"]
            qty = order["qty"]
            action = order.get("action", "buy").capitalize()
            target_price = order["target_price"]
            
            # Attempt to get stock name, default to ticker if not found
            stock_name = yf.Ticker(ticker).info.get("shortName", ticker.replace(".BO", ""))
            code = ticker.replace(".BO", "")
            
            data.append({
                "Stock Name": stock_name,
                "Scrip Code": code,
                "Action": action,
                "Limit Price (₹)": target_price,
                "Quantity": qty,
                "Total Value (₹)": target_price * qty if action == "Buy" else target_price * qty # Value for display
            })

        df = pd.DataFrame(data)
        st.dataframe(df.style.format({
            "Limit Price (₹)": "{:.2f}",
            "Total Value (₹)": "{:,.2f}"
        }))
        
        st.markdown("---")
        # New button to explicitly execute pending limit orders
        if st.button("🚀 Execute Pending Limit Orders", help="Click to check and execute any limit orders that have met their price conditions."):
            executed_any = process_limit_orders()
            if executed_any:
                st.success("Successfully executed pending limit orders!")
            else:
                st.info("No pending limit orders met their conditions for execution at current prices.")
    else:
        st.info("No pending limit orders.")

# --- View Stock Info Tab
with view_tab:
    
    st.subheader("📊 BSE Market Summary")

    def get_index_data(ticker_symbol):
        """
        Fetches and calculates current price, change, and percentage change for an index.
        Args:
            ticker_symbol (str): The Yahoo Finance ticker symbol for the index.
        Returns:
            tuple: (current_price, change, percentage_change) or None if data is unavailable.
        """
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        current = info.get("regularMarketPrice", None)
        prev = info.get("previousClose", None)
        if current is not None and prev is not None:
            chg = current - prev
            pct = (chg / prev) * 100
            return round(current, 2), round(chg, 2), round(pct, 2)
        return None

    index_tickers = {
        "Sensex": "^BSESN",
        "Sensex 50": "^NSEI", # Nifty 50 is often used as a proxy for Sensex 50 in Yahoo Finance
        "BSE Bankex": "^BSEBANK"
    }

    cols = st.columns(len(index_tickers))
    for i, (name, symbol) in enumerate(index_tickers.items()):
        result = get_index_data(symbol)
        if result:
            price, change, pct = result
            cols[i].metric(label=name, value=f"{price}", delta=f"{change:+.2f} ({pct:+.2f}%)")
        else:
            cols[i].write(f"{name}: ⚠️ Unavailable")

    st.markdown("---")
    
    st.subheader("🏆 Top Market Movers")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 🔼 Top Gainers")
        df = fetch_top_gainers()
        if df is not None:
            st.dataframe(df)
        else:
            st.warning("Could not fetch top gainers.")

        st.markdown("#### 🔁 Trending Stocks")
        df = fetch_trending_stocks()
        if df is not None:
            st.dataframe(df)
        else:
            st.warning("Could not fetch trending stocks.")

    with col2:
        st.markdown("#### 🔽 Top Losers")
        df = fetch_top_losers()
        if df is not None:
           st.dataframe(df)
        else:
            st.warning("Could not fetch top losers.")

        st.markdown("#### 💰 Top Turnover")
        df = fetch_top_turnover()
        if df is not None:
            st.dataframe(df)
        else:
            st.warning("Could not fetch top turnover stocks.")

    st.markdown("---")

# --- Trade Simulator Tab
with trade_tab:
    user_input = st.text_input("Enter BSE stock name or code (for trading):", key="trade")
    
    # Only proceed if user has entered something
    if user_input:
        ticker = f"{user_input.strip().upper()}.BO"

        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            # Ensure we have a valid market price
            if 'regularMarketPrice' not in info or info['regularMarketPrice'] is None:
                st.warning(f"❌ Could not fetch live price for {ticker}. Please check the symbol.")
                ltp = 0.0 # Set LTP to 0 if not available
            else:
                ltp = info["regularMarketPrice"]
            symbol = ticker # Use the validated ticker
            
        except Exception as e:
            st.warning(f"❌ Could not fetch data for {ticker}: {e}. Please ensure it's a valid BSE stock code (e.g., RELIANCE.BO).")
            ltp = 0.0 # Set LTP to 0 if an error occurs
            info = {} # Clear info to prevent errors in subsequent calls
            symbol = ticker # Keep the symbol as entered for display purposes

        if ltp > 0: # Only show details if we have a valid price
            st.subheader("📊 Price Overview")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Last Traded Price", f"₹{ltp:.2f}")
            col2.metric("Day High", f"₹{info.get('dayHigh', 'N/A'):.2f}" if info.get('dayHigh') else "N/A")
            col3.metric("Day Low", f"₹{info.get('dayLow', 'N/A'):.2f}" if info.get('dayLow') else "N/A")
            col4.metric("Previous Close", f"₹{info.get('previousClose', 'N/A'):.2f}" if info.get('previousClose') else "N/A")

            col5, col6 = st.columns(2)
            col5.metric("52 Week High", f"₹{info.get('fiftyTwoWeekHigh', 'N/A'):.2f}" if info.get('fiftyTwoWeekHigh') else "N/A")
            col6.metric("52 Week Low", f"₹{info.get('fiftyTwoWeekLow', 'N/A'):.2f}" if info.get('fiftyTwoWeekLow') else "N/A")
            

            st.subheader("📉 Historical Charts")
            period_option = st.selectbox("Select Time Range", ["1mo", "3mo", "6mo", "1y", "2y"], key="chart_period")
            chart_type = st.radio("Chart Type", ["Line", "Candlestick"], horizontal=True, key="chart_type")
            render_stock_chart(symbol, period=period_option, chart_type=chart_type)

            st.subheader("💼 Dummy Portfolio")
            st.write(f"**Available Balance:** ₹{st.session_state.balance:.2f}")

            qty = st.number_input("Quantity", min_value=1, step=1)
            action = st.radio("Action", ["Buy", "Sell"])
            order_type = st.radio("Order Type", ["Limit", "Market"], key="order_type_radio", index=0)
            
            target_price = None
            if order_type.lower() == "limit":
                target_price = st.number_input("Target Price (₹)", min_value=0.0, value=ltp, step=0.1, format="%.2f")
                st.info("Limit orders are placed in 'Pending Trades' and require you to click 'Execute Pending Limit Orders' in that tab.")

            if st.button("Execute Trade"):
                if not ltp or ltp <= 0:
                    st.toast("Unable to retrieve valid price for execution.", icon="⚠️")
                else:
                    if order_type.lower() == "limit":
                        # Save to pending orders
                        orders = load_limit_orders()
                        orders.append({
                            "ticker": symbol,
                            "action": action.lower(),
                            "qty": qty,
                            "target_price": target_price
                        })
                        save_limit_orders(orders)
                        st.toast(f"Limit {action} order placed for {qty} shares of {symbol.replace('.BO', '')} at ₹{target_price:.2f}. Check 'Pending Trades' tab.", icon="✅")
                        st.success(f"Limit {action} order placed for {qty} shares of {symbol.replace('.BO', '')} at ₹{target_price:.2f}. This order is now pending in 'Pending Trades' tab.")


                    elif order_type.lower() == "market":
                        # Execute immediately for market orders
                        holdings = st.session_state.portfolio.get(symbol, {"qty": 0, "avg_price": 0})

                        if action == "Buy":
                            cost = qty * ltp
                            if cost > st.session_state.balance:
                                st.toast("Insufficient balance.", icon="⚠️")
                                st.error("Insufficient balance.")
                            else:
                                new_qty = holdings["qty"] + qty
                                new_avg = (holdings["qty"] * holdings["avg_price"] + qty * ltp) / new_qty
                                st.session_state.portfolio[symbol] = {"qty": new_qty, "avg_price": new_avg}
                                st.session_state.balance -= cost
                                save_session()
                                st.toast(f"Bought {qty} shares of {symbol.replace('.BO', '')} at ₹{ltp:.2f}.", icon="✅")
                                st.success(f"Bought {qty} shares of {symbol.replace('.BO', '')} at ₹{ltp:.2f}.")


                        elif action == "Sell":
                            if qty > holdings["qty"]:
                                st.toast("Not enough shares to sell.", icon="⚠️")
                                st.error("Not enough shares to sell.")
                            else:
                                holdings["qty"] -= qty
                                if holdings["qty"] == 0:
                                    del st.session_state.portfolio[symbol]
                                else:
                                    st.session_state.portfolio[symbol] = holdings
                                st.session_state.balance += qty * ltp
                                save_session()
                                st.toast(f"Sold {qty} shares of {symbol.replace('.BO', '')} at ₹{ltp:.2f}.", icon="✅")
                                st.success(f"Sold {qty} shares of {symbol.replace('.BO', '')} at ₹{ltp:.2f}.")
    else:
        st.info("Please enter a stock symbol to view details and trade.")
