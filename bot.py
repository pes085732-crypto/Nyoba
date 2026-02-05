# =============================
# TELEGRAM BOT – FINAL CLEAN VERSION (FSM FIX)
# Aiogram 3.7+
# Semua fitur user request, StateFilter fix
# =============================

import os
import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import *
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.filters import StateFilter

# =============================
# ENV (Railway)
# =============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))

# =============================
# BOT INIT
# =============================
logging.basicConfig(level=logging.INFO)
bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# =============================
# DATABASE INIT
# =============================
conn = sqlite3.connect("media.db")
cur = conn.cursor()

cur.execute("DROP TABLE IF EXISTS users")
cur.execute("""
CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    joined_at TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS media (
    code TEXT PRIMARY KEY,
    file_id TEXT,
    file_type TEXT,
    created_at TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")
conn.commit()

# =============================
# DEFAULT SETTINGS
# =============================

def set_default(key, value):
    cur.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, value))
    conn.commit()

set_default("start_text", "Selamat datang 👋")
set_default("forbidden_words", "biyo,promosi,bio,biyoh")
set_default("fsub_links", "")
set_default("fsub_join_link", "")

# =============================
# HELPERS
# =============================

def is_admin(uid: int):
    return uid in ADMIN_IDS

async def check_fsub(user_id: int):
    cur.execute("SELECT value FROM settings WHERE key='fsub_links'")
    row = cur.fetchone()
    if not row or not row[0]:
        return True
    links = row[0].split("|")
    for ch in links:
        try:
            member = await bot.get_chat_member(ch, user_id)
            if member.status not in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                return False
        except:
            return False
    return True

# =============================
# START HANDLER
# =============================
@dp.message(CommandStart())
async def start(message: Message):
    uid = message.from_user.id
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at) VALUES (?,?,?,?)",
        (
            uid,
            message.from_user.username,
            message.from_user.first_name,
            datetime.now().isoformat()
        )
    )
    conn.commit()

    if not await check_fsub(uid):
        cur.execute("SELECT value FROM settings WHERE key='fsub_join_link'")
        join_link = cur.fetchone()[0]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 JOIN SEKARANG", url=join_link)] if join_link else [],
            [InlineKeyboardButton(text="🔄 COBA LAGI", callback_data="retry_fsub")]
        ])
        return await message.answer("🚫 Kamu belum join semua channel wajib", reply_markup=kb)

    cur.execute("SELECT value FROM settings WHERE key='start_text'")
    text = cur.fetchone()[0]
    await message.answer(text)

# =============================
# FSUB RETRY
# =============================
@dp.callback_query(F.data == "retry_fsub")
async def retry(call: CallbackQuery):
    if await check_fsub(call.from_user.id):
        await call.message.edit_text("✅ Akses dibuka")
    else:
        await call.answer("Masih belum join", show_alert=True)

# =============================
# FILTER KATA + MUTE
# =============================
@dp.message(F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]))
async def filter_words(message: Message):
    if message.from_user.id in ADMIN_IDS:
        return
    cur.execute("SELECT value FROM settings WHERE key='forbidden_words'")
    words = cur.fetchone()[0].split(",")
    text = (message.text or "").lower()
    if any(w in text for w in words):
        try:
            await message.delete()
            await bot.restrict_chat_member(
                message.chat.id,
                message.from_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now() + timedelta(hours=24)
            )
        except:
            pass

# =============================
# SAVE MEDIA (ADMIN)
# =============================
@dp.message(F.content_type.in_([
    ContentType.PHOTO,
    ContentType.VIDEO,
    ContentType.DOCUMENT,
    ContentType.ANIMATION
]))
async def save_media(message: Message):
    if not is_admin(message.from_user.id):
        return
    code = uuid.uuid4().hex[:8]
    file = message.photo[-1].file_id if message.photo else message.video.file_id if message.video else message.document.file_id if message.document else message.animation.file_id
    ftype = message.content_type
    cur.execute("INSERT INTO media VALUES (?,?,?,?)", (code, file, ftype, datetime.now().isoformat()))
    conn.commit()
    await message.reply(f"✅ Disimpan\nKode: <code>{code}</code>\nLink: t.me/{(await bot.me()).username}?start={code}")

# =============================
# GET MEDIA BY CODE
# =============================
@dp.message(Command("start"))
async def start_code(message: Message):
    args = message.text.split()
    if len(args) == 1:
        return
    code = args[1]
    cur.execute("SELECT file_id, file_type FROM media WHERE code=?", (code,))
    row = cur.fetchone()
    if not row:
        return await message.answer("❌ Konten tidak ditemukan")
    file_id, ftype = row
    if ftype == ContentType.PHOTO:
        await message.answer_photo(file_id)
    elif ftype == ContentType.VIDEO:
        await message.answer_video(file_id)
    elif ftype == ContentType.DOCUMENT:
        await message.answer_document(file_id)
    else:
        await message.answer_animation(file_id)

# =============================
# ADMIN PANEL INLINE
# =============================
@dp.message(Command("panel"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 FSUB + ADDLINK", callback_data="panel_fsub")],
        [InlineKeyboardButton(text="✍️ Edit Teks /start", callback_data="panel_start_text")],
        [InlineKeyboardButton(text="🚫 Kata Terlarang", callback_data="panel_words")]
    ])
    await message.answer("⚙️ <b>ADMIN PANEL</b>\nPilih pengaturan:", reply_markup=kb)

# ===== FSUB =====
@dp.callback_query(F.data == "panel_fsub")
async def panel_fsub(call: CallbackQuery, state: FSMContext):
    await state.set_state("await_fsub")
    await call.message.edit_text("Kirim username / ID channel wajib join (pisahkan dengan |)")

@dp.message(StateFilter("await_fsub"))
async def set_fsub(message: Message, state: FSMContext):
    cur.execute("UPDATE settings SET value=? WHERE key='fsub_links'", (message.text,))
    conn.commit()
    await state.clear()
    await message.answer("✅ FSUB berhasil disimpan")

# ===== START TEXT =====
@dp.callback_query(F.data == "panel_start_text")
async def panel_start_text(call: CallbackQuery, state: FSMContext):
    await state.set_state("await_start_text")
    await call.message.edit_text("Kirim teks baru untuk /start")

@dp.message(StateFilter("await_start_text"))
async def set_start_text(message: Message, state: FSMContext):
    cur.execute("UPDATE settings SET value=? WHERE key='start_text'", (message.text,))
    conn.commit()
    await state.clear()
    await message.answer("✅ Teks /start diperbarui")

# ===== FORBIDDEN WORDS =====
@dp.callback_query(F.data == "panel_words")
async def panel_words(call: CallbackQuery, state: FSMContext):
    await state.set_state("await_words")
    await call.message.edit_text("Kirim daftar kata terlarang (pisahkan koma)")

@dp.message(StateFilter("await_words"))
async def set_words(message: Message, state: FSMContext):
    cur.execute("UPDATE settings SET value=? WHERE key='forbidden_words'", (message.text,))
    conn.commit()
    await state.clear()
    await message.answer("✅ Kata terlarang diperbarui")

# =============================
# STATS
# =============================
@dp.message(Command("stats"))
async def stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM media")
    media = cur.fetchone()[0]
    await message.answer(f"👤 Users: {users}\n🎞 Media: {media}")

# =============================
# SEND DB
# =============================
@dp.message(Command("senddb"))
async def senddb(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer_document(FSInputFile("media.db"))

# =============================
# RUN
# =============================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
