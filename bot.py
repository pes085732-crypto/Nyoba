import asyncio
import uuid
import os
import aiosqlite
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    BotCommand, BotCommandScopeChat, FSInputFile, 
    CallbackQuery
)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= KONFIGURASI =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_USERNAME = os.getenv("BOT_USERNAME")
DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_cms.db")

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class AdminState(StatesGroup):
    waiting_input = State()

# ================= DATABASE ENGINE =================
async def set_setting(key, value):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))
        await db.commit()

async def get_setting(key):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else ""

# ================= UI COMPONENTS (ADMIN) =================
def main_dashboard_kb(protect_val):
    kb = [
        [InlineKeyboardButton(text="🆔 Multi-FSUB", callback_data="conf_fsub"), 
         InlineKeyboardButton(text="🔗 Addlist", callback_data="conf_addlist")],
        [InlineKeyboardButton(text="📝 Teks Start", callback_data="conf_start_txt"),
         InlineKeyboardButton(text="🗄 DB Channel", callback_data="conf_db_ch")],
        [InlineKeyboardButton(text=f"🛡 Proteksi: {protect_val}", callback_data="conf_toggle_prot"),
         InlineKeyboardButton(text="📢 Broadcast", callback_data="conf_bc")],
        [InlineKeyboardButton(text="📊 Stats", callback_data="conf_stats"),
         InlineKeyboardButton(text="❌ Tutup", callback_data="conf_close")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kembali", callback_data="conf_back")]])

# ================= HANDLERS ADMIN (ANTI-SPAM / EDIT MSG) =================

@dp.message(Command("settings"), F.from_user.id == ADMIN_ID)
async def open_dashboard(message: Message):
    prot = await get_setting('is_protected') or "OFF"
    await message.answer("🛠 **DASHBOARD SETTINGS**\nKelola bot secara instan di sini.", reply_markup=main_dashboard_kb(prot))

@dp.callback_query(F.data.startswith("conf_"), F.from_user.id == ADMIN_ID)
async def handle_admin_nav(c: CallbackQuery, state: FSMContext):
    action = c.data.replace("conf_", "")
    prot = await get_setting('is_protected') or "OFF"

    if action == "back":
        await state.clear()
        await c.message.edit_text("🛠 **DASHBOARD SETTINGS**", reply_markup=main_dashboard_kb(prot))
    
    elif action == "fsub":
        await c.message.edit_text("🆔 **SET MULTI-FSUB**\nKirim ID Channel (pisahkan koma):\nContoh: `-1001, -1002`", reply_markup=back_kb())
        await state.update_data(target="fsub_ids")
        await state.set_state(AdminState.waiting_input)

    elif action == "addlist":
        await c.message.edit_text("🔗 **SET ADDLIST**\nKirim Link Folder Addlist kamu:", reply_markup=back_kb())
        await state.update_data(target="addlist_url")
        await state.set_state(AdminState.waiting_input)

    elif action == "start_txt":
        await c.message.edit_text("📝 **SET TEKS START**\nKirim teks baru. Gunakan `{name}` untuk sapaan.", reply_markup=back_kb())
        await state.update_data(target="start_text")
        await state.set_state(AdminState.waiting_input)

    elif action == "db_ch":
        await c.message.edit_text("🗄 **SET DB CHANNEL**\nKirim ID Channel untuk backup database:", reply_markup=back_kb())
        await state.update_data(target="db_channel")
        await state.set_state(AdminState.waiting_input)

    elif action == "toggle_prot":
        new_prot = "ON" if prot == "OFF" else "OFF"
        await set_setting('is_protected', new_prot)
        await c.message.edit_reply_markup(reply_markup=main_dashboard_kb(new_prot))

    elif action == "close":
        await c.message.delete()
    
    await c.answer()

@dp.message(AdminState.waiting_input, F.from_user.id == ADMIN_ID)
async def process_admin_input(m: Message, state: FSMContext):
    data = await state.get_data()
    target = data.get("target")
    
    await set_setting(target, m.text)
    await m.delete() # Hapus pesan input user biar bersih
    
    prot = await get_setting('is_protected') or "OFF"
    # Edit kembali pesan dashboard lama agar tidak spam
    await bot.edit_message_text(
        chat_id=m.chat.id,
        message_id=m.message_id - 1, # Asumsi pesan dashboard tepat sebelum input
        text=f"✅ Berhasil memperbarui **{target}**\n\n🛠 **DASHBOARD SETTINGS**",
        reply_markup=main_dashboard_kb(prot)
    )
    await state.clear()

# ================= UI MEMBER (CLEAN) =================

@dp.message(CommandStart())
async def start_handler(message: Message):
    uid = message.from_user.id
    # Simpan User
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
        await db.commit()

    args = message.text.split()
    code = args[1] if len(args) > 1 else None
    
    # Logika FSUB Pintar
    fsub_ids = await get_setting('fsub_ids')
    addlist = await get_setting('addlist_url')
    
    not_joined = []
    if fsub_ids:
        for cid in fsub_ids.split(","):
            try:
                member = await bot.get_chat_member(cid.strip(), uid)
                if member.status not in ["member", "administrator", "creator"]:
                    not_joined.append(cid)
            except: continue

    if not_joined:
        btns = []
        if addlist:
            btns.append([InlineKeyboardButton(text="➕ Bergabung Sekarang", url=addlist)])
        else:
            for i, _ in enumerate(not_joined):
                btns.append([InlineKeyboardButton(text=f"Channel {i+1}", url="https://t.me/...")])
        
        btns.append([InlineKeyboardButton(text="🔄 Coba Lagi", url=f"https://t.me/{BOT_USERNAME}?start={code or ''}")])
        return await message.answer("Silakan bergabung dahulu untuk mengakses bot.", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

    # Tampilan Welcome Clean
    if not code:
        stext = await get_setting('start_text') or "Halo {name}!"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Kirim Konten", callback_data="m_donasi"),
             InlineKeyboardButton(text="💬 Tanya Admin", callback_data="m_ask")]
        ])
        return await message.answer(stext.format(name=message.from_user.first_name), reply_markup=kb)

    # Kirim Media
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, title FROM media WHERE code=?", (code,)) as cur:
            row = await cur.fetchone()
    if row:
        cap = f"✅ {row[2]}"
        if row[1] == "photo": await bot.send_photo(message.chat.id, row[0], caption=cap)
        else: await bot.send_video(message.chat.id, row[0], caption=cap)

# ================= BOOTING =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, title TEXT, backup_id INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.commit()

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
