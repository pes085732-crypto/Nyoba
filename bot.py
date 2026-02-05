import asyncio
import logging
import sqlite3
import uuid

from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import *
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
#================= RAILWAY ENV =================

BOT_TOKEN = os.getenv
ADMIN_IDS = int(os.getenv)

#================= INIT =================

logging.basicConfig(level=logging.INFO) bot = Bot(BOT_TOKEN, parse_mode="HTML") dp = Dispatcher()

#================= DATABASE =================

db = sqlite3.connect("bot.db") c = db.cursor()

c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)") c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, first_seen TEXT)") c.execute(""" CREATE TABLE IF NOT EXISTS media ( code TEXT PRIMARY KEY, file_id TEXT, type TEXT, caption TEXT, backup_msg INTEGER, created TEXT ) """)

db.commit()

#================= HELPERS =================

def get(key, default=None): r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone() return r[0] if r else default

def setv(key, val): c.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key,str(val))) db.commit()

def gen_code(): return uuid.uuid4().hex[:8]

async def is_admin(uid): return uid in ADMIN_IDS

#================= PANEL ADMIN =================

@dp.message(Command("settings")) async def panel(msg:Message): if msg.from_user.id not in ADMIN_IDS: return kb = InlineKeyboardMarkup(inline_keyboard=[ [InlineKeyboardButton(text="📢 Set Channel Post", callback_data="set:post")], [InlineKeyboardButton(text="📦 Set Channel DB", callback_data="set:db")], [InlineKeyboardButton(text="🔒 Add FSUB", callback_data="set:fsub")], [InlineKeyboardButton(text="✏️ Set Teks Start", callback_data="set:start")], [InlineKeyboardButton(text="🔘 Set Teks Tombol", callback_data="set:btn")], ]) await msg.answer("⚙️ PANEL ADMIN", reply_markup=kb)

class SetState(StatesGroup): wait = State()

@dp.callback_query(F.data.startswith("set:")) async def set_cb(cb:CallbackQuery,state:FSMContext): await state.set_state(SetState.wait) await state.update_data(key=cb.data.split(":")[1]) await cb.message.edit_text("Kirim ID / teks sekarang")

@dp.message(SetState.wait) async def save(msg:Message,state:FSMContext): d=await state.get_data() if d['key']=="fsub": old=get("fsub","") setv("fsub", old+","+msg.text if old else msg.text) else: setv(d['key'], msg.text) await msg.answer("✅ Disimpan") await state.clear()

#================= FORCE SUB =================

async def check_fsub(uid): fsub=get("fsub","") if not fsub: return True for ch in fsub.split(','): try: m=await bot.get_chat_member(int(ch), uid) if m.status not in [ChatMemberStatus.MEMBER,ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.OWNER]: return False except: return False return True

#================= START =================

@dp.message(CommandStart()) async def start(msg:Message): c.execute("INSERT OR IGNORE INTO users VALUES (?,?)", (msg.from_user.id, datetime.now().isoformat())) db.commit() args=msg.text.split() if len(args)>1: code=args[1] if not await check_fsub(msg.from_user.id): kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 COBA LAGI",callback_data=f"retry:{code}")]]) await msg.answer("⚠️ Wajib join semua channel dulu",reply_markup=kb) return r=c.execute("SELECT file_id,type,caption FROM media WHERE code=?",(code,)).fetchone() if not r: return await msg.answer("Konten tidak ada") if r[1]=="video": await bot.send_video(msg.chat.id,r[0],caption=r[2]) else: await bot.send_photo(msg.chat.id,r[0],caption=r[2]) else: await msg.answer(get("start","Selamat datang 👋"))

@dp.callback_query(F.data.startswith("retry:")) async def retry(cb:CallbackQuery): code=cb.data.split(":")[1] if not await check_fsub(cb.from_user.id): return await cb.answer("Belum join",True) await cb.message.delete() await start(cb.message)

#================= FILTER KATA =================

BAD_WORDS=["biyo","biyoh","promosi","bio"]

@dp.message(F.text, F.chat.type.in_({ChatType.GROUP,ChatType.SUPERGROUP})) async def filter_word(msg:Message): if msg.from_user.id in ADMIN_IDS: return for w in BAD_WORDS: if w in msg.text.lower(): try: await msg.delete() await bot.restrict_chat_member(msg.chat.id,msg.from_user.id, until_date=datetime.now()+timedelta(hours=24)) except: pass

#================= AUTO UPLOAD ADMIN =================

class Upload(StatesGroup): title=State(); cover=State()

@dp.message(F.video|F.photo) async def auto_upload(msg:Message,state:FSMContext): if msg.from_user.id not in ADMIN_IDS: return await state.update_data(media=msg) await state.set_state(Upload.title) await msg.answer("Judulnya apa?")

@dp.message(Upload.title) async def up_title(msg:Message,state:FSMContext): await state.update_data(title=msg.text) await state.set_state(Upload.cover) await msg.answer("Kirim cover")

@dp.message(Upload.cover,F.photo) async def up_finish(msg:Message,state:FSMContext): d=await state.get_data(); m=d['media']; code=gen_code() t="video" if m.video else "photo" fid=m.video.file_id if m.video else m.photo[-1].file_id db_ch=int(get("db")) fwd=await bot.forward_message(db_ch,m.chat.id,m.message_id) c.execute("INSERT INTO media VALUES (?,?,?,?,?,?)", (code,fid,t,d['title'],fwd.message_id,datetime.now().isoformat())) db.commit() btn=get("btn","🎬 NONTON") kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn,url=f"https://t.me/{(await bot.me()).username}?start={code}")]]) await bot.send_photo(int(get("post")),msg.photo[-1].file_id,caption=d['title'],reply_markup=kb) await msg.answer("✅ Auto post sukses") await state.clear()

#================= DONASI =================

class Donate(StatesGroup): media=State()

@dp.message(Command("donasi")) async def donasi(msg:Message,state:FSMContext): await state.set_state(Donate.media) await msg.answer("Kirim media donasi")

@dp.message(Donate.media,F.video|F.photo) async def don_recv(msg:Message,state:FSMContext): for admin in ADMIN_IDS: kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Approve",callback_data=f"approve:{msg.chat.id}:{msg.message_id}")]]) await bot.send_message(admin,"Donasi baru",reply_markup=kb) await state.clear()

@dp.callback_query(F.data.startswith("approve:")) async def approve(cb:CallbackQuery): cid,mid=cb.data.split(":")[1:] m=await bot.forward_message(cb.from_user.id,int(cid),int(mid)) await cb.answer("Approved")

#================= ASK ADMIN =================

@dp.message(Command("ask")) async def ask(msg:Message,state:FSMContext): await state.set_state(SetState.wait) await msg.answer("Tulis pesan")

@dp.message(SetState.wait) async def ask_send(msg:Message,state:FSMContext): for a in ADMIN_IDS: await bot.send_message(a,f"❓ {msg.from_user.id}:\n{msg.text}") await msg.answer("Terkirim") await state.clear()

#================= STATS & BACKUP =================

@dp.message(Command("stats")) async def stats(msg:Message): if msg.from_user.id not in ADMIN_IDS: return u=c.execute("SELECT COUNT() FROM users").fetchone()[0] m=c.execute("SELECT COUNT() FROM media").fetchone()[0] await msg.answer(f"👤 User: {u}\n📦 Media: {m}")

@dp.message(Command("senddb")) async def senddb(msg:Message): if msg.from_user.id not in ADMIN_IDS: return await msg.answer_document(open("bot.db","rb"))

#================= JOIN/LEAVE LOG =================

@dp.chat_member() async def log(update:ChatMemberUpdated): lg=get("log") if not lg: return if update.new_chat_member.status==ChatMemberStatus.MEMBER: await bot.send_message(int(lg),f"➕ {update.from_user.id} join") if update.new_chat_member.status==ChatMemberStatus.LEFT: await bot.send_message(int(lg),f"➖ {update.from_user.id} left")

#================= RUN =================

async def main(): await dp.start_polling(bot)

if name=='main': asyncio.run(main())




