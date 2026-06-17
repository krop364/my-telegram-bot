
import os
import asyncio
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup

# ===== ВЕБ-СЕРВЕР ДЛЯ RENDER =====
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Бот работает!", 200

@flask_app.route('/health')
def health():
    return "OK", 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

# ===== ТЕЛЕГРАМ-БОТ =====
api_id = 35051665  # Ваш api_id
api_hash = "32f3b364d6587b554b108a0e8fb9c6db"  # Ваш api_hash
bot_token = os.environ.get("TELEGRAM_TOKEN")

app = Client("my_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

@app.on_message(filters.command("start"))
async def start(client, message):
    keyboard = ReplyKeyboardMarkup([
        ["🔘 Кто Гусь?", "🔘 Кто Олька?"],
        ["🔘 Как играем?"]
    ], resize_keyboard=True)
    
    await message.reply("Выберите:", reply_markup=keyboard)

@app.on_message(filters.text)
async def buttons(client, message):
    if message.text == "🔘 Кто Гусь?":
        await message.reply("лох вонючий")
    elif message.text == "🔘 Кто Олька?":
        await message.reply("Цариииииица")
    elif message.text == "🔘 Как играем?":
        await message.reply("Мы ахуенно играем, невероятно сильно")

# ===== ЗАПУСК ОБОИХ СЕРВЕРОВ =====
async def run_bot():
    await app.start()
    print("✅ Бот запущен!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True  # Поток завершится при выходе
    flask_thread.start()
    
    # Запускаем бота в основном потоке
    asyncio.run(run_bot())
