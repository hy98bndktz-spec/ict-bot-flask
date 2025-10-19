import requests

TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"

def send_test():
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": "✅ اختبار البوت - الاتصال سليم"}
    try:
        r = requests.post(url, data=payload, timeout=10)
        print("Status:", r.status_code)
        print("Response:", r.text)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    send_test()
