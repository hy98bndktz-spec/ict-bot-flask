# bot.py
import os
import time
import io
import math
import requests
import pandas as pd
import numpy as np
import mplfinance as mpf
import matplotlib.pyplot as plt
from datetime import datetime, timezone, timedelta
from flask import Flask
import threading

# -----------------------
# CONFIG (already filled with your values)
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"
TWELVE_API_KEY = "0176951f5a044e719d7e644a6885120a"

# ASSETS — TwelveData symbols
ASSETS = [
    "XAU/USD",  # Gold
    "BTC/USD",  # Bitcoin
    "ETH/USD",  # Ethereum
    "EUR/USD",
    "USD/JPY",
    "GBP/USD"
]

INTERVAL = "5min"
OUTPUTSIZE = 200  # number of candles to fetch
FRESHNESS_MINUTES = 20  # consider data stale if last candle older than this

# Flask app for Render
app = Flask(__name__)

@app.route("/")
def home():
    return "🚀 ICT-style Bot (dark candles) - running"

# -----------------------
# Helper: send message / photo to Telegram
def tg_send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=15)
    except Exception as e:
        print("tg send msg failed:", e)

def tg_send_photo(img_bytes, caption=""):
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", img_bytes)}
    data = {"chat_id": CHAT_ID, "caption": caption, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=data, files=files, timeout=30)
    except Exception as e:
        print("tg send photo failed:", e)

def now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# -----------------------
# Get OHLC data from TwelveData
def get_data_td(symbol, interval=INTERVAL, outputsize=OUTPUTSIZE):
    base = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "format": "JSON",
        "apikey": TWELVE_API_KEY
    }
    r = requests.get(base, params=params, timeout=20)
    data = r.json()
    if "values" not in data:
        raise RuntimeError(f"TwelveData error for {symbol}: {data}")
    df = pd.DataFrame(data["values"])
    # TwelveData returns newest first -> reverse
    df = df.iloc[::-1].reset_index(drop=True)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)
    # ensure numeric columns
    for c in ["open","high","low","close","volume"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    # keep ohlc
    df = df.loc[:, df.columns.intersection(["open","high","low","close","volume"])]
    return df

# -----------------------
# Indicators (EMA, RSI)
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def compute_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=period-1, adjust=False).mean()
    ma_down = down.ewm(com=period-1, adjust=False).mean()
    rs = ma_up / ma_down
    rsi = 100 - (100 / (1 + rs))
    return rsi

def compute_indicators(df):
    df = df.copy()
    df["EMA20"] = ema(df["close"], 20)
    df["EMA50"] = ema(df["close"], 50)
    df["RSI"] = compute_rsi(df["close"], 14)
    return df

# -----------------------
# ICT-like heuristics (approximate)
def detect_fvg(df):
    # Fair Value Gap: check recent 3-candle patterns where middle body doesn't overlap neighbors
    fvg_list = []
    for i in range(1, len(df)-1):
        a_close, a_open = df["close"].iloc[i-1], df["open"].iloc[i-1]
        b_close, b_open = df["close"].iloc[i], df["open"].iloc[i]
        c_close, c_open = df["close"].iloc[i+1], df["open"].iloc[i+1]
        # bullish FVG example: middle bearish, and gap between a.close and c.open
        try:
            body_a_low, body_a_high = min(a_open, a_close), max(a_open, a_close)
            body_b_low, body_b_high = min(b_open, b_close), max(b_open, b_close)
            body_c_low, body_c_high = min(c_open, c_close), max(c_open, c_close)
        except Exception:
            continue
        # bullish gap
        if (b_close < b_open) and (body_c_low > body_a_high):
            fvg_list.append((df.index[i-1], df.index[i+1], body_a_high, body_c_low))
        # bearish gap
        if (b_close > b_open) and (body_c_high < body_a_low):
            fvg_list.append((df.index[i-1], df.index[i+1], body_c_high, body_a_low))
    return fvg_list

