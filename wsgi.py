from flask import Flask

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Бот работает!", 200

@flask_app.route('/health')
def health():
    return "OK", 200

if __name__ == "__main__":
    flask_app.run(host='0.0.0.0', port=10000)
    