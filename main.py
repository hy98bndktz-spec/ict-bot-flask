# main.py
# ICT Smart-Money Telegram Signal Bot (single-file, ready for Render)
# ملاحظة: الكود يحتوي التوكن والـ chat id كما طلبت (تجريبي). لاحقاً ضعه كـ env vars لأمان أفضل.

import os
import time
import io
import math
import traceback
import requests
from datetime import datetime, timezone, timedelta
from threading import Thread

# plotting & data
import matplotlib
matplotlib.use("Agg")  # headless backend for servers
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import yfinance as yf

# web keep-alive
from flask import Flask

# -----------------------
# CONFIG (هنا التوكن والـ chat id — موضوع حسب طلبك)
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"

# Symbols mapping (yfinance symbols)
SYMBOLS = {
    "BTC": "BTC-USD",
    "GOLD": "GC=F",
    "ETH": "ETH-USD",
    "EURUSD": "EURUSD=X",
    "USDJPY": "JPY=X",
    "GBPUSD": "GBPUSD=X"
}

TIMEFRAME_BIG = "1h"
TIMEFRAME_ENTRY = "5m"
CHECK_INTERVAL = 300  # 5 دقائق

# Telegram endpoints
TG_SEND = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
TG_SEND_PHOTO = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"

# Flask app
app = Flask(__name__)

@app.route("/")
def home():
    return "🚀 ICT Smart Money Bot — Running"

# -----------------------
# Utilities
def now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def send_telegram_text(text):
    try:
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
        r = requests.post(TG_SEND, json=payload, timeout=10)
        if not r.ok:
            print("Telegram text send failed:", r.status_code, r.text)
        return r.ok
    except Exception as e:
        print("Telegram send error:", e)
        return False

def send_telegram_photo(file_bytes_io, caption=""):
    try:
        file_bytes_io.seek(0)
        files = {"photo": ("chart.png", file_bytes_io.getvalue())}
        data = {"chat_id": CHAT_ID, "caption": caption, "parse_mode": "Markdown"}
        r = requests.post(TG_SEND_PHOTO, data=data, files=files, timeout=30)
        if not r.ok:
            print("Telegram photo send failed:", r.status_code, r.text)
        return r.ok
    except Exception as e:
        print("Telegram send photo error:", e)
        return False

# -----------------------
# Data fetchers
def fetch_yf(symbol, period="2d", interval="1h"):
    try:
        df = yf.download(tickers=symbol, period=period, interval=interval, progress=False, auto_adjust=False)
        if df is None or df.empty:
            return None
        df.index = pd.to_datetime(df.index)
        return df[["Open", "High", "Low", "Close", "Volume"]]
    except Exception as e:
        print(f"fetch_yf error for {symbol}:", e)
        return None

# -----------------------
# Indicators
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(alpha=1/period, adjust=False).mean()
    ma_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = ma_up / (ma_down + 1e-9)
    return 100 - (100/(1+rs))

# -----------------------
# Simple heuristics
def detect_order_blocks_and_fvg(df):
    ob_list, fvg_list = [], []
    try:
        n = len(df)
        for i in range(2, n-2):
            prev = df.iloc[i-1]
            nxt = df.iloc[i+1]
            if prev['Close'] < prev['Open'] and (df['High'].iloc[i+1:i+4] > prev['High']).any():
                ob_list.append(("bullish", prev.name, float(prev['Low']), float(prev['High'])))
            if prev['Close'] > prev['Open'] and (df['Low'].iloc[i+1:i+4] < prev['Low']).any():
                ob_list.append(("bearish", prev.name, float(prev['Low']), float(prev['High'])))
    except Exception as e:
        print("detect OB/FVG error:", e)
    return ob_list, fvg_list

# -----------------------
# Chart
def generate_candlestick_image(df, symbol, sig):
    try:
        df["EMA20"] = ema(df["Close"], 20)
        df["EMA50"] = ema(df["Close"], 50)
        apds = [mpf.make_addplot(df["EMA20"]), mpf.make_addplot(df["EMA50"])]
        style = mpf.make_mpf_style(base_mpf_style="nightclouds")
        fig, axes = mpf.plot(df, type='candle', style=style, addplot=apds, returnfig=True, figsize=(9,4))
        ax = axes[0]
        ax.set_title(f"{symbol} | {sig['signal']} | {sig['time']}", color="white", fontsize=10)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf
    except Exception as e:
        print("generate_candlestick_image error:", e)
        return None

# -----------------------
# Signal generator
def generate_signal_from_df(df):
    try:
        df["EMA20"] = ema(df["Close"], 20)
        df["EMA50"] = ema(df["Close"], 50)
        df["RSI"] = rsi(df["Close"], 14)
        last = df.iloc[-1]
        price, ema20, ema50, rsi_val = float(last["Close"]), float(last["EMA20"]), float(last["EMA50"]), float(last["RSI"])
        signal = "HOLD"
        if ema20 > ema50 and rsi_val < 70:
            signal = "BUY"
        elif ema20 < ema50 and rsi_val > 30:
            signal = "SELL"
        return {"time": now_utc_str(), "price": price, "signal": signal, "rsi": rsi_val}
    except Exception as e:
        print("generate_signal_from_df error:", e)
        return {"time": now_utc_str(), "signal": "HOLD"}

# -----------------------
# Background loop
def analyze_and_send_all():
    print(f"{now_utc_str()} - Background loop started. Checking every {CHECK_INTERVAL}s.")
    send_telegram_text(f"🚀 ICT Bot started successfully. Time: {now_utc_str()}")
    while True:
        try:
            for short, sym in SYMBOLS.items():
                df = fetch_yf(sym, period="7d", interval="1h")
                if df is None or df.empty:
                    continue
                sig = generate_signal_from_df(df)
                df_plot = df.tail(120)
                chart = generate_candlestick_image(df_plot, short, sig)
                caption = f"*ICT Smart Money Signal* `{short}`\nTime: `{sig['time']}`\nSignal: *{sig['signal']}*"
                if chart:
                    send_telegram_photo(chart, caption)
                else:
                    send_telegram_text(caption)
                print(f"{now_utc_str()} - {short}: {sig['signal']}")
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            print("Main loop error:", e)
            time.sleep(10)

# -----------------------
# Run background + Flask
def start_background():
    t = Thread(target=analyze_and_send_all, daemon=True)
    t.start()

# ✅ نبدأ الخيط سواء كان تشغيل مباشر أو تحت Gunicorn
start_background()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"{now_utc_str()} - Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port)
