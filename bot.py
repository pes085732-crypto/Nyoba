import asyncio
import uuid
import os
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    FSInputFile, CallbackQuery
)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

# ================= KONFIGURASI =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    OWNER_ID = int(os.getenv("ADMIN_ID"))
except (TypeError, ValueError):
    OWNER_ID = 0

# ================= INISIALISASI =================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher(storage=MemoryStorage())
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "media.db")

# ================= STATES =================
class AdminStates(StatesGroup):
    waiting_for_channel_post = State()
    waiting_for_fsub_list = State()
    waiting_for_addlist = State()
    waiting_for_broadcast = State()
    waiting_for_reply = State()
    waiting_for_new_admin = State()

class MemberStates(StatesGroup):
    waiting_for_ask = State()
    waiting_for_donation = State()

class PostMedia(StatesGroup):
    waiting_for_title = State()
    waiting_for_photo = State()

# ================= DATABASE HELPER =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS admins (admin_id INTEGER PRIMARY KEY)")
        await db.commit()

async def get_config(key, default=None):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT value FROM config WHERE key=?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else default

async def set_config(key, value):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

async def delete_config(key):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM config WHERE key=?", (key,))
        await db.commit()

async def is_admin(user_id: int):
    if user_id == OWNER_ID: return True
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT admin_id FROM admins WHERE admin_id=?", (user_id,)) as cur:
            return await cur.fetchone() is not None

# ================= HELPERS (FSUB CHECK) =================
async def check_membership(user_id: int):
    raw_targets = await get_config("fsub_channels")
    if not raw_targets: return True
    targets = raw_targets.split()
    not_joined_count = 0
    for target in targets:
        try:
            chat = await bot.get_chat(target)
            m = await bot.get_chat_member(chat.id, user_id)
            if m.status not in ("member", "administrator", "creator"):
                not_joined_count += 1
        except: pass
    return not_joined_count == 0

# ================= HANDLERS ADMIN PANEL =================
@dp.message(Command("panel"))
async def admin_panel(message: Message):
    if not await is_admin(message.from_user.id): return
    buttons = [[InlineKeyboardButton(text="⚙️ PENGATURAN LENGKAP", callback_data="open_settings")]]
    if message.from_user.id == OWNER_ID:
        buttons.append([InlineKeyboardButton(text="📡 Broadcast", callback_data="menu_broadcast"),
                        InlineKeyboardButton(text="📦 Backup Database", callback_data="menu_db")])
        buttons.append([InlineKeyboardButton(text="👤 Tambah Admin", callback_data="add_admin")])
    buttons.append([InlineKeyboardButton(text="❌ Tutup", callback_data="close_panel")])
    await message.reply("🛠 **PANEL KONTROL UTAMA**", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.message(Command("settings"))
async def admin_settings_command(m: Message):
    if not await is_admin(m.from_user.id): return
    await show_settings_menu(m)

@dp.callback_query(F.data == "open_settings")
async def settings_cb(c: CallbackQuery):
    if not await is_admin(c.from_user.id): return
    await show_settings_menu(c.message, is_edit=True)

async def show_settings_menu(message: Message, is_edit=False):
    ch_post = await get_config("channel_post", "Belum diset")
    fsub_list = await get_config("fsub_channels", "Belum diset")
    addlist = "Sudah diset" if await get_config("addlist_link") else "Belum diset"

    text = (
        "⚙️ **PENGATURAN SISTEM**\n\n"
        f"📢 **Auto Post:** `{ch_post}`\n"
        f"👥 **Fsub List:** `{fsub_list}`\n"
        f"🔗 **Addlist:** `{addlist}`\n\n"
        "Klik tombol kiri untuk **Ubah**, tombol kanan (🗑️) untuk **Hapus**."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Set Post CH", callback_data="set_post"), InlineKeyboardButton(text="🗑️", callback_data="del_channel_post")],
        [InlineKeyboardButton(text="👥 Set Fsub List", callback_data="set_fsub_list"), InlineKeyboardButton(text="🗑️", callback_data="del_fsub_channels")],
        [InlineKeyboardButton(text="🔗 Set Addlist", callback_data="set_addlist"), InlineKeyboardButton(text="🗑️", callback_data="del_addlist_link")],
        [InlineKeyboardButton(text="🔙 KEMBALI", callback_data="close_panel")]
    ])
    
    try:
        if is_edit:
            await message.edit_text(text, reply_markup=kb)
        else:
            await message.answer(text, reply_markup=kb)
    except TelegramBadRequest:
        # Jika pesan sama, abaikan saja agar tidak error di log
        pass

