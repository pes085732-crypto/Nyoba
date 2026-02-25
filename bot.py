import asyncio
import uuid
import os
import aiosqlite
import logging
from datetime import datetime, timedelta
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

# ================= KONFIGURASI =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    OWNER_ID = int(os.getenv("ADMIN_ID"))
except (TypeError, ValueError):
    OWNER_ID = 0

DB_NAME = "media.db"
logging.basicConfig(level=logging.INFO)

# ================= STATES =================
class AdminStates(StatesGroup):
    waiting_for_channel_post = State()
    waiting_for_fsub_list = State()
    waiting_for_broadcast = State()
    waiting_for_reply = State()
    waiting_for_new_admin = State()
    waiting_for_qris = State()
    waiting_for_preview = State()
    waiting_for_cover = State()
    waiting_for_add_title = State()
    waiting_for_log_group = State()

class MemberStates(StatesGroup):
    waiting_for_ask = State()
    waiting_for_donation = State()
    waiting_for_vip_ss = State()
    waiting_for_token_clone = State()

class PostMedia(StatesGroup):
    waiting_for_post_title = State()
    waiting_for_final_confirm = State()

# ================= DATABASE ENGINE =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, owner_id INTEGER, type TEXT, caption TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS admins (admin_id INTEGER, bot_id INTEGER, PRIMARY KEY (admin_id, bot_id))")
        await db.execute("CREATE TABLE IF NOT EXISTS titles (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS clones (bot_token TEXT PRIMARY KEY, owner_id INTEGER, expired_at TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS bot_settings (bot_id INTEGER PRIMARY KEY, log_group_id INTEGER, qris_file_id TEXT, cover_file_id TEXT, preview_msg_id TEXT, channel_post TEXT)")
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

async def is_admin(user_id: int, bot_id: int):
    if int(user_id) == OWNER_ID: return True
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT admin_id FROM admins WHERE admin_id=? AND bot_id=?", (user_id, bot_id)) as cur:
            res = await cur.fetchone()
            return res is not None

async def get_bot_setting(bot_id: int, key: str, default=None):
    async with aiosqlite.connect(DB_NAME) as db:
        # Kita ambil kolom dinamis berdasarkan key
        try:
            async with db.execute(f"SELECT {key} FROM bot_settings WHERE bot_id=?", (bot_id,)) as cur:
                row = await cur.fetchone()
                return row[0] if row and row[0] else default
        except: return default

async def update_bot_setting(bot_id: int, key: str, value: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f"INSERT INTO bot_settings (bot_id, {key}) VALUES (?, ?) ON CONFLICT(bot_id) DO UPDATE SET {key}=excluded.{key}", (bot_id, value))
        await db.commit()

async def send_bot_log(bot_obj: Bot, text: str):
    me = await bot_obj.get_me()
    log_id = await get_bot_setting(me.id, "log_group_id")
    if log_id:
        try: await bot_obj.send_message(log_id, f"🔔 **LOG @{me.username}**\n{text}")
        except: pass

async def check_fsub(bot_obj: Bot, user_id: int):
    if int(user_id) == OWNER_ID: return []
    raw = await get_config("fsub_channels")
    if not raw: return []
    channels = [c.strip() for c in raw.split() if c.strip()]
    unjoined = []
    for ch in channels:
        try:
            target = ch if ch.startswith("-100") or ch.startswith("@") else f"@{ch.replace('https://t.me/','')}"
            member = await bot_obj.get_chat_member(chat_id=target, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]: unjoined.append(target)
        except: unjoined.append(target)
    return unjoined

# ================= KEYBOARDS =================
def member_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 DONASI", callback_data="menu_donasi"), InlineKeyboardButton(text="❓ ASK", callback_data="menu_ask")],
        [InlineKeyboardButton(text="💎 ORDER VIP", callback_data="menu_vip"), InlineKeyboardButton(text="👀 PREVIEW VIP", callback_data="vip_preview")],
        [InlineKeyboardButton(text="🤖 CLONE BOT (GRATIS/TRIAL)", callback_data="menu_clone")]
    ])

