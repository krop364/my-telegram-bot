import os
import asyncio
import threading

from flask import Flask
from pyrogram import Client, filters
from openai import OpenAI


# =========================================================
# 1. FLASK ДЛЯ RENDER
# =========================================================

flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Бот работает!", 200


@flask_app.route("/health")
def health():
    return "OK", 200


def run_flask():
    port = int(os.environ.get("PORT", 10000))

    print(f"🌐 Запускаю Flask на порту {port}", flush=True)

    flask_app.run(
        host="0.0.0.0",
        port=port
    )


# =========================================================
# 2. TELEGRAM
# =========================================================

api_id = int(os.environ["API_ID"])
api_hash = os.environ["API_HASH"]
bot_token = os.environ["TELEGRAM_TOKEN"]


app = Client(
    "my_bot",
    api_id=api_id,
    api_hash=api_hash,
    bot_token=bot_token
)


# =========================================================
# 3. OPENAI
# =========================================================

openai_api_key = os.environ.get("OPENAI_API_KEY")

print(
    "🔑 OPENAI_API_KEY найден:",
    bool(openai_api_key),
    flush=True
)

if not openai_api_key:
    print(
        "❌ OPENAI_API_KEY НЕ НАЙДЕН В ENVIRONMENT VARIABLES",
        flush=True
    )


openai_client = OpenAI(
    api_key=openai_api_key
)


# =========================================================
# 4. СИСТЕМНЫЙ ПРОМПТ
# =========================================================

SYSTEM_PROMPT = """
Ты — дружелюбный AI-помощник по путешествиям.

Помогай пользователю:
- выбирать страны и направления;
- планировать поездки;
- выбирать отели;
- сравнивать варианты;
- составлять маршруты;
- отвечать на вопросы о путешествиях.

Отвечай на русском языке.

Если информации недостаточно, задавай уточняющие вопросы.
Не выдумывай факты.
"""


# =========================================================
# 5. ЗАПРОС К OPENAI
# =========================================================

def ask_gpt(user_message):

    print("========== OPENAI TEST ==========", flush=True)

    print(
        "Получен текст:",
        user_message,
        flush=True
    )

    print(
        "Отправляю запрос в OpenAI...",
        flush=True
    )

    try:

        response = openai_client.responses.create(
            model="gpt-4.1-mini",
            instructions=SYSTEM_PROMPT,
            input=user_message
        )

        print(
            "✅ OPENAI УСПЕШНО ОТВЕТИЛ!",
            flush=True
        )

        print(
            "Ответ:",
            response.output_text,
            flush=True
        )

        return response.output_text

    except Exception as e:

        print(
            "❌❌❌ ОШИБКА OPENAI ❌❌❌",
            flush=True
        )

        print(
            "Тип:",
            type(e).__name__,
            flush=True
        )

        print(
            "Ошибка:",
            str(e),
            flush=True
        )

        print(
            "repr:",
            repr(e),
            flush=True
        )

        raise


# =========================================================
# 6. /START
# =========================================================

@app.on_message(filters.command("start"))
async def start(client, message):

    await message.reply(
        "👋 Привет!\n\n"
        "Я AI-помощник по путешествиям.\n"
        "Напиши мне, куда хочешь поехать или задай любой вопрос."
    )


# =========================================================
# 7. ВСЕ ТЕКСТОВЫЕ СООБЩЕНИЯ → OPENAI
# =========================================================

@app.on_message(filters.text & ~filters.command("start"))
async def chat_with_gpt(client, message):

    print("================================", flush=True)
    print("📩 TELEGRAM MESSAGE RECEIVED", flush=True)
    print("👤 User ID:", message.from_user.id, flush=True)
    print("💬 Text:", message.text, flush=True)
    print("================================", flush=True)

    await message.reply(
        "✅ Telegram получил сообщение!\n\n"
        "Сейчас проверяем подключение к AI."
    )


# =========================================================
# 8. ЗАПУСК
# =========================================================

if __name__ == "__main__":

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    print(
        "🚀 Запускаю Telegram-бота...",
        flush=True
    )

    app.run()