@dp.callback_query(F.data.startswith("del_"))
async def config_delete(c: CallbackQuery):
    if not await is_admin(c.from_user.id): return
    key = c.data.replace("del_", "")
    await delete_config(key)
    await c.answer(f"✅ Terhapus!", show_alert=True)
    await show_settings_menu(c.message, is_edit=True)

# ================= UPDATE DATABASE HANDLER (REPLY) =================
@dp.message(Command("update"))
async def update_database(m: Message):
    if not await is_admin(m.from_user.id): return
    if not m.reply_to_message or not m.reply_to_message.document:
        return await m.reply("❌ **Caranya:** Reply file `.db` hasil backup bot, lalu ketik `/update`.")

    doc = m.reply_to_message.document
    if not doc.file_name.endswith(".db"):
        return await m.reply("❌ Ini bukan file database (.db).")

    msg = await m.reply("⏳ Memproses pembaruan database...")
    try:
        # 1. Download file baru ke nama sementara
        new_db_path = DB_NAME + ".new"
        file = await bot.get_file(doc.file_id)
        await bot.download_file(file.file_path, new_db_path)

        # 2. Ganti file lama dengan yang baru (metode rename lebih aman)
        if os.path.exists(DB_NAME):
            os.remove(DB_NAME)
        os.rename(new_db_path, DB_NAME)

        # 3. Inisialisasi ulang DB untuk memastikan tabel ada
        await init_db()
        
        await msg.edit_text("✅ **DATABASE BERHASIL DIUPDATE!**\nData baru telah dimuat otomatis.")
    except Exception as e:
        await msg.edit_text(f"❌ Gagal update: {str(e)}")

# ================= HANDLERS INPUT ADMIN =================
@dp.callback_query(F.data == "add_admin", F.from_user.id == OWNER_ID)
async def add_admin_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim **User ID** admin baru:")
    await state.set_state(AdminStates.waiting_for_new_admin)
    await c.answer()

@dp.message(AdminStates.waiting_for_new_admin, F.from_user.id == OWNER_ID)
async def process_new_admin(m: Message, state: FSMContext):
    try:
        new_id = int(m.text.strip())
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (new_id,))
            await db.commit()
        await m.reply(f"✅ ID `{new_id}` jadi Admin.")
    except:
        await m.reply("❌ Masukkan angka ID!")
    await state.clear()

@dp.callback_query(F.data == "set_post")
async def set_post_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim **Username Channel** (cth: @channel):")
    await state.set_state(AdminStates.waiting_for_channel_post)
    await c.answer()

@dp.message(AdminStates.waiting_for_channel_post)
async def process_set_post(m: Message, state: FSMContext):
    await set_config("channel_post", m.text.strip())
    await m.reply(f"✅ Channel Post set ke: {m.text}")
    await state.clear()

@dp.callback_query(F.data == "set_fsub_list")
async def set_fsub_list_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim **List Username** (cth: @ch1 @ch2):")
    await state.set_state(AdminStates.waiting_for_fsub_list)
    await c.answer()

@dp.message(AdminStates.waiting_for_fsub_list)
async def process_fsub_list(m: Message, state: FSMContext):
    await set_config("fsub_channels", m.text.strip())
    await m.reply("✅ List Fsub disimpan.")
    await state.clear()

@dp.callback_query(F.data == "set_addlist")
async def set_addlist_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim **Link Addlist / Folder**:")
    await state.set_state(AdminStates.waiting_for_addlist)
    await c.answer()

@dp.message(AdminStates.waiting_for_addlist)
async def process_addlist(m: Message, state: FSMContext):
    await set_config("addlist_link", m.text.strip())
    await m.reply("✅ Link Addlist disimpan.")
    await state.clear()

