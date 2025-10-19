import os
import requests
import time
import logging
from telegram import Bot
from telegram.ext import Application, CommandHandler
from datetime import datetime
import asyncio
from flask import Flask

# ======================
# Flask لإبقاء السيرفر شغال في Render
# ======================
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ ICT Bot is running successfully on Render!"

# ======================
# إعداد التوكن و ID المستخدم
# ======================
BOT_TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"

# ======================
# إعداد السجل (logging)
# ======================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ======================
# أزواج العملات
# ======================
SYMBOLS = ["BTC/USD", "ETH/USD", "EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]

# ======================
# جلب السعر من TradingView (واجهة بديلة مجانية)
# ======================
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

# ======================
# تحليل السوق بأسلوب ICT (مبسط)
# ======================
def ict_analysis(symbol, price):
    try:
        if price is None:
            return f"⚠️ لم أستطع جلب السعر لـ {symbol}"
        trend = "صاعد 📈" if int(str(price).replace('.', '')[-1]) % 2 == 0 else "هابط 📉"
        signal = "🟩 شراء" if "صاعد" in trend else "🟥 بيع"
        return (
            f"🔹 {symbol}\n"
            f"💰 السعر الحالي: {price:.4f}\n"
            f"📊 الاتجاه: {trend}\n"
            f"🎯 التوصية: {signal}\n"
            f"⏱ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
    except Exception as e:
        return f"⚠️ خطأ أثناء تحليل {symbol}: {e}"

# ======================
# إرسال التحليل للتليجرام
# ======================
async def send_analysis():
    logger.info("🚀 بدأ إرسال التحليل إلى تيليجرام")
    bot = Bot(token=BOT_TOKEN)
    for symbol in SYMBOLS:
        price = get_price(symbol)
        text = ict_analysis(symbol, price)
        try:
            await bot.send_message(chat_id=CHAT_ID, text=text)
            logger.info(f"✅ تم إرسال {symbol}")
        except Exception as e:
            logger.error(f"❌ فشل إرسال {symbol}: {e}")
        await asyncio.sleep(2)
    logger.info("✅ تم إرسال جميع التحليلات")

# ======================
# أوامر التليجرام
# ======================
async def start(update, context):
    await update.message.reply_text("👋 مرحبًا! هذا بوت تحليل ICT. أرسل /analyze للحصول على تحليل فوري.")

async def analyze(update, context):
    await update.message.reply_text("⏳ جاري التحليل...")
    await send_analysis()

# ======================
# التكرار التلقائي كل 5 دقائق
# ======================
async def periodic_task():
    logger.info("🔁 بدأ التكرار التلقائي كل 5 دقائق")
    while True:
        await send_analysis()
        await asyncio.sleep(300)

# ======================
# تشغيل التطبيق
# ======================
async def main():
    logger.info("🚀 بدء تشغيل بوت تيليجرام")
    app_telegram = Application.builder().token(BOT_TOKEN).build()
    app_telegram.add_handler(CommandHandler("start", start))
    app_telegram.add_handler(CommandHandler("analyze", analyze))
    asyncio.create_task(periodic_task())
    await app_telegram.run_polling()

if __name__ == "__main__":
    import threading
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()
    asyncio.run(main())
