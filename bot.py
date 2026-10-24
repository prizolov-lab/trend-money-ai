import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
# Публичный адрес сервиса на Railway (домен приложения), например https://имя.up.railway.app
RAILWAY_URL = os.getenv("RAILWAY_URL")
PORT = int(os.getenv("PORT", 8080))

if not TELEGRAM_TOKEN or not RAILWAY_URL:
    raise RuntimeError("Задайте переменные окружения TELEGRAM_TOKEN и RAILWAY_URL")

# Telegram imports
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# Наши модули
from openai_api import generate_startup_ideas
from robokassa import create_payment_link
from agenomics_hook import HOOK  # необязательно: AGENOMICS_EVIDENCE=1

# -------- COMMAND HANDLERS -------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Бот работает!\n\nНапиши:\n/ideas AI tools"
    )

async def ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("IDEAS COMMAND RECEIVED")
    token = HOOK.start() if HOOK else None
    failed = True
    try:
        text = " ".join(context.args) if context.args else "AI tools"
        print("USER INPUT:", text)

        ideas_list = generate_startup_ideas(text)
        print("IDEAS:", ideas_list)

        msg = "\n\n".join([f"{i+1}. {idea}" for i, idea in enumerate(ideas_list)])
        payment_link = create_payment_link(update.effective_user.id)

        markup = None
        if HOOK and token:
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("👍", callback_data=f"fb:{token[0]}:1"),
                InlineKeyboardButton("👎", callback_data=f"fb:{token[0]}:0"),
            ]])
        await update.message.reply_text(
            f"{msg}\n\n💰 Полный доступ:\n{payment_link}", reply_markup=markup
        )
        failed = False

    except Exception as e:
        print("ERROR:", e)
        await update.message.reply_text("Ошибка при генерации 😢")
    finally:
        if HOOK:
            HOOK.finish(token, failed)


async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Спасибо за оценку!")
    try:
        _, task_no, positive = query.data.split(":")
        if HOOK:
            HOOK.human(int(task_no), positive == "1")
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as e:
        print("FEEDBACK ERROR:", e)


# -------- START BOT -------- #

def start_bot():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Добавляем хендлеры
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas))
    app.add_handler(CallbackQueryHandler(feedback, pattern=r"^fb:"))

    # Настройка webhook для Railway
    webhook_url = f"{RAILWAY_URL}/webhook"
    print("Setting webhook to:", webhook_url)

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=webhook_url
    )

if __name__ == "__main__":
    start_bot()
