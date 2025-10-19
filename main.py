# main.py
# ICT Smart-Money Telegram Signal Bot (Render ready, Auto-start + KeepAlive)

import os
import time
import io
import math
import traceback
import requests
from datetime import datetime, timezone, timedelta
from threading import Thread
from flask import Flask

# -----------------------
# إعدادات البوت
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"

# رموز الأزواج
SYMBOLS = {
    "BTC": "BTC-USD",
    "GOLD": "GC=F",
    "ETH": "ETH-USD",
    "EURUSD": "EURUSD=X",
    "USDJPY": "JPY=X",
    "GBPUSD": "GBPUSD=X"
}

# الإعدادات العامة
TIMEFRAME_BIG = "1h"
CHECK_INTERVAL = 300  # كل 5 دقائق

# -----------------------
# روابط التلغرام
TG_SEND = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
TG_SEND_PHOTO = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"

# Flask app
app = Flask(__name__)

@app.route("/")
def home():
    return "🚀 ICT Smart Money Bot — Running"

# -----------------------
# أدوات مساعدة
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
# بيانات من Yahoo Finance
import pandas as pd
import yfinance as yf

def fetch_yf(symbol, period="2d", interval="1h"):
    try:
        df = yf.download(tickers=symbol, period=period, interval=interval, progress=False, auto_adjust=False)
        if df is None or df.empty:
            return None
        df.index = pd.to_datetime(df.index)
        return df[["Open","High","Low","Close","Volume"]]
    except Exception as e:
        print(f"fetch_yf error for {symbol}:", e)
        return None

# -----------------------
# مؤشرات بسيطة
def ema(series, span): return series.ewm(span=span, adjust=False).mean()
def rsi(series, period=14):
    delta = series.diff()
    up, down = delta.clip(lower=0), -delta.clip(upper=0)
    ma_up = up.ewm(alpha=1/period, adjust=False).mean()
    ma_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = ma_up / (ma_down + 1e-9)
    return 100 - (100/(1+rs))

# -----------------------
# توليد إشارة تداول
def generate_signal_from_df(df):
    try:
        df2 = df.copy()
        df2["EMA20"], df2["EMA50"] = ema(df2["Close"],20), ema(df2["Close"],50)
        df2["RSI"] = rsi(df2["Close"],14)
        last = df2.iloc[-1]
        price = float(last["Close"])
        ema20, ema50, rsi_val = float(last["EMA20"]), float(last["EMA50"]), float(last["RSI"])
        signal = "HOLD"
        if ema20 > ema50 and rsi_val < 70:
            signal = "BUY"
        elif ema20 < ema50 and rsi_val > 30:
            signal = "SELL"
        return {"time": now_utc_str(), "price": price, "signal": signal, "rsi": rsi_val}
    except Exception as e:
        print("signal error:", e)
        return {"time": now_utc_str(), "signal":"HOLD"}

# -----------------------
# التحقق من حداثة البيانات
def data_is_fresh(df, max_age_minutes=30):
    if df is None or df.empty: return False
    last_ts = df.index[-1]
    if last_ts.tzinfo is None:
        last_ts = last_ts.tz_localize(timezone.utc)
    age = datetime.now(timezone.utc) - last_ts
    return age <= timedelta(minutes=max_age_minutes)

# -----------------------
# التحليل والإرسال
def analyze_and_send_all():
    print(f"{now_utc_str()} - Background loop started.")
    send_telegram_text(f"🚀 ICT Bot started successfully. Time: {now_utc_str()}")
    while True:
        try:
            for short, sym in SYMBOLS.items():
                df = fetch_yf(sym, period="5d", interval="1h")
                if not data_is_fresh(df): continue
                sig = generate_signal_from_df(df)
                if sig["signal"] in ("BUY", "SELL"):
                    caption = (
                        f"*ICT Smart Money Signal*  `{short}`\n"
                        f"Time: `{sig['time']}`\n"
                        f"Price: `{sig['price']:.4f}`\n"
                        f"Signal: *{sig['signal']}*\n"
                        f"RSI: `{sig['rsi']:.1f}`\n"
                    )
                    send_telegram_text(caption)
                    print(f"{now_utc_str()} - Sent {sig['signal']} for {short}")
                else:
                    print(f"{now_utc_str()} - {short} HOLD")
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            print("Main loop error:", e)
            time.sleep(10)

# -----------------------
# Keep-alive ping (حتى ما ينام السيرفر المجاني)
def keep_alive():
    while True:
        try:
            url = "https://ict-bot-flask.onrender.com"
            requests.get(url, timeout=10)
            print(f"{now_utc_str()} - Ping keep-alive ✅")
        except Exception:
            pass
        time.sleep(600)  # كل 10 دقايق

# -----------------------
# تشغيل الخلفية وFlask
def start_background():
    Thread(target=analyze_and_send_all, daemon=True).start()
    Thread(target=keep_alive, daemon=True).start()

# -----------------------
# التشغيل التلقائي سواء محلي أو عبر Gunicorn
if __name__ == "__main__":
    start_background()
    port = int(os.environ.get("PORT", 10000))
    print(f"{now_utc_str()} - Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port)
else:
    print(f"{now_utc_str()} - Gunicorn worker starting background thread...")
    start_background()
