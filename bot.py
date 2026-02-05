import asyncio, os, aiosqlite, traceback, random, string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    BotCommand, BotCommandScopeDefault, FSInputFile, CallbackQuery, ChatMemberUpdated, ChatPermissions)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

# ================= CONFIG (PASTIKAN DIISI!) =================
# Jika pakai VPS/Heroku, isi di environment variable. Jika lokal, langsung ganti stringnya.
BOT_TOKEN = os.getenv("BOT_TOKEN", "ISI_TOKEN_BOT_DI_SINI")
ADMIN_ID = int(os.getenv("ADMIN_ID", 123456789)) # Ganti dengan ID kamu
BOT_USN = os.getenv("BOT_USERNAME", "UsernameBotTanpaAt")

# Proteksi agar tidak error TokenValidationError
if not BOT_TOKEN or BOT_TOKEN == "ISI_TOKEN_BOT_DI_SINI":
    print("❌ ERROR: BOT_TOKEN belum diisi dengan benar!")
    exit()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

KATA_TERLARANG = ["biyo", "promosi", "biyoh", "bio", "open bo"]

class BotState(StatesGroup):
    wait_title = State()
    wait_cover = State()
    wait_ask = State()
    wait_broadcast = State()
    set_val = State()

def gen_code():
    # Menggunakan 30 karakter sesuai permintaan sebelumnya
    char = ''.join(random.choices(string.ascii_letters + string.digits, k=30))
    return f"get_{char}"

# ================= DATABASE =================
async def init_db():
    async with aiosqlite.connect("master.db") as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, fid TEXT, mtype TEXT, title TEXT, bk_id TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (uid INTEGER PRIMARY KEY, name TEXT)")
        await db.execute("""CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY, start_txt TEXT, fsub_txt TEXT, 
            btn_nonton TEXT, btn_donasi TEXT, btn_ask TEXT,
            fsub_list TEXT, fsub_link TEXT, db_ch_id TEXT, post_ch_id TEXT, 
            log_id TEXT, exempt_usn TEXT)""")
        await db.execute("""INSERT OR IGNORE INTO settings 
            (id, start_txt, fsub_txt, btn_nonton, btn_donasi, btn_ask, fsub_list, fsub_link, db_ch_id, post_ch_id, log_id, exempt_usn) 
            VALUES (1, 'Halo Selamat datang', 'Wajib Join Channel Kami!', '🎬 NONTON', '🎁 DONASI', '💬 TANYA ADMIN', '', '', '', '', '', '')""")
        await db.commit()

async def get_conf():
    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings WHERE id=1") as cur: return await cur.fetchone()

# ================= 1. ANTI-KATA TERLARANG & AUTO MUTE =================
@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def group_filter(m: Message):
    if not m.text: return
    s = await get_conf()
    # Pengecekan Exempt (Admin Kebal)
    exempt = [str(ADMIN_ID)] + (s['exempt_usn'].lower().replace("@","").split(",") if s['exempt_usn'] else [])
    user_ref = str(m.from_user.id) if not m.from_user.username else m.from_user.username.lower()

    if user_ref in exempt or str(m.from_user.id) in exempt: return

    if any(word in m.text.lower() for word in KATA_TERLARANG):
        try:
            await m.delete()
            await bot.restrict_chat_member(
                m.chat.id, m.from_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now() + timedelta(hours=24)
            )
            await m.answer(f"🔇 **AUTO-MUTE 24 JAM**\n{m.from_user.full_name} menggunakan kata terlarang.")
        except: pass

# ================= 2. LOG JOIN/LEFT (NEW) =================
@dp.chat_member()
async def log_member_activity(update: ChatMemberUpdated):
    s = await get_conf()
    if not s['log_id']: return
    user = update.from_user
    chat = update.chat
    
    if update.new_chat_member.status == "member":
        txt = f"🆕 **LOG JOIN**\n👤 {user.full_name}\n🆔 `{user.id}`\n🌐 GC: {chat.title}"
    elif update.new_chat_member.status in ["left", "kicked"]:
        txt = f"🚪 **LOG LEFT**\n👤 {user.full_name}\n🆔 `{user.id}`\n🌐 GC: {chat.title}"
    else: return
    
    try: await bot.send_message(s['log_id'], txt)
    except: pass

