import os
import requests
import logging
import threading
import asyncio
from datetime import datetime
from flask import Flask
from telegram import Bot
from telegram.ext import Application, CommandHandler

# ======================
# إعداد Flask لإبقاء السيرفر شغال في Render
# ======================
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ ICT Bot Flask server is running!"

# ======================
# إعداد البوت
# ======================
BOT_TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"
SYMBOLS = ["BTC/USD", "ETH/USD", "EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]

# ======================
# إعداد السجل (logging)
# ======================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ======================
# دالة جلب السعر من API مجاني
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
# دالة التحليل البسيط
# ======================
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

# ======================
# إرسال التحليل إلى تيليجرام
# ======================
async def send_analysis():
    bot = Bot(token=BOT_TOKEN)
    for symbol in SYMBOLS:
        price = get_price(symbol)
        text = ict_analysis(symbol, price)
        await bot.send_message(chat_id=CHAT_ID, text=text)
        await asyncio.sleep(2)

# ======================
# أوامر التيليجرام
# ======================
async def start(update, context):
    await update.message.reply_text("👋 أهلاً! هذا بوت تحليل ICT. أرسل /analyze للحصول على تحليل.")

async def analyze(update, context):
    await update.message.reply_text("⏳ جاري التحليل...")
    await send_analysis()

# ======================
# تشغيل البوت في خيط منفصل
# ======================
def run_telegram_bot():
    async def main():
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=CHAT_ID, text="✅ البوت اشتغل الآن من Render!")

        app_telegram = Application.builder().token(BOT_TOKEN).build()
        app_telegram.add_handler(CommandHandler("start", start))
        app_telegram.add_handler(CommandHandler("analyze", analyze))

        asyncio.create_task(periodic_task())
        await app_telegram.run_polling()

    asyncio.run(main())

# ======================
# تكرار كل 5 دقائق
# ======================
async def periodic_task():
    while True:
        await send_analysis()
        await asyncio.sleep(300)

# ======================
# التشغيل الرئيسي
# ======================
if __name__ == "__main__":
    threading.Thread(target=run_telegram_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
