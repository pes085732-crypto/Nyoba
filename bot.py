import asyncio
import uuid
import os
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeDefault
from aiogram.filters import CommandStart, Command
from aiogram.exceptions import TelegramBadRequest

# ================= KONFIG AMAN =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CH1_USERNAME = os.getenv("CH1_USERNAME")
CH2_USERNAME = os.getenv("CH2_USERNAME")
GROUP_USERNAME = os.getenv("GROUP_USERNAME")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else 0
BOT_USERNAME = os.getenv("BOT_USERNAME")

KATA_KOTOR = ["open bo", "promosi", "bio", "slot gacor", "vcs"]

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "media.db")

# ================= DATABASE & MENU INIT =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.commit()

async def set_commands():
    # Iki ben metu garis miring (/) neng pojok chat member
    commands = [
        BotCommand(command="start", description="Mulai Bot"),
        BotCommand(command="ask", description="Tanya Admin (Sambat)"),
        BotCommand(command="donasi", description="Kirim Konten/Donasi")
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())

# ================= HELPER =================
async def check_membership(user_id: int):
    results = []
    for chat in [CH1_USERNAME, CH2_USERNAME, GROUP_USERNAME]:
        try:
            m = await bot.get_chat_member(chat, user_id)
            results.append(m.status in ("member", "administrator", "creator"))
        except Exception:
            results.append(False)
    return results

def join_keyboard(code: str, status: list):
    buttons = []
    names = ["📢 JOIN CHANNEL 1", "📢 JOIN CHANNEL 2", "👥 JOIN GRUP"]
    links = [CH1_USERNAME, CH2_USERNAME, GROUP_USERNAME]
    for i in range(3):
        if not status[i]:
            buttons.append([InlineKeyboardButton(text=names[i], url=f"https://t.me/{links[i][1:]}")])
    buttons.append([InlineKeyboardButton(text="🔄 UPDATE / COBA LAGI", callback_data=f"retry:{code}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ================= NEW FEATURES (/ASK & /DONASI) =================

@dp.message(Command("ask"))
async def ask_handler(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.reply("⚠️ Cara menggunakan: `/ask pesan` \nConto: `/ask min link mati`")
    
    pesan_user = args[1]
    user_info = f"👤 Soko: {message.from_user.full_name}\n🆔 ID: `{message.from_user.id}`"
    
    # Kirim neng Admin
    await bot.send_message(ADMIN_ID, f"📩 **PESAN ANYAR (ASK)**\n{user_info}\n\n💬 Pesan: {pesan_user}")
    await message.reply("✅ Pesanmu udah dikirim ke admin, silahkan tunggu balasan.")

@dp.message(Command("donasi"))
async def donasi_start(message: Message):
    await message.answer("🙏 maaciw donasinya.\n\n**Silahkan kirim video/foto serta caption.**\nOtomatis akan diteruskan ke Admin.")

@dp.message(F.chat.type == "private", (F.photo | F.video | F.document) & ~F.from_user.id == ADMIN_ID)
async def handle_donasi_upload(message: Message):
    user_info = f"🎁 **DONASI/KONTEN ANYAR**\n👤 Soko: {message.from_user.full_name}\n🆔 ID: `{message.from_user.id}`"
    
    # Forward neng admin
    await bot.send_message(ADMIN_ID, user_info)
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    await message.reply("✅ File udah dikirim ke admin thanks!.")

# ================= EXISTING HANDLERS =================

@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()
    
    args = message.text.split(" ", 1)
    if len(args) == 1:
        await message.answer("👋 aloo sayang ketik (garis miring) buat lihat daftar fitur.\nJoin dulu buat akses konten.")
        return
    await send_media(message.chat.id, message.from_user.id, args[1])

# --- ADMIN FEATURES (Filter ADMIN_ID) ---
@dp.message(Command("stats"), F.from_user.id == ADMIN_ID)
async def stats_handler(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1: u = await c1.fetchone()
        async with db.execute("SELECT COUNT(*) FROM media") as c2: m = await c2.fetchone()
    await message.answer(f"📊 Stats:\nUsers: {u[0]}\nMedia: {m[0]}")

@dp.message(F.from_user.id == ADMIN_ID, (F.photo | F.video), F.chat.type == "private")
async def admin_upload(message: Message):
    # Fitur upload media nggo dadi link start
    code = uuid.uuid4().hex[:8]
    f_id = message.photo[-1].file_id if message.photo else message.video.file_id
    m_t = "photo" if message.photo else "video"
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO media VALUES (?, ?, ?, ?)", (code, f_id, m_t, message.caption or ""))
        await db.commit()
    await message.reply(f"🔗 Link: `https://t.me/{BOT_USERNAME}?start={code}`")

# ================= SYSTEM & POLLING =================

async def send_media(chat_id: int, user_id: int, code: str):
    status = await check_membership(user_id)
    if not all(status):
        await bot.send_message(chat_id, "🚫 harus join semua jika udah klik cobalagi!", reply_markup=join_keyboard(code, status))
        return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (code,)) as cursor: row = await cursor.fetchone()
    if not row: return await bot.send_message(chat_id, "❌ Link mati atau salah.")
    
    if row[1] == "photo": await bot.send_photo(chat_id, row[0], caption=row[2], protect_content=True)
    else: await bot.send_video(chat_id, row[0], caption=row[2], protect_content=True)

async def main():
    await init_db()
    await set_commands() # Masang menu garis miring
    print("Bot is Running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
