from flask import Flask
import threading
import asyncio
import os

# Импортируем и запускаем бота в отдельном потоке
def start_bot():
    # Импорт должен быть внутри функции, чтобы не блокировать импорт wsgi
    import bot
    asyncio.run(bot.run_bot())

# Запускаем бота в фоновом потоке
bot_thread = threading.Thread(target=start_bot)
bot_thread.daemon = True
bot_thread.start()

# Создаем Flask-приложение для Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает!", 200

@app.route('/health')
def health():
    return "OK", 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))