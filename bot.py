import os
import asyncio
import threading
import sqlite3

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
# ПРОВЕРКА НАСТРОЕК
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
    raise ValueError("❌ TELEGRAM_TOKEN не найден")

if not API_HASH:
    raise ValueError("❌ API_HASH не найден")

if not OPENAI_API_KEY:
    raise ValueError("❌ OPENAI_API_KEY не найден")


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
Ты — AI-помощник по путешествиям в Telegram.

Твоя задача — помогать пользователю планировать путешествия,
выбирать направления, отели и составлять планы поездок.

Общайся на русском языке.

Стиль:
- дружелюбный
- живой
- естественный
- не слишком официальный
- без ненужных длинных лекций

Учитывай контекст предыдущего разговора.

Если пользователь говорит "туда", "там", "в сентябре",
"подешевле", "этот вариант" и т.п., используй информацию
из предыдущего диалога.

Если информации недостаточно — задавай уточняющие вопросы.

Не выдумывай актуальные цены, наличие номеров или другую
информацию, которой у тебя нет.
"""


# ============================================================
# DATABASE
# ============================================================

DATABASE_PATH = "bot_memory.db"


def init_database():

    connection = sqlite3.connect(DATABASE_PATH)

    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.commit()
    connection.close()

    print("🗄️ База данных готова", flush=True)


def save_message(user_id, role, content):

    connection = sqlite3.connect(DATABASE_PATH)

    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO messages
        (user_id, role, content)
        VALUES (?, ?, ?)
        """,
        (user_id, role, content)
    )

    connection.commit()
    connection.close()


def get_history(user_id, limit=20):

    connection = sqlite3.connect(DATABASE_PATH)

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT role, content
        FROM messages
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit)
    )

    rows = cursor.fetchall()

    connection.close()

    # Мы получили сообщения от новых к старым.
    # Для OpenAI нужно наоборот.
    rows.reverse()

    history = []

    for role, content in rows:

        history.append({
            "role": role,
            "content": content
        })

    return history


def clear_history(user_id):

    connection = sqlite3.connect(DATABASE_PATH)

    cursor = connection.cursor()

    cursor.execute(
        """
        DELETE FROM messages
        WHERE user_id = ?
        """,
        (user_id,)
    )

    connection.commit()
    connection.close()

    print(
        f"🧹 История пользователя {user_id} очищена",
        flush=True
    )


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

    print(
        f"🌐 Запускаю Flask на порту {port}",
        flush=True
    )

    flask_app.run(
        host="0.0.0.0",
        port=port
    )


# ============================================================
# TELEGRAM
# ============================================================

app = Client(
    "my_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=TELEGRAM_TOKEN
)


# ============================================================
# OPENAI
# ============================================================

def ask_gpt(user_id, user_message):

    print("========================================")
    print("🤖 НАЧАЛО OPENAI ЗАПРОСА")
    print("========================================")

    print(
        "👤 Пользователь:",
        user_id,
        flush=True
    )

    print(
        "💬 Сообщение:",
        user_message,
        flush=True
    )

    # --------------------------------------------------------
    # Получаем предыдущую историю
    # --------------------------------------------------------

    history = get_history(
        user_id,
        limit=20
    )

    print(
        f"🧠 Получено сообщений из памяти: {len(history)}",
        flush=True
    )

    # --------------------------------------------------------
    # Добавляем новое сообщение пользователя
    # --------------------------------------------------------

    messages = history + [
        {
            "role": "user",
            "content": user_message
        }
    ]

    # --------------------------------------------------------
    # Запрос в OpenAI
    # --------------------------------------------------------

    print(
        "📡 Вызываю OpenAI...",
        flush=True
    )

    try:

        response = openai_client.responses.create(
            model="gpt-4.1-mini",

            input=[
                {
                    "role": "developer",
                    "content": SYSTEM_PROMPT
                }
            ] + messages
        )

        answer = response.output_text

        print("========================================")
        print("✅ OPENAI ОТВЕТИЛ")
        print("========================================")

        print(
            answer,
            flush=True
        )

        # ----------------------------------------------------
        # Сохраняем сообщение пользователя
        # ----------------------------------------------------

        save_message(
            user_id,
            "user",
            user_message
        )

        # ----------------------------------------------------
        # Сохраняем ответ AI
        # ----------------------------------------------------

        save_message(
            user_id,
            "assistant",
            answer
        )

        print(
            "💾 Диалог сохранён в базу",
            flush=True
        )

        return answer

    except Exception as e:

        print("========================================")
        print("❌ ОШИБКА OPENAI")
        print("========================================")

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

        print("========================================")

        raise


# ============================================================
# /START
# ============================================================

@app.on_message(filters.command("start"))
async def start(client, message):

    user_id = message.from_user.id

    print(
        f"🚀 Пользователь {user_id} нажал /start",
        flush=True
    )

    await message.reply(
        "👋 Привет!\n\n"
        "Я твой AI-помощник по путешествиям.\n\n"
        "Можешь просто написать:\n\n"
        "🇮🇹 Хочу в Италию\n"
        "🏨 Помоги выбрать отель\n"
        "✈️ Куда поехать в сентябре?\n"
        "💰 Куда съездить недорого?\n\n"
        "Я буду запоминать контекст нашего разговора."
    )


# ============================================================
# /CLEAR
# ============================================================

@app.on_message(filters.command("clear"))
async def clear(client, message):

    user_id = message.from_user.id

    clear_history(user_id)

    await message.reply(
        "🧹 Память очищена.\n\n"
        "Начинаем разговор с чистого листа."
    )


# ============================================================
# СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ
# ============================================================

@app.on_message(filters.text)
async def chat_with_gpt(client, message):

    # Не обрабатываем команды
    if message.text.startswith("/"):
        return

    user_id = message.from_user.id

    print("====================================")
    print(
        "📩 ПОЛУЧЕНО СООБЩЕНИЕ:",
        message.text,
        flush=True
    )
    print(
        "👤 USER ID:",
        user_id,
        flush=True
    )
    print("====================================")

    try:

        print(
            "➡️ Передаю сообщение в ask_gpt()",
            flush=True
        )

        answer = await asyncio.to_thread(
            ask_gpt,
            user_id,
            message.text
        )

        print(
            "⬅️ ask_gpt() вернул ответ",
            flush=True
        )

        await message.reply(answer)

        print(
            "📤 Ответ отправлен пользователю",
            flush=True
        )

    except Exception as e:

        print("====================================")
        print("💥 ОШИБКА ОБРАБОТЧИКА")
        print("====================================")

        print(
            "Класс:",
            type(e).__name__,
            flush=True
        )

        print(
            "Ошибка:",
            str(e),
            flush=True
        )

        print("====================================")

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

    # Создаём базу данных
    init_database()

    # Запускаем Flask
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    print(
        "🌐 Flask запущен",
        flush=True
    )

    print(
        "🤖 Запускаю Telegram...",
        flush=True
    )

    app.run()

    print(
        "🛑 Telegram-бот остановлен",
        flush=True
    )
