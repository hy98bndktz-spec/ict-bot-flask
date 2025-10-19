# main.py
import os
import time
import requests
from flask import Flask
from threading import Thread

app = Flask(__name__)

# بيانات التلقرام
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"

# مفتاح Alpha Vantage
ALPHA_API_KEY = "f82dced376934dc0ab99e79afd3ca844"

# قائمة الأزواج (بأكواد صحيحة)
SYMBOLS = {
    "Bitcoin (BTC/USD)": ("BTC", "USD"),
    "Ethereum (ETH/USD)": ("ETH", "USD"),
    "Euro (EUR/USD)": ("EUR", "USD"),
    "Pound (GBP/USD)": ("GBP", "USD"),
    "Dollar/Yen (USD/JPY)": ("USD", "JPY"),
    "Gold (XAU/USD)": ("XAU", "USD")
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


def get_price(base, quote):
    """جلب السعر من Alpha Vantage"""
    try:
        url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={base}&to_currency={quote}&apikey={ALPHA_API_KEY}"
        r = requests.get(url)
        data = r.json()

        print(f"📡 Response for {base}/{quote}: {data}")

        info = data.get("Realtime Currency Exchange Rate")
        if info and "5. Exchange Rate" in info:
            return float(info["5. Exchange Rate"])
        else:
            print(f"⚠️ Unexpected data for {base}/{quote}")
            return None
    except Exception as e:
        print(f"⚠️ Error getting price for {base}/{quote}: {e}")
        return None


def analyze_and_send():
    """تحليل الأسعار وإرسالها كل 5 دقائق"""
    while True:
        print("🔄 Running analysis cycle...")

        for name, (base, quote) in SYMBOLS.items():
            price = get_price(base, quote)
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


# التشغيل المحلي / على Render
if __name__ == '__main__':
    Thread(target=analyze_and_send, daemon=True).start()
    app.run(debug=True)
else:
    Thread(target=analyze_and_send, daemon=True).start()
