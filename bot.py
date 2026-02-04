import asyncio, uuid, os, aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeDefault, BotCommandScopeChat, FSInputFile, CallbackQuery, ChatMemberUpdated, ChatPermissions
from aiogram.filters import CommandStart, Command, StateFilter, ChatMemberUpdatedFilter, IS_MEMBER, LEFT
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= KONFIGURASI & STATE =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
LOG_GROUP_ID = int(os.getenv("LOG_GROUP_ID"))
CH1 = os.getenv("CH1_USERNAME")
CH2 = os.getenv("CH2_USERNAME")
GRUP = os.getenv("GROUP_USERNAME")
BOT_USN = os.getenv("BOT_USERNAME")
EXEMPT = os.getenv("EXEMPT_USERNAME", "").lower()

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
KATA_KOTOR = ["biyo", "promosi", "bio", "byoh", "biyoh"]

class BotState(StatesGroup):
    waiting_for_title = State()
    waiting_for_cover = State()
    temp_media = State()
    edit_start_text = State()
    edit_fsub_text = State()

# ================= DATABASE SYSTEM =================
async def init_db():
    async with aiosqlite.connect("media.db") as db:
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT PRIMARY KEY, fid TEXT, type TEXT, title TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (uid INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, start_txt TEXT, fsub_txt TEXT, btn_txt TEXT)")
        # Default Settings
        await db.execute("INSERT OR IGNORE INTO settings (id, start_txt, fsub_txt, btn_txt) VALUES (1, 'Halo! Selamat datang.', 'Silakan join channel kami dulu:', '🎬 NONTON SEKARANG')")
        await db.commit()

async def get_settings():
    async with aiosqlite.connect("media.db") as db:
        async with db.execute("SELECT start_txt, fsub_txt, btn_txt FROM settings WHERE id=1") as cur:
            return await cur.fetchone()

# ================= MIDDLEWARE / HELPERS =================
async def check_fsub(uid):
    res = []
    for c in [CH1, CH2, GRUP]:
        if not c: continue
        try:
            m = await bot.get_chat_member(f"@{c}", uid)
            res.append(m.status in ("member", "administrator", "creator"))
        except: res.append(False)
    return res

# ================= LOG MEMBER & FILTER =================
@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_MEMBER))
async def join_log(event: ChatMemberUpdated):
    u = event.new_chat_member.user
    await bot.send_message(LOG_GROUP_ID, f"✅ **JOIN**\nName: {u.full_name}\nID: `{u.id}`\nUsn: @{u.username}")

@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=LEFT))
async def left_log(event: ChatMemberUpdated):
    u = event.old_chat_member.user
    await bot.send_message(LOG_GROUP_ID, f"❌ **LEAVE**\nName: {u.full_name}\nID: `{u.id}`")

@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def word_filter(m: Message):
    if m.from_user.id == ADMIN_ID or (m.from_user.username and m.from_user.username.lower() == EXEMPT): return
    if any(k in m.text.lower() for k in KATA_KOTOR):
        try:
            await m.delete()
            await bot.restrict_chat_member(m.chat.id, m.from_user.id, ChatPermissions(can_send_messages=False), until_date=datetime.now()+timedelta(hours=24))
            await m.answer(f"🚫 {m.from_user.first_name} Muted 24h (Bad Word)")
        except: pass

# ================= ADMIN DASHBOARD (INLINE) =================
@dp.message(Command("settings"), F.from_user.id == ADMIN_ID)
async def open_settings(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Set Teks Start", callback_data="set_start"), InlineKeyboardButton(text="📢 Set Teks Fsub", callback_data="set_fsub")],
        [InlineKeyboardButton(text="📊 Stats DB", callback_data="stats_db"), InlineKeyboardButton(text="📁 Send DB", callback_data="send_db")]
    ])
    await m.answer("⚙️ **Bot Dashboard Admin**\nSilakan pilih menu di bawah:", reply_markup=kb)

@dp.callback_query(F.data == "stats_db")
async def cb_stats(c: CallbackQuery):
    async with aiosqlite.connect("media.db") as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1: u = await c1.fetchone()
        async with db.execute("SELECT COUNT(*) FROM media") as c2: m = await c2.fetchone()
    await c.answer(f"User: {u[0]} | Media: {m[0]}", show_alert=True)

@dp.callback_query(F.data == "send_db")
async def cb_senddb(c: CallbackQuery):
    await c.message.answer_document(FSInputFile("media.db"))
    await c.answer()

