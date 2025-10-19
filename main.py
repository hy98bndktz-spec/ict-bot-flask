# main.py
# ICT Smart Money Bot (Render + Binance + TwelveData)
# يجلب الأسعار من Binance (للعملات الرقمية) و TwelveData (للأزواج العادية)

import os
import time
import io
import math
import traceback
import requests
from datetime import datetime, timezone, timedelta
from threading import Thread

# plotting
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

from flask import Flask

# ========================
# CONFIG
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"
TWELVE_API_KEY = "f82dced376934dc0ab99e79afd3ca844"

# أزواج العملات
SYMBOLS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "GOLD": "XAU/USD",
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY"
}

CHECK_INTERVAL = 300  # 5 دقائق

TG_SEND = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
TG_SEND_PHOTO = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"

# ========================
app = Flask(__name__)

@app.route("/")
def home():
    return "🚀 ICT Smart Money Bot — Running with Binance + TwelveData"

# ========================
def now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def send_telegram_text(text):
    try:
        requests.post(TG_SEND, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print("Telegram send error:", e)

def send_telegram_photo(file_bytes_io, caption=""):
    try:
        file_bytes_io.seek(0)
        requests.post(
            TG_SEND_PHOTO,
            data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "Markdown"},
            files={"photo": ("chart.png", file_bytes_io.getvalue())},
            timeout=30
        )
    except Exception as e:
        print("Telegram photo send error:", e)

# ========================
# EMA + RSI
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

# ========================
# Fetch functions
def fetch_binance(symbol, interval="1h", limit=200):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=10)
        data = r.json()
        df = pd.DataFrame(data, columns=[
            "Open time", "Open", "High", "Low", "Close", "Volume",
            "Close time", "QAV", "trades", "TB_base", "TB_quote", "ignore"
        ])
        df["Open time"] = pd.to_datetime(df["Open time"], unit="ms")
        df.set_index("Open time", inplace=True)
        df = df.astype(float)
        return df[["Open", "High", "Low", "Close", "Volume"]]
    except Exception as e:
        print(f"fetch_binance error for {symbol}:", e)
        return None

def fetch_twelvedata(symbol, interval="1h", outputsize=200):
    try:
        url = (
            f"https://api.twelvedata.com/time_series?"
            f"symbol={symbol}&interval={interval}&outputsize={outputsize}&apikey={TWELVE_API_KEY}"
        )
        r = requests.get(url, timeout=10)
        data = r.json()
        if "values" not in data:
            print("twelvedata error:", data)
            return None
        df = pd.DataFrame(data["values"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.rename(columns=str.capitalize)
        df.set_index("Datetime", inplace=True)
        df = df.astype(float)
        df = df.sort_index()
        return df[["Open", "High", "Low", "Close", "Volume"]]
    except Exception as e:
        print(f"fetch_twelvedata error for {symbol}:", e)
        return None

# ========================
def generate_signal(df):
    try:
        df["EMA20"] = ema(df["Close"], 20)
        df["EMA50"] = ema(df["Close"], 50)
        df["RSI"] = rsi(df["Close"], 14)
        last = df.iloc[-1]
        price = float(last["Close"])
        ema20 = last["EMA20"]
        ema50 = last["EMA50"]
        rsi_val = last["RSI"]

        signal = "HOLD"
        if ema20 > ema50 and rsi_val < 70:
            signal = "BUY"
        elif ema20 < ema50 and rsi_val > 30:
            signal = "SELL"

        return {"price": price, "rsi": rsi_val, "signal": signal}
    except Exception as e:
        print("signal error:", e)
        return {"signal": "HOLD"}

# ========================
def generate_chart(df, symbol, signal_info):
    try:
        df["EMA20"] = ema(df["Close"], 20)
        df["EMA50"] = ema(df["Close"], 50)
        apds = [
            mpf.make_addplot(df["EMA20"], width=0.8),
            mpf.make_addplot(df["EMA50"], width=0.8)
        ]
        style = mpf.make_mpf_style(base_mpf_style="nightclouds")
        fig, ax = mpf.plot(df.tail(100), type="candle", style=style, addplot=apds, figsize=(9,4), returnfig=True)
        ax[0].set_title(f"{symbol} | {signal_info['signal']}", color="white")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=120)
        plt.close(fig)
        return buf
    except Exception as e:
        print("chart error:", e)
        return None

# ========================
def analyze_and_send_all():
    send_telegram_text(f"🚀 ICT Bot started successfully — {now_utc_str()}")

    while True:
        for name, symbol in SYMBOLS.items():
            try:
                # اختار المصدر حسب نوع الزوج
                if symbol.endswith("USDT"):
                    df = fetch_binance(symbol)
                else:
                    df = fetch_twelvedata(symbol)

                if df is None or df.empty:
                    print(f"{name} — skipped (no data)")
                    continue

                sig = generate_signal(df)
                if sig["signal"] in ("BUY", "SELL"):
                    caption = (
                        f"*{name}* `{symbol}`\n"
                        f"Signal: *{sig['signal']}*\n"
                        f"Price: `{sig['price']:.4f}`\n"
                        f"RSI: `{sig['rsi']:.2f}`\n"
                        f"Time: `{now_utc_str()}`"
                    )
                    chart_buf = generate_chart(df, name, sig)
                    if chart_buf:
                        send_telegram_photo(chart_buf, caption)
                    else:
                        send_telegram_text(caption)
                    print(f"{now_utc_str()} - Sent {sig['signal']} for {name}")
                else:
                    print(f"{now_utc_str()} - {name}: HOLD")

            except Exception as e:
                print(f"Loop error for {name}:", e, traceback.format_exc())
                continue

        time.sleep(CHECK_INTERVAL)

# ========================
def start_background():
    t = Thread(target=analyze_and_send_all, daemon=True)
    t.start()

if __name__ == "__main__":
    start_background()
    port = int(os.environ.get("PORT", 10000))
    print(f"{now_utc_str()} - Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port)
