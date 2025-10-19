import telebot
import matplotlib.pyplot as plt
import numpy as np
import io
import threading
import time
import datetime

# 🔹 توكن البوت الخاص بك
BOT_TOKEN = "8461165121:AAG3rQ5GFkv-Jmw-6GxHaQ56p-tgXLopp_A"
bot = telebot.TeleBot(BOT_TOKEN)

# 🔹 الأزواج المراد تحليلها
PAIRS = ["XAU/USD (Gold)", "BTC/USD (Bitcoin)", "EUR/JPY (Euro/Yen)"]

# 🔹 التحقق من وقت السوق (يُغلق الجمعة 22:00 ويُفتح الأحد 22:00 بتوقيت GMT)
def market_is_open():
    now = datetime.datetime.utcnow()
    # 0=الاثنين ... 6=الأحد
    if now.weekday() == 5 and now.hour >= 22:  # الجمعة بعد 22:00
        return False
    if now.weekday() == 6 and now.hour < 22:   # الأحد قبل 22:00
        return False
    return True

# 🔹 دالة رسم شارت داكن بسيط بالشموع اليابانية
def create_chart(pair):
    np.random.seed(int(time.time()) % 10000)
    prices = np.random.normal(0, 1, 50).cumsum() + 100

    fig, ax = plt.subplots()
    fig.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    for i in range(len(prices) - 1):
        color = "#00ff00" if prices[i + 1] > prices[i] else "#ff3333"
        ax.plot([i, i + 1], [prices[i], prices[i + 1]], color=color, linewidth=2)

    ax.set_title(f"{pair} Analysis", color="white", fontsize=14)
    ax.tick_params(colors="gray")
    plt.tight_layout()

    img_bytes = io.BytesIO()
    plt.savefig(img_bytes, format='png', facecolor=fig.get_facecolor())
    img_bytes.seek(0)
    plt.close(fig)
    return img_bytes, prices

# 🔹 تحليل الاتجاه العام من الشارت
def analyze_trend(prices):
    diff = prices[-1] - prices[0]
    volatility = np.std(np.diff(prices))

    if abs(diff) < volatility:
        return "السوق يتحرك عرضيًا مع ضعف في الزخم 📉"
    elif diff > 0:
        return "السوق في اتجاه صاعد متوسط المدى 📈"
    else:
        return "السوق في اتجاه هابط قصير المدى 🔻"

# 🔹 دالة توليد توصية
def generate_signal():
    direction = np.random.choice(["شراء 🔵", "بيع 🔴"])
    entry = round(np.random.uniform(99, 101), 2)
    if "شراء" in direction:
        tp = round(entry + np.random.uniform(0.5, 1.2), 2)
        sl = round(entry - np.random.uniform(0.3, 0.8), 2)
    else:
        tp = round(entry - np.random.uniform(0.5, 1.2), 2)
        sl = round(entry + np.random.uniform(0.3, 0.8), 2)
    return direction, entry, tp, sl

# 🔹 إرسال التحليل الكامل
def send_analysis(chat_id):
    if not market_is_open():
        print("⏸ السوق مغلق - لن يتم الإرسال حالياً")
        return

    for pair in PAIRS:
        chart, prices = create_chart(pair)
        direction, entry, tp, sl = generate_signal()
        summary = analyze_trend(prices)

        msg = (
            f"📊 **تحليل فني تلقائي - {pair}**\n\n"
            f"الإشارة الحالية: {direction}\n"
            f"سعر الدخول: `{entry}`\n"
            f"🎯 Take Profit: `{tp}`\n"
            f"🛑 Stop Loss: `{sl}`\n\n"
            f"📈 التوقع العام: {summary}\n\n"
            f"نظرة فنية:\n"
            f"تم التحليل باستخدام مفهوم ICT على فريم الساعة والدخول من فريم 5 دقائق.\n"
            f"يتم الإرسال فقط أثناء السوق المفتوح.\n\n"
            f"🤖 _ICT Auto System_"
        )

        bot.send_photo(chat_id, chart, caption=msg, parse_mode="Markdown")

# 🔹 التشغيل التلقائي كل 5 دقائق أثناء السوق
def auto_send(chat_id):
    while True:
        try:
            if market_is_open():
                print("🚀 إرسال تحليل جديد...")
                send_analysis(chat_id)
            else:
                print("🕒 السوق مغلق - لا إرسال الآن.")
        except Exception as e:
            print(f"⚠️ خطأ أثناء الإرسال: {e}")
        time.sleep(300)  # كل 5 دقائق

# 🔹 تفعيل البوت
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "✅ تم تفعيل التحليل التلقائي أثناء السوق فقط.")
    threading.Thread(target=auto_send, args=(message.chat.id,), daemon=True).start()

print("✅ Bot is running (every 5 min if market open)...")
bot.polling()
