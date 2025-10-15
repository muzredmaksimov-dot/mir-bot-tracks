import os
import time
import threading
import datetime
import requests
import base64
import csv
import io
from PIL import Image
import numpy as np
from flask import Flask, request
import telebot
from fer import FER

# ========================
# ==== ПЕРЕМЕННЫЕ =======
# ========================
TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_OWNER = os.environ.get("GITHUB_OWNER")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Сопоставление эмоций с папками треков
EMOTION_MAP = {
    "happy": "happy",
    "sad": "sad",
    "angry": "angry",
    "neutral": "calm",
    "surprise": "happy",
    "fear": "calm",
    "disgust": "calm"
}

# ========================
# ==== ФУНКЦИИ ==========
# ========================

def analyze_emotion(image_path: str):
    result = {"emotion": "neutral"}

    def run_analysis():
        try:
            img = np.array(Image.open(image_path).convert("RGB"))
            detector = FER(mtcnn=True)
            label, score = detector.top_emotion(img)
            if label:
                result["emotion"] = label.lower()
            print(f"DEBUG: emotion detected = {result['emotion']}, score = {score}")
        except Exception as e:
            print(f"⚠️ Emotion analysis error: {e}")
            result["emotion"] = "neutral"

    t = threading.Thread(target=run_analysis)
    t.start()
    t.join(timeout=15)
    if t.is_alive():
        print("⚠️ Emotion not detected — timeout")
        return "neutral"

    return result["emotion"]

def choose_track(mood):
    """
    Берёт случайный трек из GitHub папки mood
    """
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/tracks/{mood}?ref={GITHUB_BRANCH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        raise Exception(f"Cannot fetch tracks: {resp.status_code} {resp.text}")
    data = resp.json()
    if not data:
        raise Exception("No tracks found")
    track = np.random.choice(data)
    return track["name"], track["download_url"]

def append_to_csv(row):
    csv_path = "stats/emotions.csv"
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{csv_path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    resp = requests.get(url, headers=headers, params={"ref": GITHUB_BRANCH})
    if resp.status_code == 200:
        content = base64.b64decode(resp.json()["content"]).decode("utf-8")
        sha = resp.json()["sha"]
    elif resp.status_code == 404:
        content = ""
        sha = None
    else:
        raise Exception(f"GitHub GET error: {resp.status_code} {resp.text}")

    output = io.StringIO()
    writer = csv.writer(output)
    if content.strip():
        reader = csv.reader(io.StringIO(content))
        for r in reader:
            writer.writerow(r)
    writer.writerow(row)
    csv_str = output.getvalue()

    data = {
        "message": "Update emotions.csv",
        "content": base64.b64encode(csv_str.encode("utf-8")).decode("utf-8"),
        "branch": GITHUB_BRANCH
    }
    if sha:
        data["sha"] = sha

    put_resp = requests.put(url, headers=headers, json=data)
    if put_resp.status_code not in [200, 201]:
        raise Exception(f"GitHub PUT error: {put_resp.status_code} {put_resp.text}")

# ========================
# ==== ОБРАБОТЧИК ФОТО ==
# ========================

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

    # Анализ эмоции
    emotion = analyze_emotion(tmp_path)
    mood = EMOTION_MAP.get(emotion, "calm")

    # Выбор трека
    try:
        name, url = choose_track(mood)
    except Exception as e:
        print(f"⚠️ choose_track failed: {e}")
        bot.reply_to(message, "Не смог найти трек для твоего настроения 😞")
        return

    # Отправка трека
    caption = f"Твоё настроение — *{mood}* ({emotion}) 🎧\nТрек дня: {name}"
    try:
        bot.send_audio(message.chat.id, url, caption=caption, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"Ошибка при отправке трека: {e}")
        return

    # Запись в CSV
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    row = [ts, message.from_user.username or message.from_user.id, mood, url]
    try:
        append_to_csv(row)
    except Exception as e:
        print(f"⚠️ CSV update failed: {e}")

# ========================
# ==== FLASK WEBHOOK =====
# ========================

@app.route(f'/webhook/{TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type')=='application/json':
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
        return ''
    return 'Bad Request', 400

@app.route('/')
def index(): 
    return 'Music Test Bot running!'

@app.route('/health')
def health(): 
    return 'OK'

# ========================
# ==== ЗАПУСК ===========
# ========================

if __name__=="__main__":
    print("🚀 Бот запущен!")
    if 'RENDER' in os.environ:
        port = int(os.environ.get('PORT', 10000))
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.set_webhook(url=f"https://mir-bot-tracks.onrender.com/webhook/{TOKEN}")
        except Exception as e:
            print(f"❌ Вебхук: {e}")
        app.run(host='0.0.0.0', port=port)
    else:
        bot.remove_webhook()
        bot.polling(none_stop=True)
