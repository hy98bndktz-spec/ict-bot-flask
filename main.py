from flask import Flask, request
import requests
import os

app = Flask(__name__)

# احصل على التوكن من متغير البيئة في Render
BOT_TOKEN = os.environ.get("BOT_TOKEN")
URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

@app.route('/')
def home():
    return "Bot is running successfully!"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        # مثال بسيط: رد تلقائي
        if text.lower() == "/start":
            send_message(chat_id, "مرحباً! 🤖 أنا بوت التداول الآلي جاهز للعمل.")
        else:
            send_message(chat_id, f"لقد أرسلت: {text}")

    return "ok", 200

def send_message(chat_id, text):
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    requests.post(URL, json=payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
