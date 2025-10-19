# main.py — ICT Smart Money Bot (MarketStack Version)
# يستخدم MarketStack API لجلب الأسعار بدلاً من yfinance

import os
import time
import io
import math
import traceback
import requests
from datetime import datetime, timezone, timedelta
from threading import Thread
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from flask import Flask

# ==============================
# إعدادات البوت
# ==============================
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"
MARKETSTACK_KEY = "f82dced376934dc0ab99e79afd3ca844"

# أزواج التحليل
SYMBOLS = {
    "BTC": "BTCUSD",
    "GOLD": "XAUUSD",
    "ETH": "ETHUSD",
    "EURUSD": "EURUSD",
    "USDJPY": "USDJPY",
    "GBPUSD": "GBPUSD"
}

CHECK_INTERVAL = 300  # كل 5 دقائق
TG_SEND = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
TG_SEND_PHOTO = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"

app = Flask(__name__)

@app.route("/")
def home():
    return "🚀 ICT Smart Money Bot — Running (MarketStack Source)"

# ==============================
# أدوات مساعدة
# ==============================
def now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def send_telegram_text(text):
    try:
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
        r = requests.post(TG_SEND, json=payload, timeout=10)
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
        return r.ok
    except Exception as e:
        print("Telegram photo send error:", e)
        return False

# ==============================
# جلب البيانات من MarketStack
# ==============================
def fetch_marketstack(symbol, limit=100):
    try:
        url = f"http://api.marketstack.com/v1/intraday?access_key={MARKETSTACK_KEY}&symbols={symbol}&interval=1h&limit={limit}"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            print(f"MarketStack HTTP error {r.status_code} for {symbol}")
            return None
        js = r.json()
        if "data" not in js or not js["data"]:
            print(f"No data for {symbol}")
            return None
        df = pd.DataFrame(js["data"])
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df = df.rename(columns={
            "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"
        })
        df = df[["date", "Open", "High", "Low", "Close", "Volume"]].sort_values("date")
        df.set_index("date", inplace=True)
        return df
    except Exception as e:
        print(f"fetch_marketstack error for {symbol}:", e)
        return None

# ==============================
# المؤشرات
# ==============================
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

# ==============================
# توليد الإشارة
# ==============================
def generate_signal_from_df(df):
    try:
        df2 = df.copy()
        df2["EMA20"] = ema(df2["Close"], 20)
        df2["EMA50"] = ema(df2["Close"], 50)
        df2["RSI"] = rsi(df2["Close"], 14)
        last = df2.iloc[-1]
        price = float(last["Close"])
        ema20, ema50, rsi_val = float(last["EMA20"]), float(last["EMA50"]), float(last["RSI"])

        signal = "HOLD"
        if ema20 > ema50 and rsi_val < 70:
            signal = "BUY"
        elif ema20 < ema50 and rsi_val > 30:
            signal = "SELL"

        atr_val = abs(df2["High"].iloc[-14:].max() - df2["Low"].iloc[-14:].min()) / 14
        sl, tp = None, None
        if signal == "BUY":
            sl, tp = price - 1.2*atr_val, price + 2.0*atr_val
        elif signal == "SELL":
            sl, tp = price + 1.2*atr_val, price - 2.0*atr_val

        return {"time": now_utc_str(), "price": price, "signal": signal, "sl": sl, "tp": tp, "rsi": rsi_val}
    except Exception as e:
        print("generate_signal_from_df error:", e)
        return {"time": now_utc_str(), "price": None, "signal": "HOLD"}

# ==============================
# رسم الشارت
# ==============================
def generate_chart(df, symbol, sig):
    try:
        df_plot = df.tail(100)
        df_plot["EMA20"] = ema(df_plot["Close"], 20)
        df_plot["EMA50"] = ema(df_plot["Close"], 50)
        apds = [
            mpf.make_addplot(df_plot["EMA20"], width=0.8),
            mpf.make_addplot(df_plot["EMA50"], width=0.8)
        ]
        style = mpf.make_mpf_style(base_mpf_style="nightclouds")
        fig, ax = mpf.plot(df_plot, type='candle', style=style, addplot=apds,
                           returnfig=True, figsize=(9, 4), tight_layout=True)
        ax[0].set_title(f"{symbol} | {sig['signal']} | {sig['time']}", color="white", fontsize=10)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        return buf
    except Exception as e:
        print("generate_chart error:", e)
        return None

# ==============================
# الحلقة الرئيسية
# ==============================
def analyze_and_send_all():
    print(f"{now_utc_str()} - Starting background loop.")
    send_telegram_text(f"🚀 ICT Bot (MarketStack) started successfully — {now_utc_str()}")
    while True:
        try:
            for short, sym in SYMBOLS.items():
                df = fetch_marketstack(sym)
                if df is None or len(df) < 20:
                    print(f"No data for {sym}")
                    continue
                sig = generate_signal_from_df(df)
                if sig["signal"] in ["BUY", "SELL"]:
                    chart_buf = generate_chart(df, short, sig)
                    caption = (f"*ICT Smart Money Signal*  `{short}`\n"
                               f"Time: `{sig['time']}`\n"
                               f"Price: `{sig['price']:.4f}`\n"
                               f"Signal: *{sig['signal']}*\n"
                               f"RSI: `{sig['rsi']:.1f}`\n"
                               f"SL: `{sig['sl']:.4f}` | TP: `{sig['tp']:.4f}`\n"
                               f"_Data: MarketStack API_")
                    if chart_buf:
                        send_telegram_photo(chart_buf, caption)
                    else:
                        send_telegram_text(caption)
                    print(f"Sent {sig['signal']} for {short}")
                else:
                    print(f"{short} HOLD")
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            print("Main loop error:", e)
            time.sleep(10)

# ==============================
# تشغيل السيرفر و البوت
# ==============================
def start_background():
    t = Thread(target=analyze_and_send_all, daemon=True)
    t.start()

if __name__ == "__main__":
    start_background()
    port = int(os.environ.get("PORT", 10000))
    print(f"{now_utc_str()} - Flask keepalive on port {port}")
    app.run(host="0.0.0.0", port=port)
