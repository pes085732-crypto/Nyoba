import asyncio, uuid, os, aiosqlite, traceback
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    BotCommand, BotCommandScopeDefault, FSInputFile, CallbackQuery, ChatPermissions)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= KONFIGURASI =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_USN = os.getenv("BOT_USERNAME", "").replace("@", "")

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
KATA_KOTOR = ["biyo", "promosi", "bio", "byoh", "biyoh"]

class BotState(StatesGroup):
    wait_title = State()
    wait_cover = State()
    wait_ask = State()
    wait_reject_reason = State()
    set_val = State()

# ================= DATABASE =================
async def init_db():
    async with aiosqlite.connect("master.db") as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, fid TEXT, mtype TEXT, title TEXT, bk_id TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (uid INTEGER PRIMARY KEY)")
        await db.execute("""CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY, start_txt TEXT, fsub_txt TEXT, 
            btn_nonton TEXT, btn_donasi TEXT, btn_ask TEXT,
            fsub_list TEXT, db_ch_id TEXT, post_ch_id TEXT, 
            log_id TEXT, exempt_usn TEXT)""")
        await db.execute("""INSERT OR IGNORE INTO settings 
            (id, start_txt, fsub_txt, btn_nonton, btn_donasi, btn_ask, fsub_list, db_ch_id, post_ch_id, log_id, exempt_usn) 
            VALUES (1, 'Selamat datang', 'Silakan bergabung ke channel kami dahulu untuk mengakses konten ini.', 'NONTON', 'DONASI', 'TANYA ADMIN', '', '', '', '', '')""")
        await db.commit()

async def get_conf():
    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings WHERE id=1") as cur: return await cur.fetchone()

# ================= ERROR REPORTING =================
async def report_error(e):
    err_msg = f"SISTEM ERROR DETECTED\n\nDetail:\n{traceback.format_exc()}"
    try: await bot.send_message(ADMIN_ID, err_msg)
    except: print(err_msg)

# ================= DASHBOARD ADMIN =================
@dp.message(Command("settings"), F.from_user.id == ADMIN_ID)
async def dashboard(m: Message):
    s = await get_conf()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Teks Start", callback_data="conf_start_txt"), InlineKeyboardButton(text="Teks FSub", callback_data="conf_fsub_txt")],
        [InlineKeyboardButton(text="Tombol Nonton", callback_data="conf_btn_nonton"), InlineKeyboardButton(text="Tombol Donasi", callback_data="conf_btn_donasi")],
        [InlineKeyboardButton(text="Tombol Ask", callback_data="conf_btn_ask"), InlineKeyboardButton(text="Daftar FSub", callback_data="conf_fsub_list")],
        [InlineKeyboardButton(text="ID Channel DB", callback_data="conf_db_ch_id"), InlineKeyboardButton(text="ID Channel Post", callback_data="conf_post_ch_id")],
        [InlineKeyboardButton(text="ID Log", callback_data="conf_log_id"), InlineKeyboardButton(text="User Exempt", callback_data="conf_exempt_usn")],
        [InlineKeyboardButton(text="STATISTIK", callback_data="conf_stats"), InlineKeyboardButton(text="BACKUP DB", callback_data="conf_dbfile")],
        [InlineKeyboardButton(text="TUTUP MENU", callback_data="conf_close")]
    ])
    await m.answer(f"ADMIN SETTINGS\n\nCH Post: {s['post_ch_id']}\nCH DB: {s['db_ch_id']}\nLog: {s['log_id']}", reply_markup=kb)

@dp.callback_query(F.data.startswith("conf_"))
async def config_cb(c: CallbackQuery, state: FSMContext):
    action = c.data.replace("conf_", "")
    if action == "close": return await c.message.delete()
    if action == "stats":
        async with aiosqlite.connect("master.db") as db:
            async with db.execute("SELECT COUNT(*) FROM users") as c1: u = await c1.fetchone()
            async with db.execute("SELECT COUNT(*) FROM media") as c2: m = await c2.fetchone()
        return await c.answer(f"User: {u[0]} | Media: {m[0]}", show_alert=True)
    if action == "dbfile": return await c.message.answer_document(FSInputFile("master.db"))

    await state.update_data(field=action)
    await state.set_state(BotState.set_val)
    await c.message.answer(f"Kirim data baru untuk {action}:")
    await c.answer()

@dp.message(BotState.set_val)
async def save_config(m: Message, state: FSMContext):
    data = await state.get_data()
    field = data['field']
    async with aiosqlite.connect("master.db") as db:
        await db.execute(f"UPDATE settings SET {field}=? WHERE id=1", (m.text,))
        await db.commit()
    await m.answer(f"Berhasil simpan {field}")
    await state.clear()

# ================= AUTO POST & DONASI =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document | F.animation), StateFilter(None))
async def upload_handler(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        await bot.forward_message(ADMIN_ID, m.chat.id, m.message_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="APPROVE", callback_data=f"don_app_{m.from_user.id}"),
             InlineKeyboardButton(text="REJECT", callback_data=f"don_rej_{m.from_user.id}")]
        ])
        await bot.send_message(ADMIN_ID, f"Donasi baru dari {m.from_user.full_name}", reply_markup=kb)
        return await m.answer("Konten sudah dikirim ke admin")

    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    await state.update_data(fid=fid, mtype="photo" if m.photo else "video")
    await state.set_state(BotState.wait_title)
    await m.reply("Judul konten apa?")

