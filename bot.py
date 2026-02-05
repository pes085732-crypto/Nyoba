import asyncio, os, uuid, datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiosqlite

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))
DB = "media.db"

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher(storage=MemoryStorage())

def is_admin(uid): 
    return uid in ADMIN_IDS

# ================= STATE =================
class AdminState(StatesGroup):
    badword = State()
    exempt = State()
    fsub = State()
    donasi = State()

# ================= DATABASE =================
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS media (code TEXT, file_id TEXT, type TEXT, caption TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        await db.commit()

async def set_setting(k,v):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",(k,v))
        await db.commit()

async def get_setting(k, default=None):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?",(k,))
        r = await cur.fetchone()
        return r[0] if r else default

# ================= START =================
@dp.message(CommandStart())
async def start(m: types.Message):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?)",(m.from_user.id,))
        await db.commit()

    text = await get_setting("start_text","👋 Selamat datang")
    kb = None
    if is_admin(m.from_user.id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ PANEL ADMIN", callback_data="admin_panel")]
        ])
    await m.answer(text, reply_markup=kb)

# ================= PANEL ADMIN =================
@dp.callback_query(F.data=="admin_panel")
async def panel(cb: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔐 Security", callback_data="sec")],
        [InlineKeyboardButton(text="📢 Force Join", callback_data="fsub")],
        [InlineKeyboardButton(text="📊 Stats", callback_data="stats")],
        [InlineKeyboardButton(text="💾 Backup DB", callback_data="backup")]
    ])
    await cb.message.edit_text("⚙️ ADMIN DASHBOARD", reply_markup=kb)

# ================= SECURITY =================
@dp.callback_query(F.data=="sec")
async def sec_panel(cb: types.CallbackQuery):
    status = await get_setting("filter_on","0")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Filter Kata: {'ON' if status=='1' else 'OFF'}", callback_data="toggle_filter")],
        [InlineKeyboardButton(text="✏️ Edit Kata Terlarang", callback_data="edit_badword")],
        [InlineKeyboardButton(text="🛡 Exempt Username", callback_data="edit_exempt")],
        [InlineKeyboardButton(text="⬅️ Kembali", callback_data="admin_panel")]
    ])
    await cb.message.edit_text("🔐 SECURITY SETTINGS", reply_markup=kb)

@dp.callback_query(F.data=="toggle_filter")
async def toggle_filter(cb: types.CallbackQuery):
    cur = await get_setting("filter_on","0")
    await set_setting("filter_on","0" if cur=="1" else "1")
    await sec_panel(cb)

@dp.callback_query(F.data=="edit_badword")
async def ask_badword(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminState.badword)
    await cb.message.edit_text("Kirim kata terlarang (pisahkan koma)")

@dp.message(AdminState.badword)
async def save_badword(m: types.Message, state: FSMContext):
    await set_setting("bad_words", m.text.lower())
    await m.answer("✅ Kata terlarang diperbarui")
    await state.clear()

@dp.callback_query(F.data=="edit_exempt")
async def ask_exempt(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminState.exempt)
    await cb.message.edit_text("Kirim username exempt (tanpa @, pisahkan koma)")

@dp.message(AdminState.exempt)
async def save_exempt(m: types.Message, state: FSMContext):
    await set_setting("exempt_users", m.text.lower())
    await m.answer("✅ Exempt disimpan")
    await state.clear()

# ================= FILTER GROUP =================
@dp.message(F.chat.type.in_(["group","supergroup"]))
async def filter_words(m: types.Message):
    if is_admin(m.from_user.id): 
        return
    if await get_setting("filter_on","0") != "1": 
        return

    bad = (await get_setting("bad_words","")).split(",")
    txt = (m.text or "").lower()
    if any(w and w in txt for w in bad):
        await m.delete()
        until = datetime.datetime.now() + datetime.timedelta(hours=24)
        await bot.restrict_chat_member(
            m.chat.id,
            m.from_user.id,
            permissions=types.ChatPermissions(can_send_messages=False),
            until_date=until
        )

