import os
import io
import csv
import base64
import random
import datetime
import time
import logging

from flask import Flask, request
from telebot import TeleBot, types
from PIL import Image

try:
    from deepface import DeepFace
    HAS_DEEPFACE = True
except:
    HAS_DEEPFACE = False

try:
    from fer import FER
    HAS_FER = True
except:
    HAS_FER = False

import requests

# === Настройки ===
TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

CSV_PATH = "stats/emotions.csv"
TRACKS_BASE_PATH = "tracks"

EMOTION_MAP = {
    "happy": "happy",
    "sad": "sad",
    "angry": "angry",
    "surprise": "surprise",
    "neutral": "calm",
    "fear": "surprise",
    "disgust": "angry"
}

bot = TeleBot(TOKEN)
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/"

# === GitHub API ===
def gh_get_file(file_path):
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{file_path}?ref={GITHUB_BRANCH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()

def gh_put_file(file_path, content_bytes, message, sha=None):
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{file_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    b64 = base64.b64encode(content_bytes).decode("utf-8")
    payload = {"message": message, "content": b64, "branch": GITHUB_BRANCH}
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=headers, json=payload)
    r.raise_for_status()
    return r.json()

def append_to_csv(row):
    file_json = gh_get_file(CSV_PATH)
    if file_json:
        sha = file_json["sha"]
        text = base64.b64decode(file_json["content"]).decode("utf-8")
    else:
        sha = None
        text = "timestamp,username,emotion,track_url\n"
    buf = io.StringIO()
    buf.write(text)
    writer = csv.writer(buf)
    writer.writerow(row)
    new_bytes = buf.getvalue().encode("utf-8")
    gh_put_file(CSV_PATH, new_bytes, f"add emotion: {row[2]} @ {row[0]}", sha)

# === Эмоции ===
def analyze_emotion(image_path: str):
    if HAS_DEEPFACE:
        try:
            res = DeepFace.analyze(img_path=image_path, actions=["emotion"])
            return res.get("dominant_emotion").lower()
        except Exception as e:
            logger.warning(f"DeepFace error: {e}")
    if HAS_FER:
        import numpy as np
        img = Image.open(image_path).convert("RGB")
        detector = FER(mtcnn=True)
        try:
            label, score = detector.top_emotion(np.array(img))
            return label.lower()
        except Exception as e:
            logger.warning(f"FER error: {e}")
    return "neutral"

# === Выбор трека ===
def choose_track(mood):
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{TRACKS_BASE_PATH}/{mood}?ref={GITHUB_BRANCH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    files = r.json()
    mp3s = [f for f in files if f["type"]=="file" and f["name"].lower().endswith((".mp3",".m4a",".ogg"))]
    if not mp3s:
        return None, None
    pick = random.choice(mp3s)
    return pick["name"], f"{RAW_BASE}{TRACKS_BASE_PATH}/{mood}/{pick['name']}"

# === Хэндлеры ===
@bot.message_handler(commands=['start'])
def start_cmd(message):
    bot.reply_to(message, "Привет! Отправь своё селфи — я подберу трек под настроение 🎶")

@bot.message_handler(content_types=['photo'])
def photo_handler(message):
    bot.reply_to(message, "Анализирую твоё фото… 🧠")
    
    # Скачиваем фото
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        tmp_path = "photo.jpg"
        with open(tmp_path, "wb") as f:
            f.write(downloaded_file)
    except Exception as e:
        bot.reply_to(message, f"Ошибка при загрузке фото: {e}")
        return

    # Анализ эмоции с тайм-аутом
    try:
        emotion = analyze_emotion(tmp_path)
    except Exception as e:
        print(f"⚠️ analyze_emotion failed: {e}")
        emotion = "neutral"

    # Сопоставление с настроением
    mood = EMOTION_MAP.get(emotion, "calm")

    # Выбор трека
    try:
        name, url = choose_track(mood)
    except Exception as e:
        print(f"⚠️ choose_track failed: {e}")
        name, url = None, None

    if not url:
        bot.reply_to(message, "Не смог найти трек для твоего настроения 😞")
        return

    # Отправляем трек пользователю
    caption = f"Твоё настроение — *{mood}* ({emotion}) 🎧\nТрек дня: {name}"
    try:
        bot.send_audio(message.chat.id, url, caption=caption, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"Ошибка при отправке трека: {e}")
        return

    # Сохраняем данные в CSV на GitHub
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    row = [ts, message.from_user.username or message.from_user.id, mood, url]
    try:
        append_to_csv(row)
    except Exception as e:
        print(f"⚠️ CSV update failed: {e}")
# === Flask routes ===
@app.route(f'/webhook/{TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type')=='application/json':
        update = types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
        return ''
    return 'Bad Request',400

@app.route('/')
def index(): return 'Music Bot running!'

@app.route('/health')
def health(): return 'OK'

# === Main ===
if __name__=="__main__":
    print("🚀 Бот запускается!")
    if 'RENDER' in os.environ:
        port = int(os.environ.get('PORT', 10000))
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.set_webhook(url=f"https://mir-bot-tracks.onrender.com/webhook/{TOKEN}")
            print("✅ Вебхук установлен")
        except Exception as e:
            print(f"❌ Вебхук: {e}")
        app.run(host='0.0.0.0', port=port)
    else:
        bot.remove_webhook()
        bot.polling(none_stop=True)
