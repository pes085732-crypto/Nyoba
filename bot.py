import asyncio, uuid, os, aiosqlite, traceback, random, string
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    BotCommand, BotCommandScopeDefault, FSInputFile, CallbackQuery)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_USN = os.getenv("BOT_USERNAME", "").replace("@", "")

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class BotState(StatesGroup):
    wait_title = State()
    wait_cover = State()
    wait_ask = State()
    wait_reject_reason = State()
    wait_broadcast = State()
    set_val = State()

def gen_code():
    char = ''.join(random.choices(string.ascii_letters + string.digits, k=30))
    return f"get_{char}"

# ================= DATABASE & INIT =================
async def init_db():
    async with aiosqlite.connect("master.db") as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, fid TEXT, mtype TEXT, title TEXT, bk_id TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (uid INTEGER PRIMARY KEY)")
        await db.execute("""CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY, start_txt TEXT, fsub_txt TEXT, 
            btn_nonton TEXT, btn_donasi TEXT, btn_ask TEXT,
            fsub_list TEXT, fsub_link TEXT, db_ch_id TEXT, post_ch_id TEXT, 
            log_id TEXT, exempt_usn TEXT)""")
        await db.execute("""INSERT OR IGNORE INTO settings 
            (id, start_txt, fsub_txt, btn_nonton, btn_donasi, btn_ask, fsub_list, fsub_link, db_ch_id, post_ch_id, log_id, exempt_usn) 
            VALUES (1, 'Halo Selamat datang', 'Join dulu ya', 'NONTON', 'DONASI', 'TANYA ADMIN', '', '', '', '', '', '')""")
        await db.commit()

async def get_conf():
    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings WHERE id=1") as cur: return await cur.fetchone()

# ================= ADMIN MENU =================
@dp.message(CommandStart(), F.from_user.id == ADMIN_ID)
async def admin_start(m: Message):
    # Simpan user admin ke DB
    async with aiosqlite.connect("master.db") as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
        await db.commit()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 LOG STATUS", callback_data="adm_log"), InlineKeyboardButton(text="📢 BROADCAST", callback_data="adm_bc")],
        [InlineKeyboardButton(text="📊 STATS", callback_data="conf_stats"), InlineKeyboardButton(text="⚙️ SETTINGS", callback_data="adm_sett")],
        [InlineKeyboardButton(text="❌ TUTUP", callback_data="conf_close")]
    ])
    await m.answer("🔰 **ADMIN PANEL**\nGunakan tombol di bawah untuk kontrol bot:", reply_markup=kb)

@dp.callback_query(F.data == "adm_sett")
async def open_settings(c: CallbackQuery):
    s = await get_conf()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Teks Start", callback_data="conf_start_txt"), InlineKeyboardButton(text="Teks FSub", callback_data="conf_fsub_txt")],
        [InlineKeyboardButton(text="Link FSub", callback_data="conf_fsub_link"), InlineKeyboardButton(text="ID CH Post", callback_data="conf_post_ch_id")],
        [InlineKeyboardButton(text="ID CH DB", callback_data="conf_db_ch_id"), InlineKeyboardButton(text="Username FSub", callback_data="conf_fsub_list")],
        [InlineKeyboardButton(text="🔙 KEMBALI", callback_data="adm_cancel")]
    ])
    await c.message.edit_text(f"⚙️ **SETTINGS**\nPost ID: `{s['post_ch_id']}`\nDB ID: `{s['db_ch_id']}`", reply_markup=kb)

@dp.callback_query(F.data == "adm_cancel")
async def cancel_action(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await admin_start(c.message)
    await c.answer("Dibatalkan")

# ================= LOGIKA MEMBER (FIXED) =================
@dp.message(CommandStart())
async def member_start(m: Message, code_override=None):
    # Simpan User ke Database
    async with aiosqlite.connect("master.db") as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
        await db.commit()

    s = await get_conf()
    # Ambil argumen start (get_...)
    arg = code_override if code_override else (m.text.split()[1] if len(m.text.split()) > 1 else None)
    
    if not arg:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=s['btn_donasi'], callback_data="mem_don"), 
             InlineKeyboardButton(text=s['btn_ask'], callback_data="mem_ask")]
        ])
        return await m.answer(s['start_txt'], reply_markup=kb)

    # Cek Force Join
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
        kb_fsub = []
        if s['fsub_link']: kb_fsub.append([InlineKeyboardButton(text="🔗 GABUNG SEKARANG", url=s['fsub_link'])])
        # Link start= di tombol COBA LAGI
        kb_fsub.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"retry_{arg}")])
        return await m.answer(s['fsub_txt'], reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_fsub))

    # Bot "Mengingat" media berdasarkan kode
    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM media WHERE code=?", (arg,)) as cur: row = await cur.fetchone()
    
    if row:
        try:
            if row['mtype'] == "photo": await bot.send_photo(m.chat.id, row['fid'], caption=row['title'])
            else: await bot.send_video(m.chat.id, row['fid'], caption=row['title'])
        except Exception as e:
            await bot.send_message(ADMIN_ID, f"🚨 **ERROR KIRIM MEDIA**\nID mungkin expired, bot akan mencoba ambil dari DB Channel.")
            # Fitur Recovery: Jika file_id expired, ambil dari DB Channel (Opsional dev)
    else:
        await m.answer("❌ Maaf, konten tidak ditemukan di database.")

