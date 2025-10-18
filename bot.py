import logging
import time
import requests
import pandas as pd
import matplotlib.pyplot as plt
import io
import yfinance as yf
from telegram import Bot
from telegram.ext import Updater, CommandHandler, JobQueue

# إعداد التوكن ومعرّف الشات
TELEGRAM_TOKEN = "ضع_هنا_التوكن"
CHAT_ID = "ضع_هنا_ID_الشات"

# إعداد التسجيل (logs)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# دالة لجلب بيانات السوق وتحليلها
def get_market_analysis():
    ticker = "BTC-USD"
    data = yf.download(ticker, period="1d", interval="5m")

    if data.empty:
        return None, "❌ لم يتم جلب البيانات."

    data["RSI"] = compute_rsi(data["Close"])
    current_price = data["Close"].iloc[-1]
    rsi_value = data["RSI"].iloc[-1]

    if rsi_value < 30:
        signal = "🟢 إشارة شراء (RSI منخفض)"
    elif rsi_value > 70:
        signal = "🔴 إشارة بيع (RSI مرتفع)"
    else:
        signal = "⚪ لا توجد إشارة واضحة"

    # رسم بياني
    fig, ax = plt.subplots()
    ax.plot(data.index, data["Close"], label="السعر")
    ax.set_title(f"{ticker} السعر الحالي: {current_price:.2f} - RSI: {rsi_value:.2f}")
    ax.legend()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close(fig)

    text = f"📊 *تحليل السوق*\n\nالسعر الحالي: ${current_price:.2f}\nRSI: {rsi_value:.2f}\n\nالإشارة: {signal}"

    return buf, text


# دالة لحساب RSI
def compute_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


# دالة لإرسال التحليل إلى التلغرام
def send_market_update(context):
    bot = context.bot
    buf, text = get_market_analysis()
    if buf is None:
        bot.send_message(chat_id=CHAT_ID, text=text)
    else:
        bot.send_photo(chat_id=CHAT_ID, photo=buf, caption=text, parse_mode="Markdown")


# دالة البدء
def start(update, context):
    update.message.reply_text("🤖 البوت يعمل الآن ويرسل التحديثات كل 5 دقائق!")


def main():
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))

    job_queue = updater.job_queue
    job_queue.run_repeating(send_market_update, interval=300, first=10)

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
