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

# قائمة الأزواج
SYMBOLS = {
    "BTC/USD": ("BTC", "USD"),
    "ETH/USD": ("ETH", "USD"),
    "EUR/USD": ("EUR", "USD"),
    "GBP/USD": ("GBP", "USD"),
    "USD/JPY": ("USD", "JPY"),
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


def get_price(from_symbol, to_symbol):
    """جلب السعر من Alpha Vantage"""
    try:
        url = (
            f"https://www.alphavantage.co/query?"
            f"function=CURRENCY_EXCHANGE_RATE&from_currency={from_symbol}&to_currency={to_symbol}"
            f"&apikey={ALPHA_API_KEY}"
        )
        r = requests.get(url)
        data = r.json()

        # تأكد إن المفتاح موجود قبل القراءة
        if "Realtime Currency Exchange Rate" in data:
            rate = data["Realtime Currency Exchange Rate"].get("5. Exchange Rate")
            if rate:
                return float(rate)
            else:
                print(f"⚠️ No 'Exchange Rate' value for {from_symbol}/{to_symbol}")
        else:
            print(f"⚠️ Invalid data structure for {from_symbol}/{to_symbol}: {data}")
        return None
    except Exception as e:
        print(f"❌ Error getting price for {from_symbol}/{to_symbol}: {e}")
        return None


def analyze_and_send():
    """تحليل الأسعار وإرسالها كل 5 دقائق"""
    while True:
        print("🔄 Running analysis cycle...")
        for name, (from_symbol, to_symbol) in SYMBOLS.items():
            price = get_price(from_symbol, to_symbol)
            if price:
                signal = "شراء ✅" if price % 2 == 0 else "بيع ❌"
                message = f"📊 {name}\nالسعر الحالي: {price:.2f}\nالإشارة: {signal}"
                send_telegram_message(message)
            else:
                send_telegram_message(f"⚠️ لم أستطع جلب السعر لـ {name}")

        print("✅ Cycle done. Waiting 5 minutes...\n")
        time.sleep(300)  # كل 5 دقائق


@app.route('/')
def home():
    return "Bot is running ✅"


if __name__ == '__main__':
    Thread(target=analyze_and_send, daemon=True).start()
    app.run(debug=True)
else:
    Thread(target=analyze_and_send, daemon=True).start()
