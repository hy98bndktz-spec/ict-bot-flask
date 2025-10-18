# bot.py
import os
import time
import io
import requests
import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from flask import Flask
import threading

# -----------------------
# الإعدادات (جاهزة)
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"
TWELVE_API_KEY = "0176951f5a044e719d7e644a6885120a"

# Assets list - استخدم رموز TwelveData (نماذج أدناه)
ASSETS = [
    # TwelveData symbols examples: "BTC/USD", "XAU/USD", "EUR/USD"
    "BTC/USD",
    "XAU/USD",
    "EUR/USD"
]

INTERVAL = "5min"   # نرسل كل 5 دقائق ونحصل بيانات 5m
OUTPUTSIZE = 200    # عدد شمعات نقوم بجلبها (تكفي لحساب EMA/RSI)

# -----------------------
# إعداد Flask لإبقاء السيرفر نشط
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 ICT Smart Money Bot is running (5m timeframe)"

# -----------------------
# مساعدات للـ Telegram
def send_telegram_message(text, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode
    }
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print("Failed to send message:", e)

def send_telegram_photo(image_bytes, caption=""):
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", image_bytes)}
    data = {"chat_id": CHAT_ID, "caption": caption, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=data, files=files, timeout=30)
    except Exception as e:
        print("Failed to send photo:", e)

def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# -----------------------
# جلب بيانات من TwelveData
def get_data_twelve(symbol, interval=INTERVAL, outputsize=OUTPUTSIZE):
    """
    returns DataFrame with index datetime and columns: open, high, low, close, volume
    """
    base = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "format": "JSON",
        "apikey": TWELVE_API_KEY
    }
    try:
        r = requests.get(base, params=params, timeout=20)
        data = r.json()
        if "values" not in data:
            raise ValueError(data.get("message") or data.get("status") or str(data))
        rows = data["values"]
        # values are descending (newest first) in TwelveData => reverse
        df = pd.DataFrame(rows)[::-1].reset_index(drop=True)
        # convert types
        df["datetime"] = pd.to_datetime(df["datetime"])
        df.set_index("datetime", inplace=True)
        df = df.astype({
            "open": "float",
            "high": "float",
            "low": "float",
            "close": "float",
            "volume": "float"
        }, errors="ignore")
        # keep only necessary columns
        df = df[["open", "high", "low", "close", "volume"]]
        return df
    except Exception as e:
        raise

# -----------------------
# مؤشرات (EMA, RSI) بدون pandas_ta
def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def rsi(series, length=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=length-1, adjust=False).mean()
    ma_down = down.ewm(com=length-1, adjust=False).mean()
    rs = ma_up / ma_down
    rsi = 100 - (100 / (1 + rs))
    return rsi

def compute_indicators(df):
    if df is None or df.empty or len(df) < 5:
        return df
    df = df.copy()
    df["EMA20"] = ema(df["close"], 20)
    df["EMA50"] = ema(df["close"], 50)
    df["RSI"] = rsi(df["close"], 14)
    df["OB"] = df["high"].rolling(window=20, min_periods=1).max()
    df["OS"] = df["low"].rolling(window=20, min_periods=1).min()
    return df

# -----------------------
# توليد الإشارة وفق مبادئ ICT بسيطة (قابلة للتعديل)
def generate_signal(df, symbol):
    df = compute_indicators(df)
    if df is None or df.empty or len(df) < 5:
        return {"symbol": symbol, "signal": "NO_DATA"}

    last = df.iloc[-1]
    price = float(last["close"])
    ema20 = float(last.get("EMA20", math.nan))
    ema50 = float(last.get("EMA50", math.nan))
    rsi_val = float(last.get("RSI", math.nan))

    signal = "HOLD"
    tp = None

    # شروط مبسطة:
    if not math.isnan(ema20) and not math.isnan(ema50):
        if ema20 > ema50 and rsi_val < 70:
            signal = "BUY"
            tp = price * 1.002  # هدف بسيط 0.2%
        elif ema20 < ema50 and rsi_val > 30:
            signal = "SELL"
            tp = price * 0.998

    return {
        "symbol": symbol,
        "price": price,
        "signal": signal,
        "tp": tp,
        "rsi": rsi_val,
        "time": now_str()
    }

# -----------------------
# رسم الشارت (يرجع BytesIO)
def generate_chart(df, sig):
    try:
        plt.style.use('classic')
    except:
        pass
    fig, ax = plt.subplots(figsize=(8,4))
    ax.plot(df.index, df["close"], label="Close", linewidth=1)
    if "EMA20" in df.columns:
        ax.plot(df.index, df["EMA20"], label="EMA20", linewidth=1)
    if "EMA50" in df.columns:
        ax.plot(df.index, df["EMA50"], label="EMA50", linewidth=1)
    ax.set_title(f"{sig['symbol']}  {sig['signal']}  @{sig['price']:.4f}")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.3)

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    buf.seek(0)
    return buf

# -----------------------
# عملية التحليل والإرسال
def analyze_and_send():
    for symbol in ASSETS:
        try:
            df = get_data_twelve(symbol)
            if df is None or df.empty:
                send_telegram_message(f"⚠️ No data for {symbol} (TwelveData).")
                continue

            sig = generate_signal(df, symbol)

            if sig["signal"] == "NO_DATA":
                send_telegram_message(f"⚠️ Not enough data for {symbol}.")
                continue

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
            caption += "⚙️ Strategy: Michael ICT - Smart Money Concepts"

            # if signal is not HOLD -> send chart + caption
            if sig["signal"] in ("BUY", "SELL"):
                chart = generate_chart(df, sig)
                send_telegram_photo(chart, caption)
                print(now_str(), f"Sent {sig['signal']} for {symbol}")
            else:
                # optionally send a short message for HOLD if you want:
                print(now_str(), f"{symbol}: HOLD")

        except Exception as e:
            # be explicit and safe with error message
            errtxt = str(e)
            send_telegram_message(f"⚠️ Error analyzing {symbol}: {errtxt}")

# -----------------------
# Loop runner (threaded)
def start_loop():
    while True:
        analyze_and_send()
        # run every 5 minutes
        time.sleep(300)

# -----------------------
if __name__ == "__main__":
    # notify start once
    try:
        send_telegram_message("🚀 ICT Smart Money Bot started successfully (5m timeframe)")
    except Exception:
        pass

    # start worker thread
    t = threading.Thread(target=start_loop, daemon=True)
    t.start()

    # run flask app (Render requires binding to PORT env)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
