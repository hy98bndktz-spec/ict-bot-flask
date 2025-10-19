import os
import requests
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import asyncio

# إعداد السجل (logs)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# جلب رمز البوت من البيئة
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# أزواج العملات
PAIRS = ["BTC/USD", "ETH/USD", "EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]

# ✅ دالة جلب السعر من open.er-api.com
def get_price(symbol):
    try:
        base, quote = symbol.split("/")
        url = f"https://open.er-api.com/v6/latest/{base}"
        response = requests.get(url)
        data = response.json()
        return data["rates"].get(quote)
    except Exception as e:
        logger.error(f"❌ خطأ في جلب السعر لـ {symbol}: {e}")
        return None

# ✅ دالة تحليل بسيطة
def analyze_symbol(symbol):
    price = get_price(symbol)
    if price is None:
        return f"⚠️ لم أستطع جلب السعر لـ {symbol}"
    
    if price > 1:
        trend = "📈 صاعد"
        advice = "🟩 شراء"
    else:
        trend = "📉 هابط"
        advice = "🟥 بيع"
    
    return f"🔹 {symbol}\n💰 السعر الحالي: {price:.4f}\n📊 الاتجاه: {trend}\n🎯 التوصية: {advice}"

# ✅ أمر /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 أهلاً بك! أرسل /analyze لتحليل الأزواج.")

# ✅ أمر /analyze
async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ جاري تحليل الأسواق...")
    results = [analyze_symbol(pair) for pair in PAIRS]
    message = "\n\n".join(results)
    await update.message.reply_text(message)

# ✅ بدء التشغيل
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analyze", analyze))

    logger.info("🚀 البوت يعمل بنجاح على Render!")
    app.run_polling()