async def get_titles_kb():
    kb = []
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT title FROM titles ORDER BY id DESC LIMIT 10") as cur:
            async for row in cur:
                kb.append([InlineKeyboardButton(text=row[0], callback_data=f"t_sel:{row[0][:20]}")])
    kb.append([InlineKeyboardButton(text="➕ TAMBAH JUDUL", callback_data="add_title_btn")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ================= DISPATCHER & ROUTER =================
dp = Dispatcher(storage=MemoryStorage())

# --- START & FSUB ---
@dp.message(CommandStart())
async def start_handler(m: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (m.from_user.id,))
        await db.commit()
    
    args = m.text.split()
    target_code = args[1] if len(args) > 1 else "none"

    unjoined = await check_fsub(m.bot, m.from_user.id)
    if unjoined:
        kb = [[InlineKeyboardButton(text=f"📢 JOIN CHANNEL", url=f"https://t.me/{c.replace('@','')}") ] for c in unjoined]
        kb.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"check_sub:{target_code}")])
        return await m.answer("⚠️ **AKSES DIKUNCI**\nJoin channel sponsor dulu bre!", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    if target_code != "none":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT file_id, type, caption FROM media WHERE code=?", (target_code,)) as cur:
                row = await cur.fetchone()
                if row:
                    await send_bot_log(m.bot, f"User `{m.from_user.id}` mengambil file `{target_code}`")
                    if row[1] == "photo": await m.answer_photo(row[0], caption=row[2], protect_content=True)
                    else: await m.answer_video(row[0], caption=row[2], protect_content=True)
                    return

    await m.answer(f"👋 Halo {m.from_user.first_name}!", reply_markup=member_main_kb())

@dp.callback_query(F.data.startswith("check_sub:"))
async def check_sub_cb(c: CallbackQuery):
    unjoined = await check_fsub(c.bot, c.from_user.id)
    if unjoined: return await c.answer("❌ Belum join semua!", show_alert=True)
    await c.message.delete()
    code = c.data.split(":")[1]
    # Re-run start
    new_m = Message(message_id=c.message.message_id, date=c.message.date, chat=c.message.chat, from_user=c.from_user, text=f"/start {code}")
    await start_handler(new_m)

# --- MULTI-PART UPLOAD ---
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document), StateFilter(None))
async def admin_upload(m: Message, state: FSMContext):
    me = await m.bot.get_me()
    if not await is_admin(m.from_user.id, me.id): return
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    mtype = "photo" if m.photo else "video"
    await state.update_data(temp_fid=fid, temp_type=mtype, temp_caption=(m.caption or ""), parts=[])
    await state.set_state(PostMedia.waiting_for_post_title)
    await m.reply("📝 **PILIH JUDUL:**", reply_markup=await get_titles_kb())

@dp.callback_query(PostMedia.waiting_for_post_title, F.data.startswith("t_sel:"))
async def select_title_handler(c: CallbackQuery, state: FSMContext):
    title = c.data.split(":")[1]
    await add_part_to_list(c.message, state, title)

@dp.callback_query(PostMedia.waiting_for_post_title, F.data == "add_title_btn")
async def add_new_title_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Ketik judul baru:")
    await state.set_state(AdminStates.waiting_for_add_title)

@dp.message(AdminStates.waiting_for_add_title)
async def process_save_title(m: Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO titles (title) VALUES (?)", (m.text,))
        await db.commit()
    await add_part_to_list(m, state, m.text)

async def add_part_to_list(msg, state, p_title):
    data = await state.get_data()
    code = uuid.uuid4().hex[:12]
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media (code, file_id, type, caption, owner_id) VALUES (?, ?, ?, ?, ?)", 
                       (code, data['temp_fid'], data['temp_type'], data['temp_caption'], msg.from_user.id))
        await db.commit()
    parts = data.get('parts', [])
    parts.append(code)
    await state.update_data(parts=parts, current_title=p_title)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ TAMBAH PART", callback_data="add_more_part")],
        [InlineKeyboardButton(text="🚀 POST SEKARANG", callback_data="final_publish")]
    ])
    await msg.answer(f"✅ Part {len(parts)} Siap.\nJudul: **{p_title}**", reply_markup=kb)
    await state.set_state(PostMedia.waiting_for_final_confirm)

