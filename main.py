import os
import time
import random
import requests
from io import BytesIO
from flask import Flask, request
import telebot
from telebot import types

# --- Настройки ---
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- Мемы через meme-api ---
def get_meme():
    subs = ['memes', 'funny', 'dankmemes', 'wholesomememes']
    subreddit = random.choice(subs)
    url = f'https://meme-api.com/gimme/{subreddit}'
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            return data.get('url')
    except Exception:
        pass
    return None

# --- Отправка трека как файла ---
def send_track_file(chat_id, track_url):
    try:
        res = requests.get(track_url, stream=True)
        if res.status_code == 200:
            file_like = BytesIO(res.content)
            filename = track_url.split('/')[-1]
            bot.send_document(chat_id, types.InputFile(file_like, filename))
        else:
            bot.send_message(chat_id, "Не удалось загрузить трек 😅")
    except Exception as e:
        bot.send_message(chat_id, f"Ошибка при отправке трека: {e}")

# --- Старт и кнопки настроения ---
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(
        types.KeyboardButton("😎 Чувствую себя как рок-звезда"),
        types.KeyboardButton("🥱 Лень и кофе — мои друзья"),
        types.KeyboardButton("🤡 Всё идёт по плану (но нет)"),
        types.KeyboardButton("🔥 Мир спасать не собираюсь, но попробую")
    )
    bot.send_message(message.chat.id, "Выбери своё настроение на сегодня 😏", reply_markup=markup)

# --- Обработка выбранного настроения ---
@bot.message_handler(func=lambda m: True)
def mood_handler(message):
    chat_id = message.chat.id

    # Мем дня
    meme_url = get_meme()
    if meme_url:
        bot.send_photo(chat_id, meme_url, caption="🧠 Мем дня:")

    # Трек дня (пример: из GitHub raw)
    # Замените на реальные треки из вашего репо
    track_map = {
        "😎 Чувствую себя как рок-звезда": "https://raw.githubusercontent.com/muzredmaksimov-dot/mir-bot-tracks/main/tracks/happy/track1.mp3",
        "🥱 Лень и кофе — мои друзья": "https://raw.githubusercontent.com/muzredmaksimov-dot/mir-bot-tracks/main/tracks/calm/track1.mp3",
        "🤡 Всё идёт по плану (но нет)": "https://raw.githubusercontent.com/muzredmaksimov-dot/mir-bot-tracks/main/tracks/nostalgia/track1.mp3",
        "🔥 Мир спасать не собираюсь, но попробую": "https://raw.githubusercontent.com/muzredmaksimov-dot/mir-bot-tracks/main/tracks/energy/track1.mp3",
    }
    track_url = track_map.get(message.text)
    if track_url:
        send_track_file(chat_id, track_url)
    else:
        bot.send_message(chat_id, "Выберите одно из предложенных настроений 😅")

# --- Flask webhook ---
@app.route(f'/webhook/{TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
        return ''
    return 'Bad Request', 400

@app.route('/')
def index():
    return 'Mood Music Bot running!'

@app.route('/health')
def health():
    return 'OK'

# --- Запуск ---
if __name__ == "__main__":
    print("🚀 Бот запущен!")
    if 'RENDER' in os.environ:
        port = int(os.environ.get('PORT', 8080))
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.set_webhook(url=f"https://mir-bot-tracks.onrender.com/webhook/{TOKEN}")
        except Exception as e:
            print(f"❌ Webhook error: {e}")
        app.run(host='0.0.0.0', port=port)
    else:
        bot.remove_webhook()
        bot.polling(none_stop=True)
