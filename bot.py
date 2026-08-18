import os
import threading

from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup

from openai import OpenAI


# ==========================================
# НАСТРОЙКИ
# ==========================================

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]


# ==========================================
# FLASK — веб-сервер для Render
# ==========================================

flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Telegram bot is running!", 200


@flask_app.route("/health")
def health():
    return "OK", 200


def run_flask():
    port = int(os.environ.get("PORT", 10000))

    print(f"🌐 Запускаю Flask на порту {port}")

    flask_app.run(
        host="0.0.0.0",
        port=port
    )


# ==========================================
# OPENAI
# ==========================================

openai_client = OpenAI(
    api_key=OPENAI_API_KEY
)


SYSTEM_PROMPT = """
Ты — умный помощник по путешествиям.

Ты помогаешь пользователю:
- выбирать страны и города;
- выбирать направление для отдыха;
- планировать путешествия;
- выбирать отели.

Общайся дружелюбно и естественно.

Если пользователю сложно определиться,
задавай уточняющие вопросы.

Если пользователь хочет подобрать отель,
уточни:
- город или страну;
- даты;
- количество людей;
- бюджет;
- пожелания к отелю.

Не придумывай актуальные цены, наличие номеров
или другие данные, которых у тебя нет.

Отвечай на русском языке.
"""


# ==========================================
# TELEGRAM
# ==========================================

app = Client(
    "my_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=TELEGRAM_TOKEN
)


# ==========================================
# /start
# ==========================================

@app.on_message(filters.command("start"))
async def start(client, message):

    keyboard = ReplyKeyboardMarkup(
        [
            [
                "🌍 Помоги выбрать направление",
                "🏨 Помоги выбрать отель"
            ]
        ],
        resize_keyboard=True
    )

    await message.reply(
        "👋 Привет!\n\n"
        "Я твой помощник по путешествиям.\n\n"
        "Могу помочь выбрать направление "
        "или подобрать отель.",
        reply_markup=keyboard
    )


# ==========================================
# OPENAI
# ==========================================

async def ask_gpt(user_message):

    response = openai_client.responses.create(
        model="gpt-4.1-mini",
        instructions=SYSTEM_PROMPT,
        input=user_message
    )

    return response.output_text


# ==========================================
# КНОПКА "НАПРАВЛЕНИЕ"
# ==========================================

@app.on_message(
    filters.regex("^🌍 Помоги выбрать направление$")
)
async def choose_destination(client, message):

    await message.reply(
        "🌍 Давай подберём направление!\n\n"
        "Напиши, например:\n"
        "«Хочу море, тепло и недорого»\n\n"
        "или просто расскажи, какой отдых тебе нравится."
    )


# ==========================================
# КНОПКА "ОТЕЛЬ"
# ==========================================

@app.on_message(
    filters.regex("^🏨 Помоги выбрать отель$")
)
async def choose_hotel(client, message):

    await message.reply(
        "🏨 Конечно!\n\n"
        "Напиши город или страну, "
        "даты поездки, количество людей "
        "и примерный бюджет."
    )


# ==========================================
# ВСЕ ОСТАЛЬНЫЕ ТЕКСТОВЫЕ СООБЩЕНИЯ → GPT
# ==========================================

@app.on_message(filters.text)
async def chat_with_gpt(client, message):

    if message.text.startswith("/start"):
        return

    # Не отправляем сами названия кнопок повторно в GPT
    if message.text in [
        "🌍 Помоги выбрать направление",
        "🏨 Помоги выбрать отель"
    ]:
        return

    try:

        await message.reply_chat_action("typing")

        answer = await ask_gpt(message.text)

        await message.reply(answer)

    except Exception as e:

    print("❌❌❌ ОШИБКА OPENAI ❌❌❌")
    print(type(e).__name__)
    print(str(e))
    print(repr(e))

        await message.reply(
            "😔 Произошла ошибка при обращении к AI.\n"
            "Попробуй ещё раз."
        )


# ==========================================
# ЗАПУСК
# ==========================================

if __name__ == "__main__":

    # Flask запускаем в отдельном потоке
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    print("🚀 Запускаю Telegram-бота...")

    app.run()
