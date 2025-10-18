# bot.py
import os
import time
import io
import requests
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from flask import Flask
import threading

# -----------------------
# إعدادات البوت
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"
API_KEY = "0176951f5a044e719d7e644a6885120a"  # مفتاح Twelve Data

# -----------------------
# إعداد Flask لإبقاء السيرفر نشط
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 ICT Smart Money Bot is running (5m timeframe)"

# -----------------------
# وظائف مساعدة
def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text})

def send_telegram_photo(image_bytes, caption=""):
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", image_bytes)}
    data = {"chat_id": CHAT_ID, "caption": caption, "parse_mode": "Markdown"}
    requests.post(url, data=data, files=files)

def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# -----------------------
# جلب البيانات من Twelve Data
def get_data(symbol):
    url = f"https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": "5min",
        "outputsize": 200,
        "apikey": API_KEY
    }
    r = requests.get(url, params=params)
    data = r.json()

    if "values" not in data:
        raise Exception(f"API Error for {symbol}: {data}")

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime")
    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["open"] = df["open"].astype(float)
    return df

# -----------------------
# حساب المؤشرات
def compute_indicators(df):
    df["EMA20"] = df["close"].ewm(span=20).mean()
    df["EMA50"] = df["close"].ewm(span=50).mean()
    df["RSI"] = compute_rsi(df["close"])
    return df

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# -----------------------
# توليد الإشارة
def generate_signal(df, symbol):
    df = compute_indicators(df)
    last = df.iloc[-1]
    price = last["close"]
    ema20, ema50, rsi = last["EMA20"], last["EMA50"], last["RSI"]

    signal = "HOLD"
    tp = None

    if ema20 > ema50 and rsi < 70:
        signal = "BUY"
        tp = price * 1.002
    elif ema20 < ema50 and rsi > 30:
        signal = "SELL"
        tp = price * 0.998

    return {
        "symbol": symbol,
        "price": price,
        "signal": signal,
        "tp": tp,
        "rsi": rsi,
        "time": now_str()
    }

# -----------------------
# رسم الشارت
def generate_chart(df, signal):
    plt.figure(figsize=(8,4))
    plt.plot(df["datetime"], df["close"], label="Price", linewidth=1.5)
    plt.plot(df["datetime"], df["EMA20"], label="EMA20")
    plt.plot(df["datetime"], df["EMA50"], label="EMA50")
    plt.title(f"{signal['symbol']} | {signal['signal']} | {signal['time']}")
    plt.legend()
    plt.grid(True)
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches="tight")
    plt.close()
    buf.seek(0)
    return buf

# -----------------------
# تحليل الأصول
def analyze_and_send():
    assets = ["BTC/USD", "XAU/USD", "EUR/USD"]
    for symbol in assets:
        try:
            df = get_data(symbol)
            sig = generate_signal(df, symbol)

            if sig["signal"] != "HOLD":
                caption = (
                    f"📊 *ICT Smart Money Signal*\n"
                    f"Asset: {sig['symbol']}\n"
                    f"Time: {sig['time']}\n"
                    f"Price: ${sig['price']:.2f}\n"
                    f"Signal: {sig['signal']} 📈\n"
                    f"RSI: {sig['rsi']:.1f}\n"
                    f"🎯 Take Profit: {sig['tp']:.2f}\n"
                    f"⚙️ Strategy: Michael ICT - Smart Money Concepts"
                )
                chart = generate_chart(df, sig)
                send_telegram_photo(chart, caption)
            else:
                print(f"{now_str()} - {symbol}: HOLD")

        except Exception as e:
            send_telegram_message(f"⚠️ Error analyzing {symbol}: {e}")

# -----------------------
# تشغيل البوت
if __name__ == "__main__":
    send_telegram_message("🚀 ICT Smart Money Bot started successfully (5m timeframe)")

    def loop_run():
        while True:
            analyze_and_send()
            time.sleep(300)  # كل 5 دقائق

    threading.Thread(target=loop_run, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