# ================= AUTO POST SYSTEM =================
@dp.message(F.chat.type == "private", (F.photo | F.video | F.document), StateFilter(None))
async def trigger_upload(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        # Donasi System
        await bot.send_message(LOG_GROUP_ID, f"🎁 **Donasi Masuk** dari {m.from_user.full_name}")
        await bot.forward_message(ADMIN_ID, m.chat.id, m.message_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Approve", callback_data="app_donasi")]])
        await bot.send_message(ADMIN_ID, "Donasi baru diterima:", reply_markup=kb)
        return await m.reply("✅ Konten dikirim ke admin!")

    # Admin Upload
    fid = m.photo[-1].file_id if m.photo else (m.video.file_id if m.video else m.document.file_id)
    await state.update_data(fid=fid, type="photo" if m.photo else "video")
    await state.set_state(BotState.waiting_for_title)
    await m.reply("🏷️ **Judulnya apa?**")

@dp.callback_query(F.data == "app_donasi")
async def app_donasi(c: CallbackQuery, state: FSMContext):
    await state.set_state(BotState.waiting_for_title)
    await c.message.answer("🏷️ Masukkan Judul Postingan:")
    await c.answer()

@dp.message(BotState.waiting_for_title)
async def get_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text)
    await state.set_state(BotState.waiting_for_cover)
    await m.answer("📸 **Kirim Foto Cover/Posternya:**")

@dp.message(BotState.waiting_for_cover, F.photo)
async def finalize_post(m: Message, state: FSMContext):
    data = await state.get_data()
    code = uuid.uuid4().hex[:8]
    sets = await get_settings()
    
    async with aiosqlite.connect("media.db") as db:
        await db.execute("INSERT INTO media VALUES (?,?,?,?)", (code, data['fid'], data['type'], data['title']))
        await db.commit()
    
    link = f"https://t.me/{BOT_USN}?start={code}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=sets[2], url=link)]])
    
    # Post to Channel 2
    await bot.send_photo(f"@{CH2}", m.photo[-1].file_id, caption=f"🔥 **{data['title']}**", reply_markup=kb)
    await m.answer(f"✅ **BERHASIL!**\nLink: `{link}`")
    await state.clear()

# ================= MEMBER INTERACTION =================
@dp.message(Command("ask"))
async def ask_admin(m: Message):
    txt = m.text.split(maxsplit=1)
    if len(txt) < 2: return await m.reply("Format: `/ask pesan kamu`")
    await bot.send_message(ADMIN_ID, f"📩 **ASK** dari {m.from_user.full_name} (`{m.from_user.id}`):\n{txt[1]}")
    await m.reply("✅ Terkirim ke admin.")

@dp.message(CommandStart())
async def start_handler(m: Message, code_override=None):
    uid = m.from_user.id
    async with aiosqlite.connect("media.db") as db:
        await db.execute("INSERT OR IGNORE INTO users (uid) VALUES (?)", (uid,))
        await db.commit()
    
    sets = await get_settings()
    arg = m.text.split()[1] if len(m.text.split()) > 1 else code_override
    
    if not arg: return await m.answer(sets[0])

    fsub = await check_fsub(uid)
    if not all(fsub):
        kb = []
        for i, (s, c) in enumerate(zip(fsub, [CH1, CH2, GRUP])):
            if not s and c: kb.append([InlineKeyboardButton(text=f"Join Channel {i+1}", url=f"https://t.me/{c}")])
        kb.append([InlineKeyboardButton(text="🔄 COBA LAGI", callback_data=f"retry_{arg}")])
        return await m.answer(sets[1], reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    async with aiosqlite.connect("media.db") as db:
        async with db.execute("SELECT fid, type, title FROM media WHERE code=?", (arg,)) as cur:
            row = await cur.fetchone()
    if row:
        if row[1] == "photo": await bot.send_photo(m.chat.id, row[0], caption=row[2])
        else: await bot.send_video(m.chat.id, row[0], caption=row[2])

@dp.callback_query(F.data.startswith("retry_"))
async def retry(c: CallbackQuery):
    code = c.data.split("_")[1]
    await c.message.delete()
    await start_handler(c.message, code_override=code)

# ================= BOOTING =================
async def main():
    await init_db()
    await bot.set_my_commands([BotCommand(command="start", description="Mulai"), BotCommand(command="ask", description="Tanya Admin"), BotCommand(command="donasi", description="Donasi")], scope=BotCommandScopeDefault())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
