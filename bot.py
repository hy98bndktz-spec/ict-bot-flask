# bot.py
import os
import time
import requests
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from datetime import datetime, timezone
from flask import Flask
import threading

# إعدادات البوت
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"

# أزواج العملات
ASSETS = {
    "XAUUSD": "GC=F",    # الذهب
    "BTCUSD": "BTC-USD", # بيتكوين
    "EURUSD": "EURUSD=X" # اليورو مقابل الدولار
}

TIMEFRAME_FAST = "5m"
TIMEFRAME_SLOW = "1h"
TG_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 ICT Smart Money Bot is live (5m/1h Strategy)"

def send_telegram(text):
    """إرسال رسالة إلى تيليجرام"""
    try:
        payload = {"chat_id": CHAT_ID, "text": text}
        requests.post(TG_URL, json=payload, timeout=10)
    except Exception as e:
        print("Telegram Error:", e)

def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def fetch_data(symbol, interval="5m", period="2d"):
    """جلب البيانات من Yahoo Finance"""
    df = yf.download(tickers=symbol, period=period, interval=interval, progress=False)
    if df.empty:
        return pd.DataFrame()
    df = df.dropna()
    df.index = pd.to_datetime(df.index)
    df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
    return df[["open","high","low","close","volume"]]

def compute_indicators(df):
    df["EMA12"] = ta.ema(df["close"], length=12)
    df["EMA26"] = ta.ema(df["close"], length=26)
    df["RSI14"] = ta.rsi(df["close"], length=14)
    df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    return df.dropna()

def detect_structure(df):
    highs, lows = df['high'], df['low']
    if len(df) < 5:
        return "sideways"
    if highs.iloc[-1] > highs.iloc[-4] and lows.iloc[-1] > lows.iloc[-4]:
        return "uptrend"
    elif highs.iloc[-1] < highs.iloc[-4] and lows.iloc[-1] < lows.iloc[-4]:
        return "downtrend"
    return "sideways"

def generate_signal(df_5m, df_1h):
    """توليد إشارات وفق منهج ICT Smart Money"""
    df_5m = compute_indicators(df_5m)
    df_1h = compute_indicators(df_1h)

    fast = df_5m.iloc[-1]
    slow = df_1h.iloc[-1]
    structure_h1 = detect_structure(df_1h)

    signal = "HOLD"
    reasons = []

    if slow["EMA12"] > slow["EMA26"] and structure_h1 == "uptrend":
        if fast["EMA12"] > fast["EMA26"] and fast["RSI14"] < 70:
            signal = "BUY"
            reasons.append("EMA crossover + RSI below 70 + bullish structure (ICT bias)")

    elif slow["EMA12"] < slow["EMA26"] and structure_h1 == "downtrend":
        if fast["EMA12"] < fast["EMA26"] and fast["RSI14"] > 30:
            signal = "SELL"
            reasons.append("EMA crossover + RSI above 30 + bearish structure (ICT bias)")

    return {
        "time": now_str(),
        "price": fast["close"],
        "signal": signal,
        "rsi": fast["RSI14"],
        "structure_h1": structure_h1,
        "reason": ", ".join(reasons) if reasons else "No clear entry"
    }

def analyze_and_send():
    """تحليل كل زوج وإرسال الإشارات"""
    for name, symbol in ASSETS.items():
        try:
            df_5m = fetch_data(symbol, interval=TIMEFRAME_FAST, period="2d")
            df_1h = fetch_data(symbol, interval=TIMEFRAME_SLOW, period="7d")

            if df_5m.empty or df_1h.empty:
                print(f"⚠️ Missing data for {name}")
                continue

            sig = generate_signal(df_5m, df_1h)
            if sig["signal"] != "HOLD":
                msg = (
                    f"📊 ICT Smart Money Signal\n"
                    f"Asset: {name}\n"
                    f"Time: {sig['time']}\n"
                    f"Price: {sig['price']:.2f}\n"
                    f"Signal: {sig['signal']}\n"
                    f"RSI: {sig['rsi']:.2f}\n"
                    f"Structure (1H): {sig['structure_h1']}\n"
                    f"Reason: {sig['reason']}\n"
                    f"⚙️ Framework: Michael ICT - Smart Money Concepts\n"
                    f"🕒 TF: 1H / Entry: 5M"
                )
                send_telegram(msg)
            else:
                print(f"{now_str()} - {name} HOLD")

        except Exception as e:
            err = f"⚠️ Error analyzing {name}: {e}"
            print(err)
            send_telegram(err)

def loop_run():
    """تشغيل التحليل بشكل دوري"""
    while True:
        analyze_and_send()
        time.sleep(60 * 5)  # تحليل كل 5 دقائق

if __name__ == "__main__":
    send_telegram("🚀 ICT Smart Money Bot started (1H/5M Strategy)")
    threading.Thread(target=loop_run, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