# ================= SENDDB =================
@dp.message(F.content_type.in_({"photo","video","document","animation"}))
async def senddb(m: types.Message):
    if not is_admin(m.from_user.id): 
        return

    file = (
        m.photo[-1].file_id if m.photo else
        m.video.file_id if m.video else
        m.document.file_id
    )

    code = uuid.uuid4().hex[:30]
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO media VALUES (?,?,?,?)",
            (code, file, m.content_type, m.caption or "")
        )
        await db.commit()

    await m.answer(f"✅ MEDIA DISIMPAN\nCODE: <code>{code}</code>")

# ================= STATS =================
@dp.callback_query(F.data=="stats")
async def stats(cb: types.CallbackQuery):
    async with aiosqlite.connect(DB) as db:
        u = await db.execute("SELECT COUNT(*) FROM users")
        m = await db.execute("SELECT COUNT(*) FROM media")
        users = (await u.fetchone())[0]
        media = (await m.fetchone())[0]

    await cb.message.edit_text(f"📊 USERS: {users}\n📁 MEDIA: {media}")

# ================= BACKUP =================
@dp.callback_query(F.data=="backup")
async def backup(cb: types.CallbackQuery):
    await cb.message.answer_document(types.FSInputFile(DB))

# ================= FORCE JOIN =================
@dp.callback_query(F.data=="fsub")
async def fsub_panel(cb: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Set Channel/Group", callback_data="set_fsub")],
        [InlineKeyboardButton(text="⬅️ Kembali", callback_data="admin_panel")]
    ])
    await cb.message.edit_text("📢 FORCE SUBSCRIBE", reply_markup=kb)

@dp.callback_query(F.data=="set_fsub")
async def ask_fsub(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminState.fsub)
    await cb.message.edit_text("Kirim ID channel/grup (pisahkan koma)")

@dp.message(AdminState.fsub)
async def save_fsub(m: types.Message, state: FSMContext):
    await set_setting("fsub_ids", m.text)
    await m.answer("✅ Force join disimpan")
    await state.clear()

async def check_fsub(user_id):
    ids = (await get_setting("fsub_ids","")).split(",")
    for cid in ids:
        if not cid.strip(): 
            continue
        try:
            member = await bot.get_chat_member(int(cid), user_id)
            if member.status not in ("member","administrator","creator"):
                return False
        except:
            return False
    return True

@dp.message()
async def gate(m: types.Message):
    if m.chat.type != "private":
        return
    if await get_setting("fsub_ids"):
        if not await check_fsub(m.from_user.id):
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 COBA LAGI", callback_data="retry_fsub")]
            ])
            await m.answer("🚫 Kamu belum join semua channel", reply_markup=kb)

@dp.callback_query(F.data=="retry_fsub")
async def retry(cb: types.CallbackQuery):
    if await check_fsub(cb.from_user.id):
        await cb.message.edit_text("✅ Akses dibuka")
    else:
        await cb.answer("❌ Masih belum join", show_alert=True)

# ================= DONASI =================
@dp.message(Command("donasi"))
async def donasi(m: types.Message, state: FSMContext):
    await state.set_state(AdminState.donasi)
    await m.answer("Kirim foto/video donasi")

@dp.message(AdminState.donasi, F.content_type.in_({"photo","video"}))
async def donasi_media(m: types.Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data="approve_donasi"),
            InlineKeyboardButton(text="❌ Reject", callback_data="reject_donasi")
        ]
    ])
    await bot.copy_message(
        ADMIN_IDS[0],
        m.chat.id,
        m.message_id,
        protect_content=True,
        reply_markup=kb
    )
    await m.answer("📨 Donasi dikirim ke admin")
    await state.clear()

# ================= RUN =================
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
