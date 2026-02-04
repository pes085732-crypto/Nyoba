import asyncio
import uuid
import os
import aiosqlite
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeDefault, FSInputFile, CallbackQuery, ChatPermissions
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= KONFIG AMAN =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CH1_USERNAME = os.getenv("CH1_USERNAME")
CH2_USERNAME = os.getenv("CH2_USERNAME")
GROUP_USERNAME = os.getenv("GROUP_USERNAME")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else 0
BOT_USERNAME = os.getenv("BOT_USERNAME")
EXEMPT_USERNAME = os.getenv("EXEMPT_USERNAME")

# PENGAMAN LOG_GROUP_ID
raw_log_id = os.getenv("LOG_GROUP_ID", "").replace("@", "")
if raw_log_id.replace("-", "").isdigit():
    LOG_GROUP_ID = int(os.getenv("LOG_GROUP_ID"))
else:
    LOG_GROUP_ID = ADMIN_ID

KATA_KOTOR = ["biyo", "promosi", "bio", "byoh", "biyoh"]

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "media.db")

class PostDonasi(StatesGroup):
    waiting_for_title = State()
    waiting_for_photo = State()

# ================= DATABASE & INIT =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.commit()

async def auto_backup_db():
    if os.path.exists(DB_NAME):
        file_db = FSInputFile(DB_NAME, filename=f"backup_{datetime.now().strftime('%Y%m%d')}.db")
        try:
            await bot.send_document(ADMIN_ID, file_db, caption="🔄 **AUTO BACKUP DB**")
        except: pass

# ================= HELPER FUNCTIONS =================
async def check_membership(user_id: int):
    results = []
    for chat in [CH1_USERNAME, CH2_USERNAME, GROUP_USERNAME]:
        if not chat: continue
        target = chat if chat.startswith("@") else f"@{chat}"
        try:
            m = await bot.get_chat_member(target, user_id)
            results.append(m.status in ("member", "administrator", "creator"))
        except:
            results.append(False)
    return results

def join_keyboard(code: str, status: list):
    buttons = []
    names = ["📢 JOIN CHANNEL 1", "📢 JOIN CHANNEL 2", "👥 JOIN GRUP"]
    links = [CH1_USERNAME, CH2_USERNAME, GROUP_USERNAME]
    for i in range(len(status)):
        if not status[i] and links[i]:
            clean_link = links[i].replace("@", "")
            buttons.append([InlineKeyboardButton(text=names[i], url=f"https://t.me/{clean_link}")])
    buttons.append([InlineKeyboardButton(text="🔄 UPDATE / COBA LAGI", callback_data=f"retry:{code}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def send_media(chat_id: int, user_id: int, code: str):
    status = await check_membership(user_id)
    if not all(status):
        await bot.send_message(chat_id, "🚫 Kamu harus join semua channel/grup di bawah ini dulu!", reply_markup=join_keyboard(code, status))
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (code,)) as cur:
            row = await cur.fetchone()
    
    if row:
        if row[1] == "photo":
            await bot.send_photo(chat_id, row[0], caption=row[2], protect_content=True)
        else:
            await bot.send_video(chat_id, row[0], caption=row[2], protect_content=True)
    else:
        await bot.send_message(chat_id, "❌ Link salah atau media sudah dihapus.")

# ================= HANDLERS =================

@dp.callback_query(F.data.startswith("retry:"))
async def retry_callback(callback: CallbackQuery):
    code = callback.data.split(":")[1]
    await callback.message.delete()
    await send_media(callback.message.chat.id, callback.from_user.id, code)

@dp.message(Command("id"))
async def get_id(message: Message):
    await message.reply(f"🆔 Chat ID: `{message.chat.id}`\n👤 User ID: `{message.from_user.id}`", parse_mode="Markdown")

@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def filter_kata_grup(message: Message):
    curr_usn = message.from_user.username
    if message.from_user.id == ADMIN_ID or (curr_usn and curr_usn.lower() == EXEMPT_USERNAME.lower()):
        return
    if any(k in message.text.lower() for k in KATA_KOTOR):
        try:
            await message.delete()
            until = datetime.now() + timedelta(hours=24)
            await bot.restrict_chat_member(message.chat.id, message.from_user.id, ChatPermissions(can_send_messages=False), until_date=until)
            await message.answer(f"🚫 {message.from_user.mention_html()} MUTE 24 JAM!", parse_mode="HTML")
            await bot.send_message(LOG_GROUP_ID, f"🚫 **LOG MUTE**\nUser: {message.from_user.full_name}\nKata: {message.text}")
        except: pass

@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()
    
    args = message.text.split(" ", 1)
    if len(args) == 1:
        await bot.send_message(LOG_GROUP_ID, f"👤 **USER START**\nNama: {message.from_user.full_name}\nID: `{message.from_user.id}`")
        return await message.answer("👋 Halo sayang! Kirim /donasi atau klik link media untuk melihat konten.")
    
    await send_media(message.chat.id, message.from_user.id, args[1])

@dp.message(F.chat.type == "private", (F.photo | F.video))
async def handle_donasi(message: Message):
    if message.from_user.id == ADMIN_ID: return
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ POST", callback_data=f"approve:{message.from_user.id}"),
        InlineKeyboardButton(text="❌ REJECT", callback_data="reject")
    ]])
    await bot.send_message(ADMIN_ID, f"🎁 **DONASI MASUK**\nDari: {message.from_user.full_name}", reply_markup=kb)
    await message.reply("✅ Konten donasi sudah terkirim ke admin. Makasih ya!")

@dp.callback_query(F.data == "reject")
async def rej(c: CallbackQuery):
    await c.message.delete()
    await c.answer("Konten ditolak!")

@dp.callback_query(F.data.startswith("approve"))
async def app(c: CallbackQuery, state: FSMContext):
    await state.set_state(PostDonasi.waiting_for_title)
    await c.message.answer("Sip! Sekarang kirim **JUDUL** buat postingan ini:")
    await c.answer()

@dp.message(PostDonasi.waiting_for_title)
async def set_t(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(PostDonasi.waiting_for_photo)
    await m.answer("Oke, sekarang kirim **FOTO COVER** untuk link ini:")

@dp.message(PostDonasi.waiting_for_photo, F.photo)
async def set_p(m: Message, state: FSMContext):
    data = await state.get_data()
    code = uuid.uuid4().hex[:8]
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)", (code, m.photo[-1].file_id, "photo", data['title']))
        await db.commit()
    
    link = f"https://t.me/{BOT_USERNAME}?start={code}"
    await m.answer(f"✅ **POSTINGAN SIAP**\n\nJudul: {data['title']}\nLink: `{link}`")
    await bot.send_message(LOG_GROUP_ID, f"📢 **NEW POST GENERATED**\nJudul: {data['title']}\nLink: {link}")
    await state.clear()

async def main():
    await init_db()
    scheduler.add_job(auto_backup_db, 'cron', hour=0, minute=0)
    scheduler.start()
    print("Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
