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

# قائمة الأزواج
SYMBOLS = {
    "BTC/USD": "BTCUSD",
    "ETH/USD": "ETHUSD",
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "USD/JPY": "USDJPY",
    "Gold (XAU/USD)": "XAUUSD"
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
    """جلب السعر من Alpha Vantage مع طباعة الرد للتصحيح"""
    try:
        url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={symbol[:3]}&to_currency={symbol[-3:]}&apikey={ALPHA_API_KEY}"
        r = requests.get(url)
        data = r.json()

        # طباعة الرد من الموقع داخل Render logs
        print(f"📡 Response for {symbol}: {data}")

        if "Realtime Currency Exchange Rate" in data:
            price = float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
            return price
        else:
            print(f"⚠️ Unexpected response for {symbol}: {data}")
            return None
    except Exception as e:
        print(f"⚠️ Error getting price for {symbol}: {e}")
        return None


def analyze_and_send():
    """تحليل الأسعار وإرسالها كل 5 دقائق"""
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
        time.sleep(300)  # كل 5 دقائق


@app.route('/')
def home():
    return "Bot is running ✅"


# للتشغيل في Render
if __name__ == '__main__':
    # للتشغيل المحلي فقط
    Thread(target=analyze_and_send, daemon=True).start()
    app.run(debug=True)
else:
    # للتشغيل على Render
    Thread(target=analyze_and_send, daemon=True).start()
