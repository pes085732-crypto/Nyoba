import asyncio
import uuid
import os
import aiosqlite
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, Router
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
OWNER_ID = int(os.getenv("ADMIN_ID"))
except:
    OWNER_ID = 0
DB_NAME = "media.db"  # Nama DB tetap sama agar data lama aman

logging.basicConfig(level=logging.INFO)

# ================= STATES =================
class AdminStates(StatesGroup):
    waiting_for_fsub_list = State()
    waiting_for_broadcast = State()
    waiting_for_reply = State()
    waiting_for_qris = State()
    waiting_for_cover = State()
    waiting_for_add_title = State()
    waiting_for_log_group = State()
    waiting_for_new_admin = State()

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
        # Tabel Media (Data file)
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, file_id TEXT, owner_id INTEGER, type TEXT, caption TEXT)")
        # Tabel Users (Semua user dari semua bot)
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        # Tabel Config (FSub, dll)
        await db.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
        # Tabel Admins (Multi-admin per bot)
        await db.execute("CREATE TABLE IF NOT EXISTS admins (admin_id INTEGER, bot_id INTEGER, PRIMARY KEY (admin_id, bot_id))")
        # Tabel Judul (Untuk posting)
        await db.execute("CREATE TABLE IF NOT EXISTS titles (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT)")
        # Tabel Clone (Data penyewa)
        await db.execute("CREATE TABLE IF NOT EXISTS clones (bot_token TEXT PRIMARY KEY, owner_id INTEGER, expired_at TIMESTAMP)")
        # Tabel Settings Bot (Log group, cover, qris tiap clone)
        await db.execute("CREATE TABLE IF NOT EXISTS bot_settings (bot_id INTEGER PRIMARY KEY, log_group_id INTEGER, qris_file_id TEXT, cover_file_id TEXT)")
        await db.commit()

async def get_config(key, default=None):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT value FROM config WHERE key=?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else default

async def is_admin(user_id: int, bot_id: int):
    # Pastikan user_id diconvert ke int buat jaga-jaga
    if int(user_id) == OWNER_ID: 
        return True
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT admin_id FROM admins WHERE admin_id=? AND bot_id=?", (user_id, bot_id)) as cur:
            return await cur.fetchone() is not None

async def send_bot_log(bot_obj: Bot, text: str):
    me = await bot_obj.get_me()
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT log_group_id FROM bot_settings WHERE bot_id=?", (me.id,)) as cur:
            row = await cur.fetchone()
            if row and row[0]:
                try: await bot_obj.send_message(row[0], f"🔔 **LOG BOT @{me.username}**\n{text}")
                except: pass

async def check_fsub(bot_obj: Bot, user_id: int):
    # Jika user adalah OWNER_ID, langsung skip FSub (Biar gak disuruh join)
    if int(user_id) == OWNER_ID:
        return []

    raw = await get_config("fsub_channels")
    if not raw: return []
    
    channels = [c.strip() for c in raw.split() if c.strip()]
    unjoined = []
    
    for ch in channels:
        try:
            # Telegram API butuh ID (pake -100) atau @username
            target = ch if ch.startswith("-100") or ch.startswith("@") else f"@{ch}"
            member = await bot_obj.get_chat_member(chat_id=target, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                unjoined.append(ch)
        except Exception as e:
            print(f"FSub Error for {ch}: {e}")
            unjoined.append(ch)
    return unjoined

# ================= KEYBOARDS =================
def member_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 DONASI", callback_data="menu_donasi"), InlineKeyboardButton(text="❓ ASK", callback_data="menu_ask")],
        [InlineKeyboardButton(text="💎 ORDER VIP", callback_data="menu_vip"), InlineKeyboardButton(text="👀 PREVIEW VIP", callback_data="vip_preview")],
        [InlineKeyboardButton(text="🤖 CLONE BOT (GRATIS)", callback_data="menu_clone")]
    ])

async def get_titles_kb():
    kb = []
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT title FROM titles ORDER BY id DESC LIMIT 10") as cur:
            async for row in cur:
                kb.append([InlineKeyboardButton(text=row[0], callback_data=f"t_sel:{row[0][:20]}")])
    kb.append([InlineKeyboardButton(text="➕ TAMBAH JUDUL", callback_data="add_title_btn")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ================= HANDLERS UTAMA =================
dp = Dispatcher(storage=MemoryStorage())

@dp.message(CommandStart())
@dp.message(CommandStart())
async def start_handler(m: Message):
    # Tambahkan user ke DB
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (m.from_user.id,))
        await db.commit()
    
    # CEK JIKA USER ADALAH OWNER (Langsung bypass semua)
    if int(m.from_user.id) == OWNER_ID:
        return await m.answer(f"👑 Halo Bos {m.from_user.first_name}!\nAnda adalah Owner Pusat.", reply_markup=member_main_kb())

    # Jika bukan owner, baru cek FSub
    unjoined = await check_fsub(m.bot, m.from_user.id)
    if unjoined:
        kb = []
        for c in unjoined:
            # Logika bikin link join: Kalau ID -100, admin harus set link manual 
            # atau bot bakal arahin ke username jika tersedia.
            btn_text = f"📢 JOIN CHANNEL"
            url = f"https://t.me/{c.replace('@','').replace('-100','')}" if not c.startswith("-100") else "https://t.me/c/xxxxxx" 
            kb.append([InlineKeyboardButton(text=btn_text, url=url)])
            
        kb.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data="check_ulang")])
        return await m.answer("⚠️ **AKSES DIKUNCI**\nJoin channel dulu bre!", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    await m.answer(f"👋 Halo {m.from_user.first_name}!", reply_markup=member_main_kb())

# --- FITUR AUTO POST MULTI-PART ---
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document), StateFilter(None))
async def admin_upload(m: Message, state: FSMContext):
    me = await m.bot.get_me()
    if not await is_admin(m.from_user.id, me.id): return
    
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    mtype = "photo" if m.photo else "video"
    await state.update_data(temp_fid=fid, temp_type=mtype, temp_caption=(m.caption or ""), parts=[])
    await state.set_state(PostMedia.waiting_for_post_title)
    await m.reply("📝 **PILIH JUDUL UNTUK POST INI:**", reply_markup=await get_titles_kb())