# ================= 3. ADMIN DASHBOARD =================
@dp.message(Command("settings"), F.from_user.id == ADMIN_ID)
async def cmd_settings(m: Message):
    s = await get_conf()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Teks Start", callback_data="conf_start_txt"), InlineKeyboardButton(text="Teks FSub", callback_data="conf_fsub_txt")],
        [InlineKeyboardButton(text="Link FSub", callback_data="conf_fsub_link"), InlineKeyboardButton(text="Username FSub", callback_data="conf_fsub_list")],
        [InlineKeyboardButton(text="ID Log", callback_data="conf_log_id"), InlineKeyboardButton(text="Exempt Admin", callback_data="conf_exempt_usn")],
        [InlineKeyboardButton(text="Stats", callback_data="adm_stats"), InlineKeyboardButton(text="Backup DB", callback_data="adm_dbfile")],
        [InlineKeyboardButton(text="❌ TUTUP", callback_data="adm_close")]
    ])
    await m.answer("⚙️ **ADMIN SETTINGS PANEL**", reply_markup=kb)

@dp.callback_query(F.data.startswith("conf_"))
async def config_edit(c: CallbackQuery, state: FSMContext):
    field = c.data.replace("conf_", "")
    await state.update_data(field=field)
    await state.set_state(BotState.set_val)
    await c.message.edit_text(f"Kirim nilai baru untuk `{field}`:\n(Gunakan -100 untuk ID Channel)")

@dp.message(BotState.set_val)
async def config_save(m: Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect("master.db") as db:
        await db.execute(f"UPDATE settings SET {data['field']}=? WHERE id=1", (m.text,))
        await db.commit()
    await m.answer(f"✅ `{data['field']}` berhasil diperbarui.")
    await state.clear()

# ================= 4. DATABASE & AUTO-POST =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document | F.animation), StateFilter(None))
async def upload_manager(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        # Donasi System
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ APPROVE", callback_data=f"don_app_{m.from_user.id}_{m.message_id}")]])
        await bot.forward_message(ADMIN_ID, m.chat.id, m.message_id)
        await bot.send_message(ADMIN_ID, f"🎁 Donasi: {m.from_user.full_name}", reply_markup=kb)
        return await m.answer("✅ Terkirim ke admin.")

    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    mtype = "photo" if m.photo else ("video" if m.video else "doc")
    await state.update_data(fid=fid, mtype=mtype)
    await state.set_state(BotState.wait_title)
    await m.answer("🏷️ Masukkan JUDUL konten:")

@dp.message(BotState.wait_title)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(BotState.wait_cover)
    await m.answer("📸 Kirim FOTO COVER:")

@dp.message(BotState.wait_cover, F.photo)
async def finalize_upload(m: Message, state: FSMContext):
    try:
        data = await state.get_data()
        s = await get_conf()
        code = gen_code()
        
        # Backup ke CH DB
        bk_id = ""
        if s['db_ch_id']:
            bk = await bot.send_photo(s['db_ch_id'], m.photo[-1].file_id, caption=f"KODE: `{code}`\nJUDUL: {data['title']}")
            bk_id = str(bk.message_id)
        
        async with aiosqlite.connect("master.db") as db:
            await db.execute("INSERT INTO media VALUES (?,?,?,?,?)", (code, data['fid'], data['mtype'], data['title'], bk_id))
            await db.commit()

        # Post ke CH Post
        if s['post_ch_id']:
            link = f"https://t.me/{BOT_USN}?start={code}"
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s['btn_nonton'], url=link)]])
            await bot.send_photo(s['post_ch_id'], m.photo[-1].file_id, caption=data['title'], reply_markup=kb)
        
        await m.answer(f"✅ POSTED!\nLink: `https://t.me/{BOT_USN}?start={code}`")
    finally: await state.clear()

