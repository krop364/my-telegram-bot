
import os
import asyncio
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove

# ===== 1. ВЕБ-СЕРВЕР =====
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Бот работает!", 200

@flask_app.route('/health')
def health():
    return "OK", 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

# ===== 2. БОТ =====
api_id = 35051665  # Ваш api_id
api_hash = "32f3b364d6587b554b108a0e8fb9c6db"  # Ваш api_hash
bot_token = os.environ.get("TELEGRAM_TOKEN")

app = Client("my_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

@app.on_message(filters.command("start"))
async def start(client, message):
    keyboard = ReplyKeyboardMarkup([
        ["🔘 Давай расскажу про разные направления!", "🔘 Давай помогу выбрать отель!"]
    ], resize_keyboard=True)
    
    await message.reply(
        "👋 **Добро пожаловать!**\n"
        "Ты запустил бота впервые? Нажми на левую кнопку, если сомневаешься куда ехать и на правую, если уже готов выбирать отель!",
        reply_markup=keyboard
    )

# Обработчик первой кнопки - показывает новые кнопки
@app.on_message(filters.text & filters.regex("🔘 Давай расскажу про разные направления!"))
async def show_destinations(client, message):
    keyboard = ReplyKeyboardMarkup([
        ["🌏 Азия хуязия", "🌍 Европа гейропа"]
    ], resize_keyboard=True)
    
    await message.reply(
        "🌍 **Куда хочешь поехать?**\nВыбери направление:",
        reply_markup=keyboard
    )

# Обработчик для Азии
@app.on_message(filters.text & filters.regex("🌏 Азия хуязия"))
async def asia_response(client, message):
    await message.reply(
        "😬 **Хуевый выбор**\n",
        reply_markup=ReplyKeyboardRemove()  # Убираем кнопки, чтобы не мешали
    )

# Обработчик для Европы
@app.on_message(filters.text & filters.regex("🌍 Европа гейропа"))
async def europe_response(client, message):
    await message.reply(
        "😏 **Может тебе еще пососать?",
        reply_markup=ReplyKeyboardRemove()  # Убираем кнопки
    )

# Обработчик второй начальной кнопки (отель)
@app.on_message(filters.text & filters.regex("🔘 Давай помогу выбрать отель!"))
async def hotel_response(client, message):
    await message.reply(
        "**ну да ну да бля нобу по тебе плачет."
    )

# Обработчик для всего остального текста (чтобы не падал)
@app.on_message(filters.text & ~filters.regex("🔘 Давай расскажу про разные направления!") & ~filters.regex("🔘 Давай помогу выбрать отель!") & ~filters.regex("🌏 Азия хуязия") & ~filters.regex("🌍 Европа гейропа"))
async def fallback(client, message):
    await message.reply(
        "❓ Я тебя не понял. Нажми /start, чтобы начать сначала."
    )

# ===== 3. ЗАПУСК (УПРОЩЕННЫЙ) =====
if __name__ == "__main__":
    # Запускаем Flask в фоновом потоке
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    print("🔄 Веб-сервер запущен.")

    # Запускаем бота
    print("🚀 Запускаю бота...")
    app.run()  # <-- Используем app.run() вместо асинхронного запуска
