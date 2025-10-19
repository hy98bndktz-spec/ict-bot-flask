from flask import Flask
import requests

app = Flask(__name__)

# ضع هنا التوكن حق بوتك
TOKEN = "5792b5e7383a420a96be7a01a3d7b9b0"
CHAT_ID = "ضع هنا الايدي الخاص بك"  # اكتبه مثل 123456789

@app.route('/')
def home():
    message = "✅ البوت شغال بنجاح على Render!"
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload)
        return "تم إرسال الرسالة بنجاح ✅"
    except Exception as e:
        return f"حدث خطأ أثناء الإرسال: {e}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
