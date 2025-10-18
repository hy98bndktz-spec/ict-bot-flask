import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# إعداد تسجيل الأحداث (Logs)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ضع توكن البوت هنا 👇
TOKEN = "YOUR_BOT_TOKEN"

# دالة بدء التشغيل /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot is running successfully!")

# دالة اختبار /ping
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 Pong! The bot is alive.")

# الدالة الرئيسية
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # ربط الأوامر
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))

    print("🤖 Bot is running and polling for updates...")
    app.run_polling()

if __name__ == "__main__":
    main()
