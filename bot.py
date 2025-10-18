import logging
import yfinance as yf
import pandas as pd
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import asyncio
import os

# إعداد السجلّات
logging.basicConfig(level=logging.INFO)

# ===== إعدادات البوت =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A")
ADMIN_ID = int(os.getenv("ADMIN_ID", "690864747"))

# ===== جلب البيانات =====
def get_data(symbol: str, timeframe="1h", limit=200):
    try:
        df = yf.download(symbol, period="7d", interval=timeframe)
        if df.empty:
            return pd.DataFrame()
        df.dropna(inplace=True)
        return df
    except Exception as e:
        logging.error(f"Error fetching {symbol}: {e}")
        return pd.DataFrame()

# ===== تحليل الإشارات =====
def generate_signal(df: pd.DataFrame):
    try:
        df["MA50"] = df["Close"].rolling(window=50).mean()
        df["MA200"] = df["Close"].rolling(window=200).mean()

        if df["MA50"].iloc[-1] > df["MA200"].iloc[-1]:
            return "🟢 Buy Signal (Golden Cross)"
        elif df["MA50"].iloc[-1] < df["MA200"].iloc[-1]:
            return "🔴 Sell Signal (Death Cross)"
        else:
            return "⚪ Neutral (No clear signal)"
    except Exception as e:
        return f"⚠️ Error analyzing: {e}"

# ===== أوامر البوت =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 ICT Smart Money Bot started (1H/5M Strategy)\nUse /analyze to check signals.")

async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Analyzing markets, please wait...")

    symbols = ["XAUUSD=X", "BTC-USD", "EURUSD=X"]
    timeframes = {"1h": "1 Hour", "5m": "5 Minutes"}

    for symbol in symbols:
        for tf, label in timeframes.items():
            df = get_data(symbol, timeframe=tf)
            if df.empty:
                await update.message.reply_text(f"⚠️ No data for {symbol} ({label})")
                continue

            result = generate_signal(df)
            await update.message.reply_text(f"{symbol} ({label}): {result}")

# ===== دالة التشغيل =====
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analyze", analyze))
    app.run_polling()

if __name__ == "__main__":
    main()
