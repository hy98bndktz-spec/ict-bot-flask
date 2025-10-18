# bot.py
import os
import time
import io
import json
import threading
from datetime import datetime, timezone
import requests
import pandas as pd
import matplotlib.pyplot as plt
from flask import Flask, Response

# ---------- إعدادات من متغيرات بيئة (ضعها في Render Environment) ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")   # ضع هنا token في settings > Environment
CHAT_ID = os.environ.get("CHAT_ID")       # وضع chat_id هنا أيضاً

if not BOT_TOKEN or not CHAT_ID:
    raise RuntimeError("Missing BOT_TOKEN or CHAT_ID environment variables.")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
INTERVAL = "5m"
LIMIT = 200
FRESH_MINUTES = 15

# ---------- دوال مساعدة ----------

def send_message(text):
    url = TELEGRAM_API + "/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print("tg send_message error:", e)

def send_photo_bytes(buf, caption=None):
    url = TELEGRAM_API + "/sendPhoto"
    files = {"photo": ("chart.png", buf, "image/png")}
    data = {"chat_id": CHAT_ID}
    if caption:
        data["caption"] = caption
        data["parse_mode"] = "Markdown"
    try:
        r = requests.post(url, files=files, data=data, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print("tg send_photo error:", e, getattr(e, "response", None))

def fetch_klines(symbol="BTCUSDT", interval=INTERVAL, limit=LIMIT):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        r = requests.get(BINANCE_KLINES, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(data, columns=[
            "open_time","open","high","low","close","volume","close_time",
            "quote_av","trades","tb_base_av","tb_quote_av","ignore"
        ])
        df["datetime"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df.set_index("datetime", inplace=True)
        for c in ["open","high","low","close","volume"]:
            df[c] = df[c].astype(float)
        return df[["open","high","low","close","volume"]]
    except Exception as e:
        print("fetch_klines error:", e)
        return None

def compute_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.ewm(com=period-1, adjust=False).mean()
    ma_down = down.ewm(com=period-1, adjust=False).mean()
    rs = ma_up / ma_down
    rsi = 100 - (100 / (1 + rs))
    return rsi

def make_chart_buffer(df, title="Chart"):
    plt.switch_backend("Agg")
    fig, ax = plt.subplots(figsize=(8,4))
    ax.plot(df.index, df["close"], label="close")
    ax.set_title(title)
    ax.grid(True, alpha=0.2)
    ax.legend()
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    buf.seek(0)
    return buf

def is_fresh(df):
    if df is None or df.empty: return False
    last_time = df.index[-1]
    now = datetime.now(timezone.utc)
    return (now - last_time).total_seconds() <= FRESH_MINUTES * 60

# ---------- عملية التحليل وارسال النتائج ----------
SYMBOLS = {
    "XAU": "XAUUSDT",
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "EURUSD": "EURUSDT",
    "GBPUSD": "GBPUSDT",
    "USDJPY": "USDJPY"
}

def analyze_and_send():
    for short, symbol in SYMBOLS.items():
        try:
            df = fetch_klines(symbol)
            if df is None or len(df) < 30:
                send_message(f"⚠️ Error analyzing {short}: no data for {symbol}.")
                continue
            if not is_fresh(df):
                send_message(f"⚠️ Stale data for {symbol}.")
                continue

            df["RSI"] = compute_rsi(df["close"])
            last = df.iloc[-1]
            rsi_val = last["RSI"]
            price = last["close"]

            if pd.isna(rsi_val):
                send_message(f"⚠️ Error analyzing {short}: RSI NaN.")
                continue

            if rsi_val < 30:
                sig = "BUY 🟢"
            elif rsi_val > 70:
                sig = "SELL 🔴"
            else:
                sig = "HOLD ⚪"

            caption = (
                f"*{short} / {symbol}*  \n"
                f"Time (UTC): `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}`  \n"
                f"Price: `{price:.4f}`  \n"
                f"RSI: `{rsi_val:.2f}`  \n"
                f"Signal: *{sig}*"
            )

            # chart
            try:
                buf = make_chart_buffer(df, title=f"{symbol} close")
                send_photo_bytes(buf, caption=caption)
            except Exception as e:
                print("chart/send error:", e)
                send_message(caption)

        except Exception as e:
            print("analyze error:", e)
            send_message(f"⚠️ Error analyzing {symbol}: {e}")

# ---------- background scheduler using thread ----------
def scheduler_loop(stop_event):
    # run immediately on start, then every 5 minutes
    while not stop_event.is_set():
        try:
            analyze_and_send()
        except Exception as e:
            print("scheduler_loop error:", e)
        # sleep 5 minutes (poll for stop_event every second)
        for _ in range(300):
            if stop_event.is_set():
                break
            time.sleep(1)

# ---------- Flask app (so Render sees a web process) ----------
app = Flask(__name__)
stop_event = threading.Event()
worker_thread = None

@app.route("/")
def index():
    return Response("OK - bot running", mimetype="text/plain")

def start_background():
    global worker_thread
    if worker_thread and worker_thread.is_alive():
        return
    worker_thread = threading.Thread(target=scheduler_loop, args=(stop_event,), daemon=True)
    worker_thread.start()

# ---------- main ----------
if __name__ == "__main__":
    # start background worker then run flask
    start_background()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