def detect_order_blocks(df):
    # approximate order blocks: look for last strong bearish candle before rally (bull OB)
    obs = []
    for i in range(1, len(df)-2):
        prev = df.iloc[i-1]
        cur = df.iloc[i]
        nxt = df.iloc[i+1]
        # bullish order block: prev bearish and then price rallies above prev.high within next few candles
        if prev["close"] < prev["open"]:
            future_highs = df["high"].iloc[i+1:i+5]
            if any(h > prev["high"] for h in future_highs):
                obs.append(("bullish", prev.name, float(prev["low"]), float(prev["high"])))
        # bearish order block
        if prev["close"] > prev["open"]:
            future_lows = df["low"].iloc[i+1:i+5]
            if any(l < prev["low"] for l in future_lows):
                obs.append(("bearish", prev.name, float(prev["low"]), float(prev["high"])))
    return obs

def detect_liquidity(df):
    # approximate liquidity zones: local highs/lows spikes
    liquidity = []
    highs = df["high"]
    lows = df["low"]
    for i in range(3, len(df)-3):
        win_high = highs.iloc[i-3:i+4]
        win_low = lows.iloc[i-3:i+4]
        if highs.iloc[i] == win_high.max():
            liquidity.append(("sell", df.index[i], highs.iloc[i]))
        if lows.iloc[i] == win_low.min():
            liquidity.append(("buy", df.index[i], lows.iloc[i]))
    return liquidity

# -----------------------
# Chart drawing: candlesticks dark theme with overlays
def make_candle_chart(df, sig, fvg_list, obs, liquidity_list):
    # prepare mpf data
    ohlc = df.loc[:, ["open","high","low","close"]].copy()
    ohlc.index.name = "Date"

    # style dark
    s = mpf.make_mpf_style(base_mpf_style='nightclouds', rc={
        'font.size': 9,
        'axes.facecolor': '#0e0f11',
        'figure.facecolor': '#0e0f11',
        'savefig.facecolor': '#0e0f11'
    })

    add_plots = []
    # EMAs
    if "EMA20" in df.columns:
        add_plots.append(mpf.make_addplot(df["EMA20"], color='cyan', width=0.8))
    if "EMA50" in df.columns:
        add_plots.append(mpf.make_addplot(df["EMA50"], color='magenta', width=0.8))

    # build custom rectangular overlays for FVG and OB
    alphas = 0.25
    mc = mpf.make_marketcolors(up='lime', down='red', edge='inherit', wick='inherit')
    fig, axlist = mpf.plot(ohlc,
                          type='candle',
                          style=s,
                          addplot=add_plots,
                          returnfig=True,
                          figsize=(8,4),
                          tight_layout=True)

    ax = axlist[0]

    # draw FVGs as translucent rectangles
    for (start, end, low, high) in fvg_list:
        # x coords: convert datetimes to axis positions
        try:
            ax.axvspan(start, end, color='#ffd700', alpha=alphas)  # gold-ish
            ax.text(end, (low+high)/2, 'FVG', color='black', fontsize=7, va='center', ha='right', backgroundcolor='#ffd700', alpha=0.6)
        except Exception:
            continue

    # draw Order Blocks as thicker rectangles
    for ob in obs:
        typ, time_idx, low, high = ob
        color = '#00bfff' if typ=="bullish" else '#ff69b4'
        try:
            # span 1 candle width after time_idx to current index
            ax.axvspan(time_idx, df.index[-1], ymin=0, ymax=1, color=color, alpha=0.06)
            ax.text(time_idx, high, 'OB', color=color, fontsize=7, va='bottom')
        except Exception:
            continue

    # draw liquidity points
    for liq in liquidity_list:
        typ, t_idx, price = liq
        marker = '^' if typ=='buy' else 'v'
        col = 'white'
        try:
            ax.plot([t_idx], [price], marker=marker, color=col, markersize=6, alpha=0.9)
            ax.text(t_idx, price, 'LQ', color=col, fontsize=7, va='bottom' if typ=='buy' else 'top')
        except Exception:
            continue

    # title with signal
    title = f"{sig['symbol']}  {sig['signal']}  Price:{sig['price']:.4f}  RSI:{sig['rsi']:.1f}"
    ax.set_title(title, color='white', fontsize=10)

    # save to bytes
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf

