# main.py — версия без цитат: только мем + трек
import os
import time
import random
import logging
import requests
from flask import Flask, request
import telebot
from telebot import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mood-bot-funny-no-quotes")

# ========== Настройки ==========
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise SystemExit("Установи переменную окружения BOT_TOKEN")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # если репо приватное
GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "muzredmaksimov-dot")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "mir-bot-tracks")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

GITHUB_API_BASE = "https://api.github.com"
RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/"

bot = telebot.TeleBot(TOKEN, threaded=True)
app = Flask(__name__)

# ========== Шутливые кнопки и соответствие папок ==========
# key = mood id, value = (button label (funny), folder in repo)
MOODS = {
    "rave": ("🕺 Я — дискотека в теле", "happy"),
    "zen": ("🧘♂️ Я сделал утреннюю йогу с тостером", "calm"),
    "retro": ("📼 Пойду ностальгировать с кассетой", "nostalgia"),
    "turbo": ("⚡ Я зарядился кофеином и молоком", "energy"),
}

# ========== Мемы (статические, можно позже перенести в GitHub) ==========
MEMES = {
    "rave": ["https://i.imgur.com/QKp3F4S.jpeg"],
    "zen": ["https://i.imgur.com/hV6jZZD.jpeg"],
    "retro": ["https://i.imgur.com/JrVdJqV.jpeg"],
    "turbo": ["https://i.imgur.com/B4fYglz.jpeg"],
}

# ========== Кэш треков ==========
TRACKS_CACHE = {}
CACHE_TTL = 60  # seconds

# ========== Помощники GitHub ==========
def gh_headers():
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers

def fetch_tracks_for_folder(folder_name):
    """
    Возвращает список файлов {name, download_url} из tracks/<folder_name>.
    Кэширует на CACHE_TTL секунд.
    """
    now = time.time()
    cached = TRACKS_CACHE.get(folder_name)
    if cached and now - cached["ts"] < CACHE_TTL:
        return cached["tracks"]

    api_url = f"{GITHUB_API_BASE}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/tracks/{folder_name}"
    params = {"ref": GITHUB_BRANCH}
    r = requests.get(api_url, headers=gh_headers(), params=params, timeout=10)
    if r.status_code == 404:
        raise FileNotFoundError(f"Folder tracks/{folder_name} not found")
    r.raise_for_status()
    items = r.json()
    tracks = []
    for it in items:
        if it.get("type") == "file" and it.get("name", "").lower().endswith((".mp3", ".m4a", ".ogg", ".wav")):
            tracks.append({"name": it["name"], "download_url": it.get("download_url")})
    TRACKS_CACHE[folder_name] = {"ts": now, "tracks": tracks}
    return tracks

def pick_random_track(folder_name):
    tracks = fetch_tracks_for_folder(folder_name)
    if not tracks:
        return None
    return random.choice(tracks)

# ========== Клавиатура ==========
def mood_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for key, (label, folder) in MOODS.items():
        buttons.append(types.InlineKeyboardButton(label, callback_data=f"mood:{key}"))
    kb.add(*buttons)
    return kb

# ========== Хэндлеры ==========
@bot.message_handler(commands=["start"])
def cmd_start(msg):
    intro = (
        "Привет! Я — бот настроения с чувством юмора.\n"
        "Выбери настроение — и получишь:\n"
        "1) Мем дня\n2) Трек дня\n\nНажимай одну из кнопок:"
    )
    bot.send_message(msg.chat.id, intro, reply_markup=mood_keyboard())

@bot.message_handler(commands=["help"])
def cmd_help(msg):
    bot.reply_to(msg, "Нажми /start → выбери кнопку. Я пришлю мем и трек дня.")

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("mood:"))
def on_mood_selected(call: types.CallbackQuery):
    try:
        mood_key = call.data.split(":", 1)[1]
        if mood_key not in MOODS:
            bot.answer_callback_query(call.id, "Неизвестное настроение")
            return
        label, folder = MOODS[mood_key]
        bot.answer_callback_query(call.id, text=f"Вы выбрали: {label}")

        # Забавный вступительный текст
        funny_intro = random.choice([
            "Подбираю мемы и треки... держись крепче!",
            "Собираю персональный плейлист для твоего настроения.",
            "Залезаю в сундук с мемами... нашёл парочку!"
        ])
        bot.send_message(call.message.chat.id, f"🔊 {funny_intro}")

        time.sleep(0.5)

        # 1) Мем
        meme = random.choice(MEMES.get(mood_key, ["https://i.imgur.com/QKp3F4S.jpeg"]))
        try:
            bot.send_photo(call.message.chat.id, meme, caption="😂 Мем дня")
        except Exception as e:
            logger.warning("send_photo failed: %s", e)
            bot.send_message(call.message.chat.id, "😂 Мем дня (ссылка недоступна)")

        time.sleep(0.4)

        # 2) Трек — берем из GitHub
        try:
            track = pick_random_track(folder)
            if not track:
                bot.send_message(call.message.chat.id, "🎧 Трек дня: пока нет треков в этой категории.")
                return
            name = track["name"]
            url = track["download_url"] or (RAW_BASE + f"tracks/{folder}/{name}")

            track_intro = random.choice([
                "Вот трек — рекомендуем слушать в наушниках.",
                "Трек, который я бы поставил на повтор.",
                "Готовься подпевать!"
            ])
            bot.send_message(call.message.chat.id, f"🎧 *Трек дня:* *{name}*\n{url}\n\n_{track_intro}_", parse_mode="Markdown")

            # Попытка отправить аудио по прямой ссылке (если поддерживается)
            try:
                bot.send_audio(call.message.chat.id, url)
            except Exception as e:
                logger.info("send_audio skipped/fallback: %s", e)

        except FileNotFoundError:
            bot.send_message(call.message.chat.id, "🎧 Трек дня: категория треков не найдена в репозитории.")
        except requests.HTTPError:
            logger.exception("GitHub HTTP error")
            bot.send_message(call.message.chat.id, "Ошибка при получении треков с GitHub.")
        except Exception:
            logger.exception("Unexpected error while fetching track")
            bot.send_message(call.message.chat.id, "Произошла ошибка при подборе трека.")
    except Exception:
        logger.exception("Error in callback handler")
        bot.answer_callback_query(call.id, "Произошла ошибка, попробуйте снова.")

# ========== Flask webhook ==========
@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook_route():
    if request.headers.get("content-type") == "application/json":
        update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
        bot.process_new_updates([update])
        return ""
    return "Bad Request", 400

@app.route("/")
def index():
    return "Mood-bot (funny, no quotes) running"

@app.route("/health")
def health():
    return "OK"

# ========== Запуск ==========
if __name__ == "__main__":
    logger.info("Starting bot (no quotes)")
    if "RENDER" in os.environ:
        PORT = int(os.environ.get("PORT", 8080))
        try:
            bot.remove_webhook()
            time.sleep(0.5)
            # Замените YOUR-RENDER-URL на реальный URL вашего сервиса на Render
            bot.set_webhook(url=f"https://YOUR-RENDER-URL.onrender.com/webhook/{TOKEN}")
            logger.info("Webhook установлен")
        except Exception as e:
            logger.exception("Ошибка установки webhook: %s", e)
        app.run(host="0.0.0.0", port=PORT)
    else:
        bot.remove_webhook()
        bot.polling(none_stop=True)
