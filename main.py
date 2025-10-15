import os
import io
import csv
import base64
import random
import datetime
import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiohttp import web, ClientSession, ClientResponseError
from PIL import Image

try:
    from deepface import DeepFace
    HAS_DEEPFACE = True
except Exception:
    HAS_DEEPFACE = False
try:
    from fer import FER
    HAS_FER = True
except Exception:
    HAS_FER = False

BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/"

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

# --- GitHub API ---
async def gh_api(session, method, path, **kwargs):
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    async with session.request(method, url, headers=headers, **kwargs) as resp:
        if resp.status >= 400:
            text = await resp.text()
            logger.error(f"GitHub API error {resp.status}: {text}")
            raise ClientResponseError(resp.request_info, resp.history, status=resp.status)
        return await resp.json()

async def gh_get_file(session, file_path):
    return await gh_api(session, "GET", f"/contents/{file_path}?ref={GITHUB_BRANCH}")

async def gh_put_file(session, file_path, content_bytes, message, sha=None):
    b64 = base64.b64encode(content_bytes).decode("utf-8")
    payload = {"message": message, "content": b64, "branch": GITHUB_BRANCH}
    if sha:
        payload["sha"] = sha
    return await gh_api(session, "PUT", f"/contents/{file_path}", json=payload)

# --- Эмоции ---
async def analyze_emotion(image_path: str):
    if HAS_DEEPFACE:
        def run_deepface():
            res = DeepFace.analyze(img_path=image_path, actions=["emotion"])
            return res.get("dominant_emotion")
        try:
            label = await asyncio.to_thread(run_deepface)
            if label:
                return label.lower()
        except Exception as e:
            logger.warning(f"DeepFace error: {e}")
    if HAS_FER:
        from numpy import array
        img = Image.open(image_path).convert("RGB")
        detector = FER(mtcnn=True)
        try:
            label, score = detector.top_emotion(array(img))
            return label.lower()
        except Exception as e:
            logger.warning(f"FER error: {e}")
    return "neutral"

# --- CSV обновление ---
async def append_to_csv(session, row):
    try:
        file_json = await gh_get_file(session, CSV_PATH)
        sha = file_json["sha"]
        text = base64.b64decode(file_json["content"]).decode("utf-8")
    except ClientResponseError as e:
        if e.status == 404:
            text = "timestamp,username,emotion,track_url\n"
            sha = None
        else:
            raise
    buf = io.StringIO()
    buf.write(text)
    writer = csv.writer(buf)
    writer.writerow(row)
    new_bytes = buf.getvalue().encode("utf-8")
    msg = f"add emotion: {row[2]} @ {row[0]}"
    return await gh_put_file(session, CSV_PATH, new_bytes, msg, sha)

# --- Выбор трека ---
async def choose_track(session, mood):
    try:
        files = await gh_api(session, "GET", f"/contents/{TRACKS_BASE_PATH}/{mood}?ref={GITHUB_BRANCH}")
        mp3s = [f for f in files if f["type"] == "file" and f["name"].lower().endswith((".mp3", ".m4a", ".ogg"))]
        if not mp3s:
            return None, None
        pick = random.choice(mp3s)
        return pick["name"], f"{RAW_BASE}{TRACKS_BASE_PATH}/{mood}/{pick['name']}"
    except Exception as e:
        logger.warning(f"choose_track error: {e}")
        return None, None

@dp.message(CommandStart())
async def start_cmd(m: types.Message):
    await m.answer("Привет! Отправь своё селфи — я подберу трек под настроение 🎶")

@dp.message(lambda m: m.photo)
async def photo_handler(m: types.Message):
    await m.answer("Анализирую твоё фото… 🧠")
    photo = m.photo[-1]
    file = await bot.get_file(photo.file_id)
    bio = io.BytesIO()
    await bot.download_file(file.file_path, bio)
    tmp = "photo.jpg"
    with open(tmp, "wb") as f:
        f.write(bio.getbuffer())

    emotion = await analyze_emotion(tmp)
    mood = EMOTION_MAP.get(emotion, "calm")

    async with ClientSession() as s:
        name, url = await choose_track(s, mood)
        if not url:
            await m.answer("Не смог найти трек 😞")
            return
        caption = f"Твоё настроение — *{mood}* ({emotion}) 🎧\nТрек дня: {name}"
        await bot.send_audio(m.chat.id, url, caption=caption, parse_mode="Markdown")

        ts = datetime.datetime.utcnow().isoformat() + "Z"
        row = [ts, m.from_user.username or m.from_user.id, mood, url]
        try:
            await append_to_csv(s, row)
        except Exception:
            logger.warning("CSV update failed")

# --- aiohttp webhook server ---
async def handle_webhook(request):
    body = await request.text()
    update = types.Update.model_validate_json(body)
    await dp.feed_update(bot, update)
    return web.Response()

async def on_startup(app):
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app):
    await bot.session.close()

def main():
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()

