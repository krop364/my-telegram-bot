import os
import asyncio
import threading

from flask import Flask
from pyrogram import Client, filters
from openai import OpenAI


# ============================================================
# НАСТРОЙКИ
# ============================================================

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


# ============================================================
# ПРОВЕРКА КЛЮЧЕЙ
# ============================================================

print("========================================")
print("🔍 ПРОВЕРКА НАСТРОЕК")
print("========================================")

print("API_ID найден:", bool(API_ID))
print("API_HASH найден:", bool(API_HASH))
print("TELEGRAM_TOKEN найден:", bool(TELEGRAM_TOKEN))
print("OPENAI_API_KEY найден:", bool(OPENAI_API_KEY))

print("========================================")


if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не найден в Environment Variables")

if not API_HASH:
    raise ValueError("❌ API_HASH не найден в Environment Variables")

if not OPENAI_API_KEY:
    raise ValueError("❌ OPENAI_API_KEY не найден в Environment Variables")


# ============================================================
# OPENAI
# ============================================================

openai_client = OpenAI(
    api_key=OPENAI_API_KEY
)


# ============================================================
# СИСТЕМНЫЙ ПРОМПТ
# ============================================================

SYSTEM_PROMPT = """
Ты — дружелюбный AI-помощник в Telegram.

Твоя задача — общаться с пользователем естественно и помогать
ему с выбором путешествий, направлений и отелей.

Отвечай на русском языке.

Стиль:
- дружелюбный
- живой
- не слишком официальный
- без длинных ненужных лекций
- отвечай непосредственно на вопрос пользователя

Если информации недостаточно — задай уточняющий вопрос.

Пока у тебя нет доступа к интернету и актуальным базам отелей,
поэтому не выдумывай актуальные цены, наличие номеров или
конкретные факты, которых ты не знаешь.
"""


# ============================================================
# FLASK
# ============================================================

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


# ============================================================
# TELEGRAM / PYROGRAM
# ============================================================

app = Client(
    "my_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=TELEGRAM_TOKEN
)


# ============================================================
# ФУНКЦИЯ ОБРАЩЕНИЯ К OPENAI
# ============================================================

def ask_gpt(user_message):

    print("🤖 Отправляю запрос в OpenAI...", flush=True)
    print(f"👤 Пользователь написал: {user_message}", flush=True)

    try:

        response = openai_client.responses.create(
            model="gpt-4.1-mini",

            input=[
                {
                    "role": "developer",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": user_message
                }
            ]
        )

        answer = response.output_text

        print("========================================")
        print("✅ OPENAI ОТВЕТИЛ")
        print("========================================")
        print(answer)
        print("========================================")

        return answer

    except Exception as e:

        print("========================================")
        print("❌❌❌ ОШИБКА OPENAI ❌❌❌")
        print("========================================")
        print("Тип ошибки:", type(e).__name__)
        print("Ошибка:", str(e))
        print("========================================")

        raise


# ============================================================
# /START
# ============================================================

@app.on_message(filters.command("start"))
async def start(client, message):

    print(
        f"🚀 Пользователь {message.from_user.id} нажал /start",
        flush=True
    )

    await message.reply(
        "👋 Привет!\n\n"
        "Я твой AI-помощник по путешествиям.\n\n"
        "Можешь просто написать мне, например:\n\n"
        "🇮🇹 Хочу поехать в Италию\n"
        "🏨 Помоги выбрать отель\n"
        "✈️ Куда поехать в сентябре?\n"
        "💰 Куда съездить недорого?\n\n"
        "Просто напиши свой вопрос."
    )


# ============================================================
# ВСЕ ТЕКСТОВЫЕ СООБЩЕНИЯ
# ============================================================

@app.on_message(filters.text & ~filters.command("start"))
async def chat_with_gpt(client, message):

    print("========================================")
    print("📩 ПОЛУЧЕНО СООБЩЕНИЕ")
    print("========================================")
    print(message.text)
    print("========================================")

    try:

        # Показываем пользователю, что бот печатает
        await message.reply_chat_action("typing")

        # OpenAI SDK синхронный,
        # поэтому запускаем его отдельно от Telegram event loop.
        answer = await asyncio.to_thread(
            ask_gpt,
            message.text
        )

        # Отправляем ответ пользователю
        await message.reply(answer)

        print("📤 Ответ отправлен пользователю", flush=True)

    except Exception as e:

        print("========================================")
        print("💥 ОШИБКА ОБРАБОТЧИКА")
        print("========================================")
        print("Тип:", type(e).__name__)
        print("Ошибка:", str(e))
        print("========================================")

        await message.reply(
            "😔 Произошла ошибка при обращении к AI.\n\n"
            "Попробуй ещё раз."
        )


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":

    print("========================================")
    print("🚀 ЗАПУСК TELEGRAM-БОТА")
    print("========================================")

    # Flask запускаем в отдельном потоке
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    print("🌐 Flask запущен", flush=True)
    print("🤖 Запускаю Telegram...", flush=True)

    # Pyrogram запускает Telegram-клиент
    app.run()

    print("🛑 Telegram-бот остановлен", flush=True)
