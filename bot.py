# bot.py
import os
import io
import threading
import requests
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from flask import Flask
import ta

# ===== config from env =====
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable")

# ===== helpers =====
def get_klines_binance(symbol="BTCUSDT", interval="5m", limit=200):
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(data, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_asset_volume","num_trades","taker_buy_base","taker_buy_quote","ignore"
        ])
        # make timezone-aware UTC index (fix tz-naive vs tz-aware errors)
        df["datetime"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df.set_index("datetime", inplace=True)
        for c in ["open","high","low","close","volume"]:
            df[c] = df[c].astype(float)
        return df[["open","high","low","close","volume"]]
    except Exception as e:
        print("Binance fetch error for", symbol, e)
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

def compute_indicators(df):
    df = df.copy()
    df["EMA20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["RSI"] = compute_rsi(df["close"], 14)
    return df

def make_chart_bytes(df, title="chart"):
    ohlc = df[["open","high","low","close"]].copy()
    s = mpf.make_mpf_style(base_mpf_style='nightclouds')
    fig, axes = mpf.plot(ohlc, type='candle', style=s, returnfig=True, figsize=(8,4), tight_layout=True)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf

def is_fresh(df, minutes=15):
    if df is None or df.empty:
        return False
    last_time = df.index[-1]
    # last_time is tz-aware (utc=True above)
    now = datetime.now(timezone.utc)
    return (now - last_time) <= timedelta(minutes=minutes)

def generate_signal(df, symbol="SYM"):
    df = compute_indicators(df)
    if df is None or df.empty:
        return {"symbol": symbol, "signal": "NO_DATA"}
    last = df.iloc[-1]
    price = float(last["close"])
    ema20 = float(last["EMA20"]) if not pd.isna(last["EMA20"]) else None
    ema50 = float(last["EMA50"]) if not pd.isna(last["EMA50"]) else None
    rsi_val = float(last["RSI"]) if not pd.isna(last["RSI"]) else None

    signal = "HOLD"; tp = None
    if ema20 is not None and ema50 is not None and rsi_val is not None:
        if ema20 > ema50 and rsi_val < 70:
            signal = "BUY"; tp = price * 1.002
        elif ema20 < ema50 and rsi_val > 30:
            signal = "SELL"; tp = price * 0.998

    return {"symbol": symbol, "price": price, "signal": signal, "tp": tp, "rsi": rsi_val, "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}

# ===== job that runs periodically =====
SYMBOLS = ["BTCUSDT","ETHUSDT","XAUUSDT","EURUSDT","GBPUSDT","USDJPY"]  # adjust as needed

async def send_analysis_job(context: ContextTypes.DEFAULT_TYPE):
    for sym in SYMBOLS:
        try:
            df = get_klines_binance(sym, interval="5m", limit=200)
            if df is None or len(df) < 30:
                print("No data for", sym)
                continue
            if not is_fresh(df):
                print("Stale data for", sym)
                continue
            sig = generate_signal(df, sym)
            if sig["signal"] in ("BUY","SELL"):
                try:
                    chart_buf = make_chart_bytes(df, title=sym)
                except Exception as e:
                    print("Chart creation error:", e)
                    chart_buf = None

                caption = (
                    f"*ICT Smart Money Signal*\n"
                    f"Asset: `{sig['symbol']}`\n"
                    f"Time: `{sig['time']}`\n"
                    f"Price: `{sig['price']:.4f}`\n"
                    f"Signal: *{sig['signal']}*\n"
                    f"RSI: `{sig['rsi']:.1f}`\n"
                )
                if sig["tp"] is not None:
                    caption += f"🎯 TP: `{sig['tp']:.4f}`\n"

                # send to a single CHAT_ID (or you can loop multiple)
                if chart_buf:
                    chart_buf.seek(0)
                    await context.bot.send_photo(chat_id=CHAT_ID, photo=chart_buf, caption=caption, parse_mode="Markdown")
                else:
                    await context.bot.send_message(chat_id=CHAT_ID, text=caption, parse_mode="Markdown")
            else:
                print(sym, "HOLD")
        except Exception as e:
            print("Error processing", sym, e)
            # send error message to chat? optional:
            try:
                await context.bot.send_message(chat_id=CHAT_ID, text=f"⚠️ Error analyzing {sym}: {e}")
            except Exception:
                pass

# ===== commands =====
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot started. I will send signals automatically.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start to start\n/help to see this message")

# ===== main: build bot, schedule job, and run Flask web server =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))

    # schedule repeating job (every 5 minutes)
    jq = app.job_queue
    jq.run_repeating(send_analysis_job, interval=300, first=10)

    # run polling in background thread (so we can also run Flask for Render)
    def run_polling():
        app.run_polling()

    t = threading.Thread(target=run_polling, daemon=True)
    t.start()
    print("Bot polling started in background thread.")

    # Flask app so Render sees a web endpoint (health)
    flask_app = Flask(__name__)

    @flask_app.route("/")
    def home():
        return "Bot is running"

    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
