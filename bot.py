# bot.py
import os
import time
import io
import requests
import pandas as pd
import pandas_ta as ta
import yfinance as yf
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from flask import Flask
import threading

# -----------------------
# إعدادات البوت
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"

# -----------------------
# إعداد Flask لإبقاء السيرفر نشط
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 ICT Smart Money Bot is running (5m timeframe)"

# -----------------------
# إرسال رسالة نصية
def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})

# -----------------------
# إرسال صورة مع تعليق
def send_telegram_photo(image_bytes, caption=""):
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", image_bytes)}
    data = {"chat_id": CHAT_ID, "caption": caption, "parse_mode": "Markdown"}
    requests.post(url, data=data, files=files)

# -----------------------
def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# -----------------------
# حساب المؤشرات
def compute_indicators(df):
    df["EMA20"] = ta.ema(df["close"], length=20)
    df["EMA50"] = ta.ema(df["close"], length=50)
    df["RSI"] = ta.rsi(df["close"], length=14)
    return df

# -----------------------
# توليد الإشارة
def generate_signal(df, symbol):
    df = compute_indicators(df)
    last = df.iloc[-1]

    price = last["close"]
    ema20, ema50, rsi = last["EMA20"], last["EMA50"], last["RSI"]

    signal = "HOLD"
    tp = None

    # منطق الإشارة
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
# توليد الشارت
def generate_chart(df, signal):
    plt.figure(figsize=(8,4))
    plt.plot(df.index, df["close"], label="Price", linewidth=1.5)
    plt.plot(df.index, df["EMA20"], label="EMA20")
    plt.plot(df.index, df["EMA50"], label="EMA50")
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
    assets = ["BTC-USD", "GC=F", "EURUSD=X"]
    for symbol in assets:
        try:
            df = yf.download(symbol, period="2d", interval="5m", progress=False)
            if df.empty or len(df) < 20:
                continue

            df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"}, inplace=True)
            sig = generate_signal(df, symbol)

            if sig["signal"] != "HOLD":
                caption = (
                    f"📊 *ICT Smart Money Signal*\n\n"
                    f"💎 *Asset:* {sig['symbol']}\n"
                    f"🕒 *Time:* {sig['time']}\n"
                    f"💰 *Price:* ${sig['price']:.2f}\n"
                    f"📈 *Signal:* {sig['signal']}\n"
                    f"📊 *RSI:* {sig['rsi']:.1f}\n"
                    f"🎯 *Take Profit:* {sig['tp']:.2f}\n\n"
                    f"⚙️ Strategy: Michael ICT Smart Money Concepts"
                )
                chart = generate_chart(df, sig)
                send_telegram_photo(chart, caption)
            else:
                print(f"{now_str()} - {symbol}: HOLD")

        except Exception as e:
            send_telegram_message(f"⚠️ Error analyzing {symbol}: {e}")

# -----------------------
# التشغيل
if __name__ == "__main__":
    send_telegram_message("🚀 *ICT Smart Money Bot started successfully* (5m timeframe)")

    def loop_run():
        while True:
            analyze_and_send()
            time.sleep(300)  # كل 5 دقائق

    threading.Thread(target=loop_run, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