@dp.callback_query(F.data == "menu_db", F.from_user.id == OWNER_ID)
async def send_db_cb(c: CallbackQuery):
    if os.path.exists(DB_NAME):
        await c.message.reply_document(FSInputFile(DB_NAME), caption="📦 **Backup Database**")
    await c.answer()

# ================= MEDIA & BROADCAST (SAMA DENGAN SEBELUMNYA) =================
@dp.callback_query(F.data == "menu_broadcast", F.from_user.id == OWNER_ID)
async def broadcast_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("📢 Kirim pesan broadcast:")
    await state.set_state(AdminStates.waiting_for_broadcast)
    await c.answer()

@dp.message(AdminStates.waiting_for_broadcast, F.from_user.id == OWNER_ID)
async def process_broadcast(m: Message, state: FSMContext):
    await m.reply("⏳ Sending...")
    count = 0
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            async for row in cursor:
                try:
                    await m.copy_to(row[0])
                    count += 1
                    await asyncio.sleep(0.05)
                except: pass
    await m.reply(f"✅ Terkirim ke {count} user.")
    await state.clear()

@dp.callback_query(F.data == "close_panel")
async def close_panel(c: CallbackQuery):
    await c.message.delete()

# --- Handler Member & Upload Tetap Sama Sesuai Kode Awalmu ---
@dp.callback_query(F.data == "menu_ask")
async def member_ask_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("📩 **TANYA ADMIN**\nSilahkan tulis pesanmu:")
    await state.set_state(MemberStates.waiting_for_ask)

@dp.message(MemberStates.waiting_for_ask)
async def process_member_ask(m: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ REPLY", callback_data=f"reply:{m.from_user.id}")]])
    await bot.send_message(OWNER_ID, f"📩 **PESAN BARU**\nDari: {m.from_user.full_name}\nID: `{m.from_user.id}`\n\nIsi: {m.text}", reply_markup=kb)
    await m.reply("✅ Terkirim.")
    await state.clear()

@dp.message(F.chat.type == "private", (F.photo | F.video | F.document), StateFilter(None))
async def admin_upload(m: Message, state: FSMContext):
    if not await is_admin(m.from_user.id): return
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    mtype = "photo" if m.photo else "video"
    await state.update_data(temp_fid=fid, temp_type=mtype)
    await state.set_state(PostMedia.waiting_for_title)
    await m.reply("📝 **JUDUL KONTEN:**")

@dp.message(PostMedia.waiting_for_title)
async def set_title_post(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(PostMedia.waiting_for_photo)
    await m.answer("📸 Kirim **FOTO COVER**:")

@dp.message(PostMedia.waiting_for_photo, F.photo)
async def finalize_post(m: Message, state: FSMContext):
    data = await state.get_data()
    code = uuid.uuid4().hex[:15]
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)", (code, data['temp_fid'], data['temp_type'], data['title']))
        await db.commit()
    
    bot_me = await bot.get_me()
    link = f"https://t.me/{bot_me.username}?start={code}"
    ch = await get_config("channel_post")
    if ch:
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎬 TONTON SEKARANG", url=link)]])
            await bot.send_photo(ch, m.photo[-1].file_id, caption=f"🔥 **{data['title']}**", reply_markup=kb)
        except: pass
    await m.answer(f"✅ Berhasil!\nLink: `{link}`")
    await state.clear()

@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()

    args = message.text.split(" ", 1)
    code = args[1] if len(args) > 1 else None
    
    if not await check_membership(message.from_user.id):
        link = await get_config("addlist_link") or f"https://t.me/{(await bot.get_me()).username}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 JOIN CHANNEL", url=link)],
            [InlineKeyboardButton(text="🔄 COBA LAGI", url=f"https://t.me/{(await bot.get_me()).username}?start={code}" if code else "https://t.me")]
        ])
        return await message.answer("⚠️ **AKSES DIKUNCI**\nSilahkan join dulu.", reply_markup=kb)

    if not code:
        return await message.answer(f"👋 Halo {message.from_user.first_name}!")

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (code,)) as cur:
            row = await cur.fetchone()
            if row:
                if row[1] == "photo": await bot.send_photo(message.chat.id, row[0], caption=row[2], protect_content=True)
                else: await bot.send_video(message.chat.id, row[0], caption=row[2], protect_content=True)

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
