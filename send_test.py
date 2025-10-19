import requests

TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
CHAT_ID = "690864747"

message = "✅ اختبار ناجح! البوت يعمل الآن على Render."

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
params = {"chat_id": CHAT_ID, "text": message}

r = requests.get(url, params=params)
print("Status:", r.status_code)
print("Response:", r.text)
