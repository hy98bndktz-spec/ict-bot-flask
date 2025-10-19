import os
import time
import requests
from flask import Flask
from threading import Thread

app = Flask(__name__)

# بيانات التلقرام
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"

# مفتاح Twelve Data
TWELVE_API_KEY = "5792b5e7383a420a96be7a01a3d7b9b0"

# قائمة الأزواج
SYMBOLS = {
    "BTC/USD": "BTC/USD",
    "ETH/USD": "ETH/USD",
    "EUR/USD": "EUR/USD",
    "GBP/USD": "GBP/USD",
    "USD/JPY": "USD/JPY",
    "Gold (XAU/USD)": "XAU/USD"
}


def send_telegram_message(message):
    """إرسال رسالة إلى التلقرام"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        r = requests.post(url, data=payload)
        print("📩 Telegram Response:", r.text)
    except Exception as e:
        print("❌ Telegram error:", e)


def get_price(symbol):
    """جلب السعر من Twelve Data"""
    try:
        url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={TWELVE_API_KEY}"
        r = requests.get(url)
        data = r.json()
        return float(data["price"])
    except Exception as e:
        print(f"⚠️ Error getting price for {symbol}: {e}")
        return None


def analyze_and_send():
    """تحليل الأسعار وإرسالها كل 5 دقائق"""
    # ✅ رسالة اختبار فورية عند التشغيل
    send_telegram_message("🚀 ICT Bot بدأ العمل بنجاح! سيتم إرسال أول تحليل خلال 5 دقائق.")

    while True:
        print("🔄 Running analysis cycle...")
        for name, symbol in SYMBOLS.items():
            price = get_price(symbol)
            if price:
                signal = "شراء ✅" if price % 2 == 0 else "بيع ❌"
                message = f"📊 {name}\nالسعر الحالي: {price:.2f}\nالإشارة: {signal}"
                send_telegram_message(message)
            else:
                send_telegram_message(f"⚠️ لم أستطع جلب السعر لـ {name}")
        print("✅ Cycle done. Waiting 5 minutes...\n")
        time.sleep(300)


@app.route('/')
def home():
    return "Bot is running ✅"


if __name__ == '__main__':
    Thread(target=analyze_and_send, daemon=True).start()
    app.run(host='0.0.0.0', port=10000)