@dp.callback_query(PostMedia.waiting_for_post_title, F.data.startswith("t_sel:"))
async def select_title_handler(c: CallbackQuery, state: FSMContext):
    title = c.data.split(":")[1]
    data = await state.get_data()
    code = uuid.uuid4().hex[:10]
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO media (code, file_id, owner_id, type, caption) VALUES (?, ?, ?, ?, ?)",
                       (code, data['temp_fid'], c.from_user.id, data['temp_type'], data['temp_caption']))
        await db.commit()
    
    parts = data.get('parts', [])
    parts.append(code)
    await state.update_data(parts=parts, current_title=title)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ TAMBAH PART LAIN", callback_data="add_more_part")],
        [InlineKeyboardButton(text="🚀 POST SEKARANG", callback_data="final_publish")]
    ])
    await c.message.edit_text(f"✅ Part {len(parts)} Berhasil Disimpan!\n\nJudul: **{title}**\nCode: `{code}`", reply_markup=kb)

@dp.callback_query(F.data == "add_more_part")
async def add_more_part_handler(c: CallbackQuery):
    await c.message.answer("Silahkan kirim file (Foto/Video) untuk part selanjutnya:")
    # State tetap di PostMedia tapi menunggu file baru

# --- FITUR CLONE BOT (AUTOPILOT) ---
@dp.callback_query(F.data == "menu_clone")
async def clone_pricing(c: CallbackQuery):
    text = (
        "🤖 **PENYEWAAN BOT CLONE**\n\n"
        "1 Bulan: Rp 30.000\n"
        "2 Bulan: Rp 55.000\n"
        "3 Bulan: Rp 80.000\n\n"
        "🎁 **FREE TRIAL 1 HARI**"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 BELI (1 BLN)", callback_data="pay:1:30000")],
        [InlineKeyboardButton(text="🎁 TRIAL 1 HARI", callback_data="start_trial")],
        [InlineKeyboardButton(text="📖 TUTORIAL", callback_data="show_tutor")]
    ])
    await c.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data == "start_trial")
async def start_trial(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kirimkan **API TOKEN** bot kamu dari @BotFather:")
    await state.set_state(MemberStates.waiting_for_token_clone)

@dp.message(MemberStates.waiting_for_token_clone)
async def process_clone_token(m: Message, state: FSMContext):
    token = m.text.strip()
    try:
        test_bot = Bot(token=token)
        me = await test_bot.get_me()
        await test_bot.session.close()
        
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR REPLACE INTO clones (bot_token, owner_id, expired_at) VALUES (?, ?, ?)",
                           (token, m.from_user.id, datetime.now() + timedelta(days=1)))
            await db.execute("INSERT OR IGNORE INTO admins (admin_id, bot_id) VALUES (?, ?)", (m.from_user.id, me.id))
            await db.commit()
        
        await m.reply(f"✅ **BOT CLONE AKTIF!**\n\nUsername: @{me.username}\nBuka bot tersebut dan ketik /panel untuk setting.")
        await state.clear()
        # Jalankan polling bot baru secara asinkron
        asyncio.create_task(run_new_clone(token))
    except:
        await m.reply("❌ Token tidak valid!")

# --- SISTEM AUTO BACKUP & GLOBAL BROADCAST ---
async def auto_backup_task():
    while True:
        await asyncio.sleep(6 * 3600) # 6 Jam
        if os.path.exists(DB_NAME):
            try:
                main_bot = Bot(token=BOT_TOKEN)
                await main_bot.send_document(OWNER_ID, FSInputFile(DB_NAME), caption=f"🔄 **AUTO BACKUP**\n{datetime.now()}")
                await main_bot.session.close()
            except: pass

@dp.message(Command("bc_global"), F.from_user.id == OWNER_ID)
async def bc_global_handler(m: Message):
    count = 0
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            async for row in cur:
                try: 
                    await m.copy_to(row[0])
                    count += 1
                    await asyncio.sleep(0.05)
                except: pass
    await m.reply(f"🚀 **GLOBAL BC SELESAI**\nPesan terkirim ke {count} user di semua jaringan bot.")

# ================= RUNNER =================
async def run_new_clone(token):
    try:
        new_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
        new_dp = Dispatcher(storage=MemoryStorage())
        # Daftarkan semua handler ke dispatcher baru
        new_dp.include_router(dp.router) # Menggunakan router utama
        await new_dp.start_polling(new_bot)
    except: pass

# Tambahkan ini di luar fungsi main (di bagian atas setelah konfigurasi)
# agar variabel 'bot' bisa diakses di mana saja
master_bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))

async def main():
    await init_db()
    
    # Jalankan background task backup
    asyncio.create_task(auto_backup_task())
    
    # Jalankan ulang semua bot clone yang ada di DB
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT bot_token FROM clones") as cur:
            async for row in cur:
                asyncio.create_task(run_new_clone(row[0]))

    print("🚀 Master & Clone Bots Running...")
    
    # Gunakan master_bot (bukan 'bot' huruf kecil saja)
    await master_bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(master_bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass

