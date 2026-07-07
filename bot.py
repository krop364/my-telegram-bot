
import os
import asyncio
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup

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
    user_id = message.from_user.id # (здесь можно добавить проверку на нового пользователя)
    
    keyboard = ReplyKeyboardMarkup([
        ["🔘 Кто Гусь?", "🔘 Кто Олька?"],
        ["🔘 Как играем?"]
    ], resize_keyboard=True)
    
    await message.reply(
        "👋 **Добро пожаловать!**\n"
        "Ты запустил бота впервые? Нажми любую кнопку:",
        reply_markup=keyboard
    )

@app.on_message(filters.text)
async def buttons(client, message):
    if message.text == "🔘 Кто Гусь?":
        await message.reply("лох вонючий")
    elif message.text == "🔘 Кто Олька?":
        await message.reply("Цариииииица")
    elif message.text == "🔘 Как играем?":
        await message.reply("Мы ахуенно играем, невероятно сильно")

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