@dp.callback_query(F.data.startswith("don_"))
async def don_action(c: CallbackQuery, state: FSMContext):
    parts = c.data.split("_")
    action, uid = parts[1], parts[2]
    if action == "app":
        msg = c.message.reply_to_message
        fid = msg.photo[-1].file_id if msg.photo else (msg.video.file_id if msg.video else msg.document.file_id)
        await state.update_data(fid=fid, mtype="photo" if msg.photo else "video", sender=uid)
        await state.set_state(BotState.wait_title)
        await c.message.answer("Donasi diterima. Masukkan Judul:")
    else:
        await state.update_data(target_uid=uid)
        await state.set_state(BotState.wait_reject_reason)
        await c.message.answer("Alasan penolakan?")
    await c.answer()

@dp.message(BotState.wait_reject_reason)
async def reject_don(m: Message, state: FSMContext):
    data = await state.get_data()
    try: await bot.send_message(data['target_uid'], f"Donasi ditolak. Alasan: {m.text}")
    except: pass
    await m.answer("Ditolak.")
    await state.clear()

@dp.message(BotState.wait_title)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(BotState.wait_cover)
    await m.answer("Kirim Foto Cover:")

@dp.message(BotState.wait_cover, F.photo)
async def finalize_post(m: Message, state: FSMContext):
    try:
        data = await state.get_data()
        s = await get_conf()
        code = uuid.uuid4().hex[:8]
        bk_id = None
        if s['db_ch_id']:
            bk = await bot.send_photo(s['db_ch_id'], m.photo[-1].file_id, caption=f"KODE: {code}\nJUDUL: {data['title']}")
            bk_id = bk.message_id
        async with aiosqlite.connect("master.db") as db:
            await db.execute("INSERT INTO media VALUES (?,?,?,?,?)", (code, data['fid'], data['mtype'], data['title'], bk_id))
            await db.commit()
        link = f"https://t.me/{BOT_USN}?start={code}"
        if s['post_ch_id']:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s['btn_nonton'], url=link)]])
            await bot.send_photo(s['post_ch_id'], m.photo[-1].file_id, caption=data['title'], reply_markup=kb)
        await m.answer(f"Berhasil! Link: {link}")
    except Exception as e: await report_error(e)
    finally: await state.clear()

# ================= MEMBER AREA & FSUB LOGIC =================
@dp.message(CommandStart())
async def start_handler(m: Message, code_override=None):
    s = await get_conf()
    # Deteksi apakah dari command /start atau dari tombol coba lagi
    arg = m.text.split()[1] if (hasattr(m, 'text') and len(m.text.split()) > 1) else code_override
    
    if not arg:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=s['btn_donasi'], callback_data="mem_don"), 
             InlineKeyboardButton(text=s['btn_ask'], callback_data="mem_ask")]
        ])
        return await m.answer(s['start_txt'], reply_markup=kb)

    # Logika Force Join (Multi-Channel)
    must_join = []
    if s['fsub_list']:
        channels = [c.strip() for c in s['fsub_list'].split(",") if c.strip()]
        for ch in channels:
            try:
                # Menghapus @ jika user menginputnya
                ch_fix = ch.replace("@", "")
                mem = await bot.get_chat_member(f"@{ch_fix}", m.from_user.id)
                if mem.status not in ("member", "administrator", "creator"):
                    must_join.append(ch_fix)
            except Exception:
                # Jika bot belum admin di channel tersebut
                pass
    
    if must_join:
        btns = [[InlineKeyboardButton(text=f"JOIN CHANNEL", url=f"https://t.me/{c}")] for c in must_join]
        # Pastikan arg (kode media) disertakan dalam callback_data
        btns.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"retry_{arg}")])
        return await m.answer(s['fsub_txt'], reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

    # Ambil Media dari DB
    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM media WHERE code=?", (arg,)) as cur:
            row = await cur.fetchone()
    
    if row:
        if row['mtype'] == "photo":
            await bot.send_photo(m.chat.id, row['fid'], caption=row['title'])
        else:
            await bot.send_video(m.chat.id, row['fid'], caption=row['title'])
    else:
        await m.answer("Maaf, konten tidak ditemukan atau sudah dihapus.")

@dp.callback_query(F.data.startswith("retry_"))
async def retry_cb(c: CallbackQuery):
    # Ambil kode media dari callback data
    code = c.data.split("_")[1]
    
    # Cek status join lagi secara real-time
    s = await get_conf()
    must_join = []
    if s['fsub_list']:
        channels = [ch.strip().replace("@", "") for ch in s['fsub_list'].split(",") if ch.strip()]
        for ch in channels:
            try:
                mem = await bot.get_chat_member(f"@{ch}", c.from_user.id)
                if mem.status not in ("member", "administrator", "creator"):
                    must_join.append(ch)
            except: pass
            
    if must_join:
        # Jika masih belum join, beri peringatan (alert) tanpa kirim pesan baru
        await c.answer("Kamu belum join semua channel! Silakan join dulu.", show_alert=True)
    else:
        # Jika sudah join, hapus pesan peringatan dan panggil start_handler
        await c.answer("Terima kasih! Menyiapkan konten...", show_alert=False)
        await c.message.delete()
        # Jalankan fungsi start secara manual
        await start_handler(c, code_override=code)

@dp.callback_query(F.data == "mem_ask")
async def mem_ask(c: CallbackQuery, state: FSMContext):
    await state.set_state(BotState.wait_ask)
    await c.message.answer("Tulis pesan untuk admin:")
    await c.answer()

@dp.message(BotState.wait_ask)
async def process_ask(m: Message, state: FSMContext):
    await bot.send_message(ADMIN_ID, f"PESAN BARU: {m.from_user.full_name}\n\n{m.text}")
    await m.answer("Pesan terkirim ke admin.")
    await state.clear()

@dp.callback_query(F.data == "mem_don")
async def mem_don(c: CallbackQuery):
    await c.message.answer("Kirim foto/video donasi langsung ke sini.")
    await c.answer()

# ================= RUN =================
async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
