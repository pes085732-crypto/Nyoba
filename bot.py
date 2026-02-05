import asyncio, os, aiosqlite, traceback, random, string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat, CallbackQuery, ChatMemberUpdated, ChatPermissions)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "ISI_TOKEN_DISINI")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0)) 
BOT_USN = os.getenv("BOT_USERNAME", "UsernameBot").replace("@", "")

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
    return f"get_{''.join(random.choices(string.ascii_letters + string.digits, k=26))}"

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
            VALUES (1, 'Halo Selamat datang', 'Join dulu ya', '🎬 NONTON', '🎁 DONASI', '💬 ASK', '', '', '', '', '', '')""")
        await db.commit()

async def get_conf():
    async with aiosqlite.connect("master.db") as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM settings WHERE id=1") as cur: return await cur.fetchone()

# ================= ANTI-KATA TERLARANG =================
@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def group_filter(m: Message):
    if not m.text: return
    s = await get_conf()
    exempt = [str(ADMIN_ID)] + (s['exempt_usn'].lower().replace("@","").split(",") if s['exempt_usn'] else [])
    if str(m.from_user.id) in exempt or (m.from_user.username and m.from_user.username.lower() in exempt): return
    if any(word in m.text.lower() for word in KATA_TERLARANG):
        try:
            await m.delete()
            await bot.restrict_chat_member(m.chat.id, m.from_user.id, permissions=ChatPermissions(can_send_messages=False), until_date=datetime.now() + timedelta(hours=24))
            await m.answer(f"🔇 {m.from_user.first_name} di-mute 24 jam.")
        except: pass

# ================= LOG JOIN/LEFT =================
@dp.chat_member()
async def member_update(update: ChatMemberUpdated):
    s = await get_conf()
    if not s['log_id']: return
    user = update.from_user
    if update.new_chat_member.status == "member":
        txt = f"🆕 **JOIN**\n👤 {user.full_name}\n🆔 `{user.id}`"
    elif update.new_chat_member.status in ["left", "kicked"]:
        txt = f"🚪 **LEFT**\n👤 {user.full_name}\n🆔 `{user.id}`"
    else: return
    try: await bot.send_message(s['log_id'], txt)
    except: pass

# ================= DASHBOARD ADMIN =================
@dp.message(Command("settings"), F.from_user.id == ADMIN_ID)
async def admin_settings(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Start Teks", callback_data="set_start_txt"), InlineKeyboardButton(text="📢 Fsub Teks", callback_data="set_fsub_txt")],
        [InlineKeyboardButton(text="🔗 Set Addlist/Link", callback_data="set_fsub_link"), InlineKeyboardButton(text="👥 Set USN Fsub", callback_data="set_fsub_list")],
        [InlineKeyboardButton(text="📁 CH Database", callback_data="set_db_ch_id"), InlineKeyboardButton(text="📣 CH Post", callback_data="set_post_ch_id")],
        [InlineKeyboardButton(text="📜 Log Channel", callback_data="set_log_id"), InlineKeyboardButton(text="🛡 Exempt", callback_data="set_exempt_usn")],
        [InlineKeyboardButton(text="❌ TUTUP", callback_data="adm_exit")]
    ])
    await m.answer("⚙️ **ADMIN SETTINGS**", reply_markup=kb)

@dp.callback_query(F.data.startswith("set_"))
async def config_trigger(c: CallbackQuery, state: FSMContext):
    field = c.data.replace("set_", "")
    await state.update_data(field=field)
    await state.set_state(BotState.set_val)
    await c.message.edit_text(f"Kirim data baru untuk `{field}`:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ BATAL", callback_data="adm_exit")]]))

@dp.message(BotState.set_val)
async def config_saver(m: Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect("master.db") as db:
        await db.execute(f"UPDATE settings SET {data['field']}=? WHERE id=1", (m.text,))
        await db.commit()
    await m.answer(f"✅ `{data['field']}` updated!")
    await state.clear()

@dp.callback_query(F.data == "adm_exit")
async def adm_exit(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.delete()

# ================= AUTO UPLOAD & POST =================
# ================= AUTO UPLOAD (ADMIN) & DONASI (MEMBER) =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document | F.animation))
async def handle_incoming_media(m: Message, state: FSMContext):
    # CEK JIKA YANG KIRIM ADALAH ADMIN
    if m.from_user.id == ADMIN_ID:
        current_state = await state.get_state()
        
        # Jika Admin sedang di tengah proses upload (Menunggu Cover)
        if current_state == BotState.wait_cover:
            if not m.photo:
                return await m.answer("❌ Mohon kirimkan FOTO untuk cover!")
            
            data = await state.get_data()
            s = await get_conf()
            code = gen_code()
            
            try:
                # 1. Backup ke Channel DB
                bk = await bot.send_photo(s['db_ch_id'], data['fid'], caption=f"ID: `{code}`\nTITLE: {data['title']}")
                
                # 2. Simpan ke SQLite
                async with aiosqlite.connect("master.db") as db:
                    await db.execute("INSERT INTO media VALUES (?,?,?,?,?)", 
                                   (code, data['fid'], data['mtype'], data['title'], str(bk.message_id)))
                    await db.commit()
                
                # 3. Post ke Channel Utama
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s['btn_nonton'], url=f"https://t.me/{emsamasamaenak_bot}?start={code}")]])
                await bot.send_photo(s['post_ch_id'], m.photo[-1].file_id, caption=data['title'], reply_markup=kb)
                
                await m.answer(f"✅ **BERHASIL DIPOST!**\nLink: ` https://t.me/{emsamasamaenak_bot}?start={code} `")
                await state.clear()
            except Exception as e:
                await m.answer(f"❌ Gagal Post! Pastikan ID Channel Benar.\nError: {e}")
                await state.clear()
            return

        # Jika Admin baru pertama kali kirim media (Mulai Upload)
        fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
        mtype = "photo" if m.photo else "video"
        
        await state.update_data(fid=fid, mtype=mtype)
        await state.set_state(BotState.wait_title) # Set ke nunggu judul
        return await m.answer("🏷️ **JUDUL:**\nKetik judul untuk konten ini:", 
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ BATAL", callback_data="adm_exit")]]))

    # JIKA YANG KIRIM ADALAH MEMBER (DONASI)
    else:
        # Kirim ke Admin
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ APPROVE", callback_data=f"don_app_{m.from_user.id}_{m.message_id}"),
             InlineKeyboardButton(text="❌ REJECT", callback_data="adm_exit")]
        ])
        await bot.forward_message(ADMIN_ID, m.chat.id, m.message_id)
        await bot.send_message(ADMIN_ID, f"🎁 **DONASI BARU**\nDari: {m.from_user.full_name}\nID: `{m.from_user.id}`", reply_markup=kb)
        await m.answer("✅ Media donasi kamu sudah terkirim ke admin. Terima kasih!")

# Handler khusus untuk teks Judul agar tidak bentrok
@dp.message(BotState.wait_title)
async def process_title(m: Message, state: FSMContext):
    if not m.text:
        return await m.answer("❌ Kirimkan teks untuk judul!")
    
    await state.update_data(title=m.text)
    await state.set_state(BotState.wait_cover) # Pindah ke nunggu cover
    await m.answer("📸 **COVER:**\nSekarang kirimkan **FOTO** untuk cover/postingan di channel:", 
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ BATAL", callback_data="adm_exit")]]))

# ================= MEMBER LOGIC =================
@dp.message(CommandStart())
async def start_handler(m: Message, code_override=None):
    s = await get_conf()
    arg = code_override if code_override else (m.text.split()[1] if len(m.text.split()) > 1 else None)
    
    # Simpan user baru
    async with aiosqlite.connect("master.db") as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?,?)", (m.from_user.id, m.from_user.full_name))
        await db.commit()

    if arg:
        must_join = False
        if s['fsub_list']:
            for ch in s['fsub_list'].replace("@","").split(","):
                if not ch.strip(): continue
                try:
                    mem = await bot.get_chat_member(f"@{ch.strip()}", m.from_user.id)
                    if mem.status not in ["member", "administrator", "creator"]: must_join = True; break
                except: pass
        
        if must_join:
            kb = []
            if s['fsub_link']: kb.append([InlineKeyboardButton(text="🔗 JOIN CHANNEL", url=s['fsub_link'])])
            kb.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"retry_{arg}")])
            return await m.answer(s['fsub_txt'], reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

        async with aiosqlite.connect("master.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM media WHERE code=?", (arg,)) as cur: row = await cur.fetchone()
        
        if row:
            if row['mtype'] == "photo": await bot.send_photo(m.chat.id, row['fid'], caption=row['title'])
            else: await bot.send_video(m.chat.id, row['fid'], caption=row['title'])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s['btn_donasi'], callback_data="don"), InlineKeyboardButton(text=s['btn_ask'], callback_data="ask")]])
        await m.answer(s['start_txt'], reply_markup=kb)

@dp.callback_query(F.data.startswith("retry_"))
async def retry_cb(c: CallbackQuery):
    code = c.data.replace("retry_", "")
    await c.message.delete()
    await start_handler(c.message, code_override=code)

# ================= ADMIN CMDS =================
@dp.message(Command("stats"), F.from_user.id == ADMIN_ID)
async def stats_cmd(m: Message):
    async with aiosqlite.connect("master.db") as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1: u = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM media") as c2: d = (await c2.fetchone())[0]
    await m.answer(f"📊 Stats:\nUser: {u}\nMedia: {d}")

@dp.message(Command("senddb"), F.from_user.id == ADMIN_ID)
async def db_cmd(m: Message): await m.answer_document(types.FSInputFile("master.db"))

# ================= RUN =================
async def main():
    await init_db()
    # Member hanya lihat /start
    await bot.set_my_commands([BotCommand(command="start", description="Mulai")], scope=BotCommandScopeDefault())
    # Admin lihat menu lengkap
    await bot.set_my_commands([
        BotCommand(command="start", description="Mulai"),
        BotCommand(command="settings", description="Settings"),
        BotCommand(command="stats", description="Stats"),
        BotCommand(command="senddb", description="Backup DB")
    ], scope=BotCommandScopeChat(chat_id=ADMIN_ID))
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


