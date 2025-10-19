import os
import time
import logging
import threading
import requests
from flask import Flask

# إعداد اللوجز
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# إعداد Flask
app = Flask(__name__)

# توكن بوت تيليجرام
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")  # تأكد إنك ضايفه في Render Environment
CHAT_ID = os.getenv("CHAT_ID")  # أيضاً ضيف الـ chat id لو تبغاه ثابت

# رابط API (مثل Alpha Vantage أو أي مصدر أسعار)
API_URL = "https://www.alphavantage.co/query"
API_KEY = os.getenv("ALPHA_VANTAGE_KEY")

# دالة تجيب البيانات من Alpha Vantage
def fetch_price(symbol="BTCUSD"):
    try:
        response = requests.get(API_URL, params={
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": "BTC",
            "to_currency": "USD",
            "apikey": API_KEY
        })
        data = response.json()
        price = data["Realtime Currency Exchange Rate"]["5. Exchange Rate"]
        return price
    except Exception as e:
        logger.error(f"❌ خطأ أثناء جلب السعر: {e}")
        return None

# دالة ترسل رسالة إلى تيليجرام
def send_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message}
        requests.post(url, data=payload)
        logger.info(f"📨 تم إرسال الرسالة إلى تيليجرام: {message}")
    except Exception as e:
        logger.error(f"❌ خطأ أثناء إرسال الرسالة: {e}")

# المهمة الرئيسية
def analyze_and_send():
    while True:
        logger.info("🚀 بدء التحليل والإرسال...")
        price = fetch_price()
        if price:
            msg = f"💰 سعر BTC الحالي: {price}"
            send_message(msg)
        else:
            send_message("⚠️ تعذر جلب السعر حالياً.")
        logger.info("✅ تم إرسال التحليل، بانتظار الجولة القادمة...")
        time.sleep(300)  # كل 5 دقائق

# تشغيل المهمة في خيط منفصل
def start_background_thread():
    thread = threading.Thread(target=analyze_and_send)
    thread.daemon = True
    thread.start()
    logger.info("🔥 تشغيل خيط البوت...")

# مسار رئيسي لتأكيد عمل السيرفر
@app.route('/')
def home():
    return "✅ البوت يعمل حالياً على Render!"

if __name__ == '__main__':
    logger.info("🤖 بدء تشغيل بوت تيليجرام...")
    start_background_thread()
    app.run(host='0.0.0.0', port=10000)
