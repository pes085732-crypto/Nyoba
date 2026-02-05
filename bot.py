import asyncio, uuid, os, aiosqlite, traceback, random, string
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    BotCommand, BotCommandScopeDefault, FSInputFile, CallbackQuery)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

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

# ================= DATABASE =================
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

# ================= GLOBAL ERROR DETECTOR =================
@dp.errors()
async def error_handler(event: types.ErrorEvent):
    err_text = f"🚨 **DETEKSI ERROR OTOMATIS**\n\nJenis: `{type(event.exception).__name__}`\nDetail: `{event.exception}`\n\nTraceback:\n`{traceback.format_exc()[-500:]}`"
    try: await bot.send_message(ADMIN_ID, err_text)
    except: print(err_text)

# ================= MENU UTAMA ADMIN =================
@dp.message(CommandStart(), F.from_user.id == ADMIN_ID)
async def admin_start(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 LOG STATUS", callback_data="adm_log_view"), InlineKeyboardButton(text="📢 BROADCAST", callback_data="adm_bc_start")],
        [InlineKeyboardButton(text="📊 STATS", callback_data="adm_stats_view"), InlineKeyboardButton(text="⚙️ SETTINGS", callback_data="adm_sett_open")],
        [InlineKeyboardButton(text="❌ TUTUP", callback_data="adm_close_menu")]
    ])
    await m.answer("🔰 **ADMIN PANEL**\nSemua tombol sudah diperbaiki.", reply_markup=kb)

# ================= SETTINGS HANDLER (FIXED) =================
@dp.callback_query(F.data == "adm_sett_open")
async def open_settings(c: CallbackQuery):
    s = await get_conf()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Teks Start", callback_data="set_start_txt"), InlineKeyboardButton(text="Teks FSub", callback_data="set_fsub_txt")],
        [InlineKeyboardButton(text="Link FSub", callback_data="set_fsub_link"), InlineKeyboardButton(text="ID CH Post", callback_data="set_post_ch_id")],
        [InlineKeyboardButton(text="ID CH DB", callback_data="set_db_ch_id"), InlineKeyboardButton(text="Username FSub", callback_data="set_fsub_list")],
        [InlineKeyboardButton(text="🔙 KEMBALI", callback_data="adm_back_home")]
    ])
    await c.message.edit_text(f"⚙️ **SETTINGS**\nPost: `{s['post_ch_id']}`\nDB: `{s['db_ch_id']}`", reply_markup=kb)

@dp.callback_query(F.data.startswith("set_"))
async def config_input(c: CallbackQuery, state: FSMContext):
    field = c.data.replace("set_", "")
    await state.update_data(field=field)
    await state.set_state(BotState.set_val)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ BATAL", callback_data="adm_sett_open")]])
    await c.message.edit_text(f"Kirim data baru untuk `{field}`:", reply_markup=kb)

@dp.message(BotState.set_val)
async def save_config(m: Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect("master.db") as db:
        await db.execute(f"UPDATE settings SET {data['field']}=? WHERE id=1", (m.text,))
        await db.commit()
    await m.answer(f"✅ Berhasil simpan {data['field']}")
    await state.clear()
    # Kembali ke menu utama
    await admin_start(m)

# ================= TOMBOL LAINNYA =================
@dp.callback_query(F.data == "adm_back_home")
async def back_home(c: CallbackQuery):
    await c.message.delete()
    await admin_start(c.message)

@dp.callback_query(F.data == "adm_close_menu")
async def close_menu(c: CallbackQuery):
    await c.message.delete()

@dp.callback_query(F.data == "adm_log_view")
async def view_log(c: CallbackQuery):
    s = await get_conf()
    status = "DATABASE: OK\nPOST CH: OK" if s['post_ch_id'] and s['db_ch_id'] else "PERINGATAN: ID BELUM LENGKAP"
    await c.answer(status, show_alert=True)

# ================= LOGIKA MEMBER & COBA LAGI (SOLID) =================
@dp.message(CommandStart())
async def member_start(m: Message, code_override=None):
    s = await get_conf()
    arg = code_override if code_override else (m.text.split()[1] if len(m.text.split()) > 1 else None)
    
    if not arg:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=s['btn_donasi'], callback_data="mem_don"), InlineKeyboardButton(text=s['btn_ask'], callback_data="mem_ask")]
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
        if s['fsub_link']: kb_fsub.append([InlineKeyboardButton(text="🔗 GABUNG", url=s['fsub_link'])])
        kb_fsub.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"retry_{arg}")])
        return await m.answer(s['fsub_txt'], reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_fsub))

    # Ambil Media berdasarkan kode get_...
    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM media WHERE code=?", (arg,)) as cur: row = await cur.fetchone()
    
    if row:
        if row['mtype'] == "photo": await bot.send_photo(m.chat.id, row['fid'], caption=row['title'])
        else: await bot.send_video(m.chat.id, row['fid'], caption=row['title'])
    else:
        await m.answer("❌ Media tidak ditemukan.")

@dp.callback_query(F.data.startswith("retry_"))
async def retry_handler(c: CallbackQuery):
    code = c.data.replace("retry_", "")
    await c.message.delete()
    await member_start(c.message, code_override=code)

# ================= AUTO POST & UPLOAD =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document | F.animation), StateFilter(None))
async def handle_uploads(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ APPROVE", callback_data=f"don_app_{m.from_user.id}_{m.message_id}"),
             InlineKeyboardButton(text="❌ REJECT", callback_data=f"don_rej_{m.from_user.id}")]
        ])
        await bot.forward_message(ADMIN_ID, m.chat.id, m.message_id)
        await bot.send_message(ADMIN_ID, f"Donasi dari {m.from_user.full_name}", reply_markup=kb)
        return await m.answer("✅ Terkirim!")

    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    await state.update_data(fid=fid, mtype="photo" if m.photo else "video")
    await state.set_state(BotState.wait_title)
    await m.answer("Judul konten?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ BATAL", callback_data="adm_back_home")]]))

@dp.message(BotState.wait_title)
async def post_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(BotState.wait_cover)
    await m.answer("Kirim Foto Cover:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ BATAL", callback_data="adm_back_home")]]))

@dp.message(BotState.wait_cover, F.photo)
async def finalize_post(m: Message, state: FSMContext):
    try:
        data = await state.get_data()
        s = await get_conf()
        code = gen_code()
        
        # Backup DB Channel
        if s['db_ch_id']:
            bk = await bot.send_photo(s['db_ch_id'], m.photo[-1].file_id, caption=f"ID: {code}\nTITLE: {data['title']}")
            bk_id = bk.message_id
        
        async with aiosqlite.connect("master.db") as db:
            await db.execute("INSERT INTO media VALUES (?,?,?,?,?)", (code, data['fid'], data['mtype'], data['title'], str(bk_id)))
            await db.commit()

        if s['post_ch_id']:
            link = f"https://t.me/{BOT_USN}?start={code}"
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s['btn_nonton'], url=link)]])
            await bot.send_photo(s['post_ch_id'], m.photo[-1].file_id, caption=data['title'], reply_markup=kb)
            await m.answer(f"✅ BERHASIL!\nLink: `{link}`")
        else:
            await m.answer("❌ Gagal post: CH ID Kosong.")
    finally: await state.clear()

# ================= RUN =================
async def main():
    await init_db()
    await bot.set_my_commands([BotCommand(command="start", description="Mulai Bot")])
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
