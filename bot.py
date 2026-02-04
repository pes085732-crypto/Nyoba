import asyncio
import uuid
import os
import aiosqlite
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeDefault, BotCommandScopeChat, FSInputFile, CallbackQuery, ChatPermissions
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= KONFIGURASI =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else 0
CH1_USERNAME = os.getenv("CH1_USERNAME")
CH2_USERNAME = os.getenv("CH2_USERNAME")
GROUP_USERNAME = os.getenv("GROUP_USERNAME")
BOT_USERNAME = os.getenv("BOT_USERNAME")
EXEMPT_USERNAME = os.getenv("EXEMPT_USERNAME")

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

# ================= DATABASE =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.commit()

# ================= MENU COMMANDS =================
async def set_commands():
    # Menu untuk Member Umum
    member_commands = [
        BotCommand(command="start", description="Mulai Bot"),
        BotCommand(command="ask", description="Tanya Admin (Sambat)"),
        BotCommand(command="donasi", description="Kirim Konten/Donasi")
    ]
    await bot.set_my_commands(member_commands, scope=BotCommandScopeDefault())
    
    # Menu Khusus Admin
    admin_commands = member_commands + [
        BotCommand(command="stats", description="Cek Statistik"),
        BotCommand(command="all", description="Broadcast Pesan"),
        BotCommand(command="id", description="Cek ID Chat/User")
    ]
    if ADMIN_ID:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
        except: pass

# ================= HELPERS =================
async def check_membership(user_id: int):
    results = []
    for chat in [CH1_USERNAME, CH2_USERNAME, GROUP_USERNAME]:
        if not chat: continue
        target = chat if chat.startswith("@") else f"@{chat}"
        try:
            m = await bot.get_chat_member(target, user_id)
            results.append(m.status in ("member", "administrator", "creator"))
        except: results.append(False)
    return results

def join_keyboard(code: str, status: list):
    buttons = []
    links = [CH1_USERNAME, CH2_USERNAME, GROUP_USERNAME]
    names = ["📢 JOIN CH 1", "📢 JOIN CH 2", "👥 JOIN GRUP"]
    for i in range(len(status)):
        if not status[i] and links[i]:
            clean = links[i].replace("@", "")
            buttons.append([InlineKeyboardButton(text=names[i], url=f"https://t.me/{clean}")])
    buttons.append([InlineKeyboardButton(text="🔄 UPDATE / COBA LAGI", callback_data=f"retry:{code}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ================= HANDLERS =================

@dp.message(Command("id"))
async def get_id(message: Message):
    await message.reply(f"🆔 Chat ID: `{message.chat.id}`\n👤 User ID: `{message.from_user.id}`", parse_mode="Markdown")

@dp.message(Command("ask"))
async def ask_handler(message: Message):
    text = message.text.split(maxsplit=1)
    if len(text) < 2:
        return await message.reply("⚠️ Cara: `/ask pesan kamu`")
    
    msg_to_admin = f"📩 **PESAN ASK BARU**\n👤 User: {message.from_user.full_name}\n🆔 ID: `{message.from_user.id}`\n\n💬 Pesan: {text[1]}"
    await bot.send_message(ADMIN_ID, msg_to_admin, parse_mode="Markdown")
    await bot.send_message(LOG_GROUP_ID, f"💬 {message.from_user.full_name} mengirim /ask ke admin.")
    await message.reply("✅ Pesanmu sudah terkirim ke admin.")

@dp.message(Command("donasi"))
async def donasi_cmd(message: Message):
    await message.answer("🙏 Silakan langsung kirim **Foto/Video** yang ingin kamu donasikan ke bot ini.\n\nNanti admin akan mereview untuk diposting.")

@dp.message(F.chat.type == "private", (F.photo | F.video | F.document | F.animation))
async def handle_media_donasi(message: Message):
    if message.from_user.id == ADMIN_ID:
        # Jika admin kirim media langsung tanpa /all, buatkan link
        if message.caption and "/all" in message.caption: return
        code = uuid.uuid4().hex[:8]
        fid = message.photo[-1].file_id if message.photo else (message.video.file_id if message.video else message.document.file_id)
        mtype = "photo" if message.photo else "video"
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT INTO media VALUES (?,?,?,?)", (code, fid, mtype, message.caption or ""))
            await db.commit()
        return await message.reply(f"🔗 Link Admin: `https://t.me/{BOT_USERNAME}?start={code}`", parse_mode="Markdown")

    # Untuk User (Donasi)
    await bot.send_message(LOG_GROUP_ID, f"🎁 **DONASI MASUK**\nDari: {message.from_user.full_name}\nID: `{message.from_user.id}`")
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ POST", callback_data=f"approve:{message.from_user.id}"),
        InlineKeyboardButton(text="❌ REJECT", callback_data="reject")
    ]])
    await bot.send_message(ADMIN_ID, f"Review donasi dari {message.from_user.full_name}:", reply_markup=kb)
    await message.reply("✅ Media donasi sudah diterima admin. Makasih!")

@dp.callback_query(F.data == "reject")
async def process_reject(c: CallbackQuery):
    await c.message.delete()
    await c.answer("Konten ditolak & dihapus.", show_alert=True)

@dp.callback_query(F.data.startswith("approve"))
async def process_approve(c: CallbackQuery, state: FSMContext):
    await state.set_state(PostDonasi.waiting_for_title)
    await c.message.answer("📝 Masukkan **JUDUL** postingan:")
    await c.answer()

@dp.message(PostDonasi.waiting_for_title)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(PostDonasi.waiting_for_photo)
    await m.answer("📸 Sekarang kirim **FOTO COVER** untuk linknya:")

@dp.message(PostDonasi.waiting_for_photo, F.photo)
async def finalize_post(m: Message, state: FSMContext):
    data = await state.get_data()
    code = uuid.uuid4().hex[:8]
    fid = m.photo[-1].file_id
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)", (code, fid, "photo", data['title']))
        await db.commit()
    
    link = f"https://t.me/{BOT_USERNAME}?start={code}"
    await m.answer(f"✅ **POSTINGAN BERHASIL**\n\nJudul: {data['title']}\nLink: `{link}`")
    await bot.send_message(LOG_GROUP_ID, f"📢 **KONTEN BARU**\nJudul: {data['title']}\nLink: {link}")
    await state.clear()

@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()
    
    args = message.text.split(" ", 1)
    if len(args) == 1:
        return await message.answer(f"👋 Halo {message.from_user.first_name}!\nKetik /ask untuk tanya admin atau /donasi untuk kirim konten.")
    
    # Kirim Media
    code = args[1]
    status = await check_membership(message.from_user.id)
    if not all(status):
        return await message.answer("🚫 Bergabunglah ke channel kami dulu!", reply_markup=join_keyboard(code, status))
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (code,)) as cur:
            row = await cur.fetchone()
    
    if row:
        if row[1] == "photo": await bot.send_photo(message.chat.id, row[0], caption=row[2])
        else: await bot.send_video(message.chat.id, row[0], caption=row[2])
    else: await message.answer("❌ Link kadaluarsa atau salah.")

# ================= SISTEM =================
async def main():
    await init_db()
    await set_commands()
    # Hapus webhook dan drop updates yang numpuk (Anti-Conflict)
    await bot.delete_webhook(drop_pending_updates=True)
    print("Bot is ready...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