# -----------------------
# determine if data is fresh enough
def is_fresh(df, minutes=FRESHNESS_MINUTES):
    if df is None or df.empty:
        return False
    last_time = df.index[-1]
    now = datetime.now(timezone.utc)
    return (now - last_time) <= timedelta(minutes=minutes)

# -----------------------
# generate signal (EMA cross + RSI filter)
def generate_signal_basic(df, symbol):
    df = compute_indicators(df)
    if df is None or df.empty:
        return {"symbol": symbol, "signal": "NO_DATA"}
    last = df.iloc[-1]
    price = float(last["close"])
    ema20 = float(last["EMA20"]) if not math.isnan(last["EMA20"]) else math.nan
    ema50 = float(last["EMA50"]) if not math.isnan(last["EMA50"]) else math.nan
    rsi_val = float(last["RSI"]) if not math.isnan(last["RSI"]) else math.nan

    signal = "HOLD"
    tp = None
    if not math.isnan(ema20) and not math.isnan(ema50):
        if ema20 > ema50 and rsi_val < 70:
            signal = "BUY"
            tp = price * 1.002
        elif ema20 < ema50 and rsi_val > 30:
            signal = "SELL"
            tp = price * 0.998

    return {
        "symbol": symbol,
        "price": price,
        "signal": signal,
        "tp": tp,
        "rsi": rsi_val,
        "time": now_utc_str()
    }

# -----------------------
# Main analyze & send (separate message per asset)
def analyze_and_send():
    for symbol in ASSETS:
        try:
            df = get_data_td(symbol)
            # require at least some candles
            if df is None or len(df) < 20:
                tg_send_message(f"⚠️ No/insufficient data for {symbol}")
                continue
            # check freshness (skip if stale)
            if not is_fresh(df):
                print(f"{symbol} data stale, skipping")
                continue

            df = compute_indicators(df)
            sig = generate_signal_basic(df, symbol)

            # detect ICT-ish structures
            fvg = detect_fvg(df)
            obs = detect_order_blocks(df)
            liq = detect_liquidity(df)

            caption = (
                f"*ICT Smart Money Signal*\n"
                f"Asset: `{sig['symbol']}`\n"
                f"Time: `{sig['time']}`\n"
                f"Price: `${sig['price']:.4f}`\n"
                f"Signal: *{sig['signal']}*\n"
                f"RSI: `{sig['rsi']:.1f}`\n"
            )
            if sig["tp"] is not None:
                caption += f"🎯 TP: `{sig['tp']:.4f}`\n"
            caption += "⚙️ Strategy: Michael ICT - Smart Money Concepts (approx)"

            # send only when BUY or SELL (user wanted that behavior)
            if sig["signal"] in ("BUY", "SELL"):
                try:
                    chart = make_candle_chart(df, sig, fvg, obs, liq)
                    tg_send_photo(chart, caption)
                    print(now_utc_str(), f"Sent {symbol} {sig['signal']}")
                except Exception as e:
                    tg_send_message(f"⚠️ Failed to create/send chart for {symbol}: {e}")
            else:
                print(now_utc_str(), f"{symbol}: HOLD")

        except Exception as e:
            tg_send_message(f"⚠️ Error analyzing {symbol}: {e}")

# -----------------------
# Thread runner
def run_loop():
    while True:
        analyze_and_send()
        time.sleep(300)  # 5 minutes

if __name__ == "__main__":
    try:
        tg_send_message("🚀 ICT Dark Candles Bot started (5m) — will send BUY/SELL per asset")
    except Exception:
        pass
    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
