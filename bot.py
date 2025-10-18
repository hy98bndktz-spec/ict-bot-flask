# bot.py (مُنقح)
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
# إعدادات البوت (افضل: ضعها في Environment Variables على Render)
TOKEN = os.environ.get("BOT_TOKEN", "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A")
CHAT_ID = os.environ.get("CHAT_ID", "690864747")

# الرموز المراد متابعتها
BINANCE_SYMBOL = "BTCUSDT"      # بيتكوين في Binance
YFINANCE_SYMBOL = "GC=F"        # ذهب (Gold futures) على Yahoo Finance

# وقت الفريم وحدود الاسترجاع
TIMEFRAME = "5m"                # فريم 5 دقائق
FETCH_LIMIT = 500

# ملفات لوج بسيطة (خيارية)
SIGNAL_CSV = "signals_log.csv"

# -----------------------
TG_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

# Flask app (لـ keep-alive على Render)
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 ICT Smart Money Bot is running (5m timeframe)"

# -----------------------
def send_telegram(text):
    try:
        payload = {"chat_id": CHAT_ID, "text": text}
        r = requests.post(TG_URL, json=payload, timeout=10)
        if not r.ok:
            print("Telegram API returned:", r.status_code, r.text)
        return r.ok
    except Exception as e:
        print("Telegram Error:", e)
        return False

def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# -----------------------
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
    if df is None or df.empty:
        return pd.DataFrame()  # فارغ آمن
    df = df.dropna()
    df.index = pd.to_datetime(df.index)
    df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
    return df[["open","high","low","close","volume"]]

# -----------------------
def compute_indicators(df):
    # تأكد من وجود أعمدة وقيم كافية
    df = df.copy()
    if len(df) < 20:
        return df  # لا نضيف مؤشرات إذا كانت البيانات قليلة
    df["EMA12"] = ta.ema(df["close"], length=12)
    df["EMA26"] = ta.ema(df["close"], length=26)
    df["RSI14"] = ta.rsi(df["close"], length=14)
    return df

def detect_structure(df):
    # حماية لو الداتا قصيرة
    if len(df) < 4:
        return "uncertain"
    highs = df['high']
    lows = df['low']
    try:
        if highs.iloc[-1] > highs.iloc[-3] and lows.iloc[-1] > lows.iloc[-3]:
            return "uptrend"
        elif highs.iloc[-1] < highs.iloc[-3] and lows.iloc[-1] < lows.iloc[-3]:
            return "downtrend"
        else:
            return "sideways"
    except Exception:
        return "uncertain"

def generate_signal(df):
    df = compute_indicators(df)
    if df.empty or len(df) < 20:
        return {"signal":"HOLD","price":None,"rsi":None,"structure":"insufficient_data","reasons":[],"time":now_str()}

    last = df.iloc[-1]
    ema12 = last.get("EMA12", None)
    ema26 = last.get("EMA26", None)
    rsi = last.get("RSI14", None)
    price = float(last["close"])
    structure = detect_structure(df)

    signal = "HOLD"
    reasons = []

    # تأكد أن المؤشرات تحتوي أرقام
    if pd.notna(ema12) and pd.notna(ema26) and pd.notna(rsi):
        if ema12 > ema26 and rsi < 70 and structure == "uptrend":
            signal = "BUY"
            reasons.append("Smart Money Bias: bullish structure + EMA + RSI")
        elif ema12 < ema26 and rsi > 30 and structure == "downtrend":
            signal = "SELL"
            reasons.append("Smart Money Bias: bearish structure + EMA + RSI")

    return {
        "price": price,
        "signal": signal,
        "rsi": float(rsi) if pd.notna(rsi) else None,
        "structure": structure,
        "reasons": reasons,
        "time": now_str()
    }

# -----------------------
def append_csv(filename, row):
    try:
        df = pd.DataFrame([row])
        if not os.path.exists(filename):
            df.to_csv(filename, index=False)
        else:
            df.to_csv(filename, mode='a', header=False, index=False)
    except Exception as e:
        print("CSV write error:", e)

# -----------------------
def analyze_and_send():
    assets = [
        ("BTCUSDT", fetch_binance_klines),
        (YFINANCE_SYMBOL, fetch_yfinance_klines)
    ]
    for sym, fetcher in assets:
        try:
            if "BTC" in sym:
                df = fetcher(sym, interval=TIMEFRAME, limit=FETCH_LIMIT)
            else:
                df = fetcher(sym, interval=TIMEFRAME, period="2d")

            if df is None or df.empty:
                print(f"{now_str()} - No data for {sym}")
                continue

            sig = generate_signal(df)
            # سجل دائمًا
            append_csv(SIGNAL_CSV, {
                "checked_at": now_str(),
                "symbol": sym,
                "price": sig.get("price"),
                "signal": sig.get("signal"),
                "rsi": sig.get("rsi"),
                "structure": sig.get("structure"),
                "reasons": "|".join(sig.get("reasons", []))
            })

            if sig["signal"] != "HOLD":
                text = (
                    f"📈 ICT Smart Money Signal ({sym})\n"
                    f"Time: {sig['time']}\n"
                    f"Price: {sig['price']:.2f}\n"
                    f"Signal: {sig['signal']}\n"
                    f"RSI: {sig['rsi']}\n"
                    f"Structure: {sig['structure']}\n"
                    f"Reason: {', '.join(sig['reasons'])}\n"
                    f"⚙️ Strategy: Michael ICT - Smart Money Concepts (5m)"
                )
                send_telegram(text)
            else:
                print(f"{now_str()} - {sym} HOLD")
        except Exception as e:
            err = f"⚠️ Error analyzing {sym}: {e}"
            print(err)
            send_telegram(err)

# -----------------------
if __name__ == "__main__":
    # إعادة تذكير: يفضل أن توضع المتغيرات في إعدادات Render بدل الكود
    send_telegram("🚀 ICT Smart Money Bot started (5m timeframe) - demo")
    def loop_run():
        while True:
            analyze_and_send()
            time.sleep(60)

    threading.Thread(target=loop_run, daemon=True).start()
    # ربط على PORT الذي يحدده Render
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