# ================= 5. MEMBER INTERACTION =================
@dp.message(CommandStart())
async def start_logic(m: Message, code_override=None):
    s = await get_conf()
    arg = code_override if code_override else (m.text.split()[1] if len(m.text.split()) > 1 else None)
    
    # Simpan user stats & Log Start pertama kali
    async with aiosqlite.connect("master.db") as db:
        cur = await db.execute("SELECT uid FROM users WHERE uid=?", (m.from_user.id,))
        if not await cur.fetchone():
            await db.execute("INSERT INTO users VALUES (?,?)", (m.from_user.id, m.from_user.full_name))
            await db.commit()
            if s['log_id']:
                await bot.send_message(s['log_id'], f"🚀 **NEW USER START**\n👤 {m.from_user.full_name}\n🆔 `{m.from_user.id}`")

    if not arg:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=s['btn_donasi'], callback_data="mem_donasi"), InlineKeyboardButton(text=s['btn_ask'], callback_data="mem_ask")]
        ])
        return await m.answer(s['start_txt'], reply_markup=kb)

    # Force Join 3 Tempat (CH1, CH2, GRUP)
    must_join = False
    if s['fsub_list']:
        for ch in s['fsub_list'].replace("@","").split(","):
            if not ch.strip(): continue
            try:
                mem = await bot.get_chat_member(f"@{ch.strip()}", m.from_user.id)
                if mem.status not in ["member", "administrator", "creator"]:
                    must_join = True; break
            except: pass

    if must_join:
        kb = []
        if s['fsub_link']: kb.append([InlineKeyboardButton(text="🔗 GABUNG CHANNEL", url=s['fsub_link'])])
        kb.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"retry_{arg}")])
        return await m.answer(s['fsub_txt'], reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    # Panggil Media
    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM media WHERE code=?", (arg,)) as cur: row = await cur.fetchone()
    
    if row:
        if row['mtype'] == "photo": await bot.send_photo(m.chat.id, row['fid'], caption=row['title'])
        else: await bot.send_video(m.chat.id, row['fid'], caption=row['title'])
    else:
        await m.answer("❌ Konten tidak ditemukan.")

@dp.callback_query(F.data.startswith("retry_"))
async def retry_cb(c: CallbackQuery):
    code = c.data.replace("retry_", "")
    await c.message.delete()
    await start_logic(c.message, code_override=code)

@dp.callback_query(F.data == "mem_ask")
async def ask_btn(c: CallbackQuery, state: FSMContext):
    await state.set_state(BotState.wait_ask)
    await c.message.answer("💬 Kirim pesan kamu untuk admin:")

@dp.message(BotState.wait_ask)
async def ask_process(m: Message, state: FSMContext):
    await bot.send_message(ADMIN_ID, f"📩 **PESAN ASK**\nDari: {m.from_user.full_name}\n\n{m.text}")
    await m.answer("✅ Terkirim.")
    await state.clear()

# ================= 6. STATS & BC =================
@dp.callback_query(F.data == "adm_stats")
async def stats_cb(c: CallbackQuery):
    async with aiosqlite.connect("master.db") as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1: u = await c1.fetchone()
        async with db.execute("SELECT COUNT(*) FROM media") as c2: m = await c2.fetchone()
    await c.answer(f"📊 User: {u[0]} | Media: {m[0]}", show_alert=True)

@dp.callback_query(F.data == "adm_dbfile")
async def backup_cb(c: CallbackQuery):
    await c.message.answer_document(FSInputFile("master.db"))

@dp.callback_query(F.data == "adm_close")
async def close_cb(c: CallbackQuery): await c.message.delete()

# ================= RUN =================
async def main():
    await init_db()
    await bot.set_my_commands([
        BotCommand(command="start", description="Mulai Bot"),
        BotCommand(command="settings", description="Admin Only")
    ])
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
