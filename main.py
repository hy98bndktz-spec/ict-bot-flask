import os
import time
import threading
import requests
from flask import Flask

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_message(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": msg}
        response = requests.post(url, data=data)
        print("✅ Response:", response.text)
    except Exception as e:
        print("❌ Error sending message:", e)

def background_task():
    while True:
        send_message("🚀 البوت شغال بنجاح على Render!")
        print("📨 تم إرسال الرسالة التجريبية.")
        time.sleep(300)  # كل 5 دقايق

@app.route('/')
def home():
    return "✅ Test bot is running on Render!"

if __name__ == '__main__':
    t = threading.Thread(target=background_task)
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=10000)
