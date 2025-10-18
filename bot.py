# bot.py
import os
import time
import json
import requests
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from datetime import datetime, timezone
from flask import Flask
import threading

# -----------------------
# إعدادات البوت
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"

# إعدادات الرموز
TIMEFRAME = "5m"
FETCH_LIMIT = 500

# -----------------------
# روابط Telegram API
TG_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

# إنشاء تطبيق Flask لإبقاء السيرفر شغال
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 ICT Smart Money Bot is running (5m timeframe)"

# -----------------------
# دوال المساعدة
def send_telegram(text):
    """إرسال رسالة إلى تيليجرام"""
    try:
        payload = {"chat_id": CHAT_ID, "text": text}
        requests.post(TG_URL, json=payload, timeout=10)
    except Exception as e:
        print("Telegram Error:", e)

def now_str():
    """الوقت الحالي UTC"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# -----------------------
# جلب البيانات
def fetch_binance_klines(symbol, interval="5m", limit=500):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    df = pd.DataFrame(data, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_asset_volume","num_trades",
        "taker_buy_base","taker_buy_quote","ignore"
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("open_time", inplace=True)
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    return df[["open","high","low","close","volume"]]

def fetch_yfinance_klines(ticker, interval="5m", period="2d"):
    df = yf.download(tickers=ticker, period=period, interval=interval, progress=False)
    if df.empty:
        return df
    df = df.dropna()
    df.index = pd.to_datetime(df.index)
    df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
    return df[["open","high","low","close","volume"]]

# -----------------------
# المؤشرات الفنية وتحليل الاتجاه
def compute_indicators(df):
    df["EMA12"] = ta.ema(df["close"], length=12)
    df["EMA26"] = ta.ema(df["close"], length=26)
    df["RSI14"] = ta.rsi(df["close"], length=14)
    return df

def detect_structure(df):
    highs, lows = df['high'], df['low']
    struct = "sideways"

    # تأكد من وجود بيانات كافية
    if len(df) < 4:
        return struct

    last_high = float(highs.iloc[-1])
    prev_high = float(highs.iloc[-3])
    last_low = float(lows.iloc[-1])
    prev_low = float(lows.iloc[-3])

    if last_high > prev_high and last_low > prev_low:
        struct = "uptrend"
    elif last_high < prev_high and last_low < prev_low:
        struct = "downtrend"

    return struct

def generate_signal(df):
    df = compute_indicators(df)
    last = df.iloc[-1]
    ema12, ema26, rsi = last["EMA12"], last["EMA26"], last["RSI14"]
    structure = detect_structure(df)
    price = last["close"]

    signal = "HOLD"
    reasons = []

    # منطق الذكاء المالي (Smart Money)
    if ema12 > ema26 and rsi < 70 and structure == "uptrend":
        signal = "BUY"
        reasons.append("Smart Money Bias: bullish structure + EMA + RSI")

    elif ema12 < ema26 and rsi > 30 and structure == "downtrend":
        signal = "SELL"
        reasons.append("Smart Money Bias: bearish structure + EMA + RSI")

    return {
        "price": price,
        "signal": signal,
        "rsi": rsi,
        "structure": structure,
        "reasons": reasons,
        "time": now_str()
    }

# -----------------------
def analyze_and_send():
    """تحليل السوق وإرسال الإشارات"""
    assets = [
        ("BTCUSDT", fetch_binance_klines),
        ("GC=F", fetch_yfinance_klines)
    ]
    for symbol, fetcher in assets:
        try:
            if "BTC" in symbol:
                df = fetcher(symbol, interval=TIMEFRAME, limit=FETCH_LIMIT)
            else:
                df = fetcher(symbol, interval=TIMEFRAME, period="2d")

            if df.empty:
                continue

            sig = generate_signal(df)

            if sig["signal"] != "HOLD":
                text = (
                    f"📊 ICT Smart Money Signal ({symbol})\n"
                    f"Time: {sig['time']}\n"
                    f"Price: {sig['price']:.2f}\n"
                    f"Signal: {sig['signal']}\n"
                    f"RSI: {sig['rsi']:.2f}\n"
                    f"Structure: {sig['structure']}\n"
                    f"Reason: {', '.join(sig['reasons'])}\n"
                    f"⚙️ Strategy: Michael ICT - Smart Money Concepts (5m)"
                )
                send_telegram(text)
            else:
                print(f"{now_str()} - {symbol} HOLD")

        except Exception as e:
            err = f"⚠️ Error analyzing {symbol}: {e}"
            print(err)
            send_telegram(err)

# -----------------------
if __name__ == "__main__":
    send_telegram("🚀 ICT Smart Money Bot started (5m timeframe) - demo")

    def loop_run():
        while True:
            analyze_and_send()
            time.sleep(60)  # تحليل كل دقيقة

    threading.Thread(target=loop_run, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
