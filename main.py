# main.py
import os
import time
import requests
from flask import Flask
from threading import Thread

app = Flask(__name__)

# ===== إعدادات البوت =====
TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"

# ===== مفاتيح Alpha Vantage (مفاتيح متعددة للتناوب) =====
API_KEYS = [
    "f82dced376934dc0ab99e79afd3ca844",
    "5792b5e7383a420a96be7a01a3d7b9b0"
]
key_index = 0

# ===== الأزواج =====
SYMBOLS = {
    "BTC/USD": "BTCUSD",
    "ETH/USD": "ETHUSD",
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "USD/JPY": "USDJPY",
    "Gold (XAU/USD)": "XAUUSD"
}


def send_telegram_message(message):
    """إرسال رسالة إلى التلغرام"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        r = requests.post(url, data=payload)
        print("📩 Telegram Response:", r.text)
    except Exception as e:
        print("❌ Telegram error:", e)


def get_price(symbol):
    """جلب السعر من Alpha Vantage"""
    global key_index
    api_key = API_KEYS[key_index]

    try:
        url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={symbol[:3]}&to_currency={symbol[-3:]}&apikey={api_key}"
        r = requests.get(url)
        data = r.json()

        if "Realtime Currency Exchange Rate" not in data:
            # المفتاح تجاوز الحد — نبدله
            print(f"⚠️ API Key limit reached for {api_key}")
            key_index = (key_index + 1) % len(API_KEYS)
            return None

        price = float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
        return price

    except Exception as e:
        print(f"⚠️ Error getting price for {symbol}: {e}")
        return None


def analyze_and_send():
    """تحليل وإرسال الأسعار بشكل دوري"""
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


# ===== تشغيل البوت =====
if __name__ == '__main__':
    Thread(target=analyze_and_send, daemon=True).start()
    app.run(debug=True)
else:
    Thread(target=analyze_and_send, daemon=True).start()