@dp.callback_query(F.data.startswith("retry_"))
async def retry_callback(c: CallbackQuery):
    code = c.data.split("_", 1)[1] # Mengambil 'get_30char'
    await c.message.delete()
    # Memicu ulang fungsi start dengan kode yang sama
    await member_start(c.message, code_override=code)
    await c.answer()

# ================= AUTO POST & DB BACKUP =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document | F.animation), StateFilter(None))
async def handle_uploads(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ APPROVE", callback_data=f"don_app_{m.from_user.id}_{m.message_id}"),
             InlineKeyboardButton(text="❌ REJECT", callback_data=f"don_rej_{m.from_user.id}")]
        ])
        await bot.forward_message(ADMIN_ID, m.chat.id, m.message_id)
        await bot.send_message(ADMIN_ID, f"🎁 **DONASI BARU**\nDari: {m.from_user.full_name}", reply_markup=kb)
        return await m.answer("✅ Terkirim ke Admin!")

    # Admin Mode: Proses Posting
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    await state.update_data(fid=fid, mtype="photo" if m.photo else "video")
    await state.set_state(BotState.wait_title)
    await m.reply("🏷 **JUDUL:**\nMasukkan judul postingan (atau klik BATAL)", 
                 reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ BATAL", callback_data="adm_cancel")]]))

@dp.message(BotState.wait_title)
async def get_post_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(BotState.wait_cover)
    await m.answer("📸 **COVER:**\nKirim foto cover untuk di Channel:",
                 reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ BATAL", callback_data="adm_cancel")]]))

@dp.message(BotState.wait_cover, F.photo)
async def finalize_post_system(m: Message, state: FSMContext):
    try:
        data = await state.get_data()
        s = await get_conf()
        code_penanda = gen_code() # start=get_30char
        
        # 1. Simpan ke Database
        async with aiosqlite.connect("master.db") as db:
            await db.execute("INSERT INTO media VALUES (?,?,?,?,?)", 
                           (code_penanda, data['fid'], data['mtype'], data['title'], "pending"))
            await db.commit()

        # 2. Backup ke DB Channel (Bot Mengingat)
        bk_id = ""
        if s['db_ch_id']:
            bk = await bot.send_photo(s['db_ch_id'], m.photo[-1].file_id, 
                                     caption=f"📂 **BACKUP DATA**\n\nCODE: `{code_penanda}`\nTITLE: {data['title']}")
            bk_id = str(bk.message_id)
            # Update ID backup di DB
            async with aiosqlite.connect("master.db") as db:
                await db.execute("UPDATE media SET bk_id=? WHERE code=?", (bk_id, code_penanda))
                await db.commit()

        # 3. Kirim ke Post Channel (Tombol Nonton Fix)
        if s['post_ch_id']:
            link_start = f"https://t.me/{BOT_USN}?start={code_penanda}"
            kb_nonton = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s['btn_nonton'], url=link_start)]])
            await bot.send_photo(s['post_ch_id'], m.photo[-1].file_id, caption=data['title'], reply_markup=kb_nonton)
            await m.answer(f"✅ **BERHASIL POST!**\nLink: `{link_start}`")
        else:
            await m.answer("❌ Gagal Post: ID Channel Post belum di-set!")

    except Exception:
        err = traceback.format_exc()
        await bot.send_message(ADMIN_ID, f"🚨 **SISTEM ERROR (Finalize)**\n\n`{err}`")
    finally:
        await state.clear()

# ================= BROADCAST =================
@dp.callback_query(F.data == "adm_bc")
async def start_bc(c: CallbackQuery, state: FSMContext):
    await state.set_state(BotState.wait_broadcast)
    await c.message.answer("📝 Kirim pesan yang ingin di-broadcast (Teks/Foto/Video):", 
                          reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ BATAL", callback_data="adm_cancel")]]))

@dp.message(BotState.wait_broadcast)
async def process_broadcast(m: Message, state: FSMContext):
    async with aiosqlite.connect("master.db") as db:
        async with db.execute("SELECT uid FROM users") as cur:
            users = await cur.fetchall()
    
    count = 0
    await m.answer(f"⏳ Memulai broadcast ke {len(users)} user...")
    for u in users:
        try:
            await bot.copy_message(u[0], m.chat.id, m.message_id)
            count += 1
            await asyncio.sleep(0.05)
        except: pass
    
    await m.answer(f"✅ Broadcast selesai! Terkirim ke {count} user.")
    await state.clear()

# ================= RUN =================
async def main():
    await init_db()
    await bot.set_my_commands([
        BotCommand(command="start", description="Mulai Bot"),
        BotCommand(command="settings", description="Admin Settings")
    ])
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
