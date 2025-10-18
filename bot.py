import os
import requests
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import ta
from datetime import datetime, timedelta
from flask import Flask

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ========== الدوال ==========

def get_klines(symbol="BTCUSDT", interval="5m", limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    data = requests.get(url).json()
    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close", "volume", "_", "__", "___", "____", "_____", "______"
    ])
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)
    return df


def analyze_market(df):
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    last_rsi = df["rsi"].iloc[-1]
    if last_rsi > 70:
        return "🔴 السوق في منطقة تشبع شرائي (احتمال هبوط)"
    elif last_rsi < 30:
        return "🟢 السوق في منطقة تشبع بيعي (احتمال صعود)"
    else:
        return "⚪ السوق متوازن حالياً"


def generate_chart(df, filename="chart.png"):
    mc = mpf.make_marketcolors(up="green", down="red", wick="black", edge="black", volume="gray")
    s = mpf.make_mpf_style(marketcolors=mc)
    mpf.plot(df, type="candle", style=s, volume=True, title="BTC/USDT (ICT Style)", savefig=filename)


async def send_analysis(context: ContextTypes.DEFAULT_TYPE):
    df = get_klines()
    analysis = analyze_market(df)
    generate_chart(df)

    await context.bot.send_photo(
        chat_id=CHAT_ID,
        photo=open("chart.png", "rb"),
        caption=f"📊 تحليل السوق وفق مدرسة مايكل ICT\n\n{analysis}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ البوت شغال ويحلل السوق كل 5 دقايق تلقائياً.")

# ========== التشغيل ==========

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    job_queue = app.job_queue
    job_queue.run_repeating(send_analysis, interval=300, first=10)

    app.run_polling()

# ========== لربط Render وتشغيل السيرفر ==========

if __name__ == "__main__":
    main()

    # الجزء اللي يخلي Render يتعرف إن البوت شغال
    flask_app = Flask(__name__)

    @flask_app.route("/")
    def home():
        return "Bot is running!"

    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)