@dp.callback_query(PostMedia.waiting_for_final_confirm, F.data == "add_more_part")
async def add_more_part_cb(c: CallbackQuery):
    await c.message.answer("Kirim media selanjutnya:")

@dp.message(F.chat.type == "private", (F.photo | F.video | F.document), StateFilter(PostMedia.waiting_for_final_confirm))
async def handle_next_part(m: Message, state: FSMContext):
    data = await state.get_data()
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    mtype = "photo" if m.photo else "video"
    await state.update_data(temp_fid=fid, temp_type=mtype, temp_caption=(m.caption or ""))
    await add_part_to_list(m, state, data['current_title'])

@dp.callback_query(PostMedia.waiting_for_final_confirm, F.data == "final_publish")
async def final_post_handler(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    parts, p_title = data['parts'], data['current_title']
    me = await c.bot.get_me()
    kb_rows = []
    if len(parts) == 1:
        kb_rows.append([InlineKeyboardButton(text="🎬 TONTON", url=f"https://t.me/{me.username}?start={parts[0]}")])
    else:
        row = []
        for i, code in enumerate(parts, 1):
            row.append(InlineKeyboardButton(text=f"Part {i}", url=f"https://t.me/{me.username}?start={code}"))
            if len(row) == 2: kb_rows.append(row); row = []
        if row: kb_rows.append(row)

    ch = await get_bot_setting(me.id, "channel_post")
    cover = await get_bot_setting(me.id, "cover_file_id")
    if ch:
        try:
            if cover: await c.bot.send_photo(ch, cover, caption=f"**{p_title}**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
            else: await c.bot.send_message(ch, f"**{p_title}**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
            await c.message.answer("✅ Berhasil diposting ke channel!")
        except Exception as e: await c.message.answer(f"❌ Gagal post: {e}")
    else: await c.message.answer("❌ Channel post belum diset di /panel")
    await state.clear()

# --- CLONE SYSTEM ---
@dp.callback_query(F.data == "menu_clone")
async def clone_menu(c: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 TRIAL 1 HARI", callback_data="start_trial")],
        [InlineKeyboardButton(text="💎 BELI VIP CLONE", callback_data="menu_vip")]
    ])
    await c.message.edit_text("🤖 **CLONE BOT SYSTEM**\nBuat bot serupa dengan token kamu sendiri.", reply_markup=kb)

@dp.callback_query(F.data == "start_trial")
async def trial_clone(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim API TOKEN dari @BotFather:"); await state.set_state(MemberStates.waiting_for_token_clone)

@dp.message(MemberStates.waiting_for_token_clone)
async def process_clone(m: Message, state: FSMContext):
    token = m.text.strip()
    try:
        temp_bot = Bot(token=token)
        me_clone = await temp_bot.get_me()
        await temp_bot.session.close()
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR REPLACE INTO clones (bot_token, owner_id, expired_at) VALUES (?, ?, ?)", 
                           (token, m.from_user.id, datetime.now() + timedelta(days=1)))
            await db.execute("INSERT OR IGNORE INTO admins (admin_id, bot_id) VALUES (?, ?)", (m.from_user.id, me_clone.id))
            await db.commit()
        await m.reply(f"✅ Berhasil! Bot @{me_clone.username} aktif. Restarting system..."); await state.clear()
        os._exit(1)
    except: await m.reply("❌ Token salah!")

# --- ADMIN PANEL ---
@dp.message(Command("panel"))
async def admin_panel(m: Message):
    me = await m.bot.get_me()
    if not await is_admin(m.from_user.id, me.id): return
    btns = [
        [InlineKeyboardButton(text="⚙️ SETTINGS", callback_data="open_settings")],
        [InlineKeyboardButton(text="🖼 COVER", callback_data="set_cover"), InlineKeyboardButton(text="🖼 QRIS", callback_data="set_qris")],
        [InlineKeyboardButton(text="📺 PREVIEW", callback_data="set_preview"), InlineKeyboardButton(text="🔔 LOG GROUP", callback_data="set_log")],
        [InlineKeyboardButton(text="📡 BC", callback_data="menu_broadcast"), InlineKeyboardButton(text="📦 DB", callback_data="menu_db")],
        [InlineKeyboardButton(text="❌ TUTUP", callback_data="close_panel")]
    ]
    await m.reply(f"🛠 **PANEL ADMIN @{me.username}**", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data == "open_settings")
async def settings_cb(c: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 POST CH", callback_data="set_post")],
        [InlineKeyboardButton(text="👥 FSUB (GLOBAL)", callback_data="set_fsub_list")],
        [InlineKeyboardButton(text="🔙 KEMBALI", callback_data="close_panel")]
    ])
    await c.message.edit_text("⚙️ **CONFIG**", reply_markup=kb)

# --- ADMIN ACTIONS (Cover, QRIS, Log, etc) ---
@dp.callback_query(F.data == "set_qris")
async def set_qris_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim Foto QRIS:"); await state.set_state(AdminStates.waiting_for_qris)

@dp.message(AdminStates.waiting_for_qris, F.photo)
async def save_qris(m: Message, state: FSMContext):
    me = await m.bot.get_me()
    await update_bot_setting(me.id, "qris_file_id", m.photo[-1].file_id)
    await m.reply("✅ QRIS Tersimpan."); await state.clear()

@dp.callback_query(F.data == "set_log")
async def set_log_cb(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim ID Group Log (pake -100):"); await state.set_state(AdminStates.waiting_for_log_group)

@dp.message(AdminStates.waiting_for_log_group)
async def save_log_group(m: Message, state: FSMContext):
    me = await m.bot.get_me()
    await update_bot_setting(me.id, "log_group_id", m.text)
    await m.reply("✅ Log Group Terpasang."); await state.clear()

# --- MEMBER INTERACTION (ASK/VIP) ---
@dp.callback_query(F.data == "menu_ask")
async def ask_btn(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirim pesan:"); await state.set_state(MemberStates.waiting_for_ask)

@dp.message(MemberStates.waiting_for_ask)
async def process_ask(m: Message, state: FSMContext):
    await m.forward(OWNER_ID); await m.reply("✅ Terkirim ke pusat."); await state.clear()

@dp.callback_query(F.data == "menu_vip")
async def order_vip(c: CallbackQuery, state: FSMContext):
    me = await c.bot.get_me()
    qris = await get_bot_setting(me.id, "qris_file_id")
    if not qris: return await c.answer("QRIS belum diset admin.", show_alert=True)
    await c.bot.send_photo(c.message.chat.id, qris, caption="Silahkan bayar dan kirim SS Bukti:"); await state.set_state(MemberStates.waiting_for_vip_ss)

@dp.message(MemberStates.waiting_for_vip_ss, F.photo)
async def process_vip_ss(m: Message, state: FSMContext):
    await m.forward(OWNER_ID); await m.reply("✅ SS Terkirim, tunggu konfirmasi."); await state.clear()

# --- DATABASE & GLOBAL BC ---
@dp.callback_query(F.data == "menu_db", F.from_user.id == OWNER_ID)
async def send_db_cb(c: CallbackQuery):
    if os.path.exists(DB_NAME): await c.message.reply_document(FSInputFile(DB_NAME))
    await c.answer()

@dp.message(Command("bc_global"), F.from_user.id == OWNER_ID)
async def bc_global(m: Message):
    count = 0
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            async for row in cur:
                try: await m.copy_to(row[0]); count += 1; await asyncio.sleep(0.05)
                except: pass
    await m.reply(f"✅ Global BC Selesai ke {count} user.")

# ================= RUNNER =================
async def auto_backup_task(bot_obj: Bot):
    while True:
        await asyncio.sleep(3600 * 6)
        if os.path.exists(DB_NAME):
            try: await bot_obj.send_document(OWNER_ID, FSInputFile(DB_NAME), caption="📦 AUTO BACKUP")
            except: pass

async def main():
    await init_db()
    master_bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    asyncio.create_task(auto_backup_task(master_bot))

    # Jalankan Master + Clones
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT bot_token FROM clones") as cur:
            async for row in cur:
                try: asyncio.create_task(dp.start_polling(Bot(token=row[0], default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))))
                except: pass

    print("🚀 ALL BOTS STARTING...")
    await master_bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(master_bot)

if __name__ == "__main__":
    asyncio.run(main())
