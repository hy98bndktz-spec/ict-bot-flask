import os
import requests
import logging
import threading
import asyncio
from datetime import datetime
from flask import Flask
from telegram import Bot
from telegram.ext import Application, CommandHandler

# إعداد Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ ICT Bot Flask server is running!"

# إعداد التوكن والـ Chat ID
BOT_TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"
SYMBOLS = ["BTC/USD", "ETH/USD", "EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]

# إعداد السجل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_price(symbol):
    try:
        base, quote = symbol.split("/")
        url = f"https://api.exchangerate.host/latest?base={base}&symbols={quote}"
        response = requests.get(url)
        data = response.json()
        return data["rates"][quote]
    except Exception as e:
        logger.error(f"❌ خطأ في جلب السعر لـ {symbol}: {e}")
        return None

def ict_analysis(symbol, price):
    if price is None:
        return f"⚠️ لم أستطع جلب السعر لـ {symbol}"
    trend = "صاعد 📈" if int(str(price).replace('.', '')[-1]) % 2 == 0 else "هابط 📉"
    bos = "تم كسر هيكل السوق" if price % 2 == 0 else "هيكل السوق مستقر"
    signal = "🟩 شراء" if "صاعد" in trend else "🟥 بيع"
    return (
        f"🔹 {symbol}\n"
        f"💰 السعر الحالي: {price:.4f}\n"
        f"📊 الاتجاه: {trend}\n"
        f"📉 {bos}\n"
        f"🎯 التوصية: {signal}\n"
        f"⏱ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )

async def send_analysis():
    logger.info("🚀
