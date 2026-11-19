import asyncio
import html
import json
import logging
import os
from pathlib import Path
import random
import sqlite3
from contextlib import closing
from urllib.parse import quote

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("DB_PATH", "actress_game.db")
AUTO_POST_CHAT_ID = os.getenv("AUTO_POST_CHAT_ID", "").strip()
AUTO_POST_INTERVAL_MINUTES = max(1, int(os.getenv("AUTO_POST_INTERVAL_MINUTES", "15")))
AUTO_POST_ENABLED = os.getenv("AUTO_POST_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
SUPPORT_CHANNEL = os.getenv("SUPPORT_CHANNEL", "").strip()
SUPPORT_GROUP = os.getenv("SUPPORT_GROUP", "").strip()
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "").strip()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("actress-game")

# Search is limited to Wikimedia Commons and only accepts freely licensed/public-domain files.
ACTRESSES = [
    "Deepika Padukone", "Alia Bhatt", "Priyanka Chopra", "Katrina Kaif", "Kareena Kapoor",
    "Aishwarya Rai", "Anushka Sharma", "Kriti Sanon", "Kiara Advani", "Shraddha Kapoor",
    "Madhuri Dixit", "Kajol", "Rani Mukerji", "Vidya Balan", "Taapsee Pannu", "Bhumi Pednekar",
    "Disha Patani", "Sara Ali Khan", "Janhvi Kapoor", "Ananya Panday", "Parineeti Chopra",
    "Sonakshi Sinha", "Sushmita Sen", "Rekha", "Hema Malini", "Shabana Azmi", "Tabu",
    "Nayanthara", "Samantha Ruth Prabhu", "Rashmika Mandanna", "Sai Pallavi", "Tamannaah Bhatia",
    "Trisha Krishnan", "Kajal Aggarwal", "Pooja Hegde", "Rakul Preet Singh", "Keerthy Suresh",
    "Ramya Krishnan", "Manju Warrier", "Parvathy Thiruvothu", "Amala Paul", "Aparna Balamurali",
    "Mrunal Thakur", "Radhika Apte", "Yami Gautam", "Shilpa Shetty", "Bipasha Basu", "Genelia D'Souza",
    "Urvashi Rautela", "Nimrat Kaur", "Fatima Sana Shaikh", "Richa Chadda", "Huma Qureshi",
    "Ileana D'Cruz", "Lara Dutta", "Dia Mirza", "Neha Dhupia", "Mouni Roy", "Aditi Rao Hydari"
]


def db():
    return sqlite3.connect(DB_PATH, timeout=30)


def init_db():
    with closing(db()) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("""CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_id TEXT NOT NULL,
            answer TEXT NOT NULL,
            options TEXT NOT NULL,
            source TEXT DEFAULT ''
        )""")
        # Upgrade databases created by the starter version.
        cols = {r[1] for r in con.execute("PRAGMA table_info(questions)")}
        if "source" not in cols:
            con.execute("ALTER TABLE questions ADD COLUMN source TEXT DEFAULT ''")
        con.execute("""CREATE TABLE IF NOT EXISTS scores (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            points INTEGER NOT NULL DEFAULT 0
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS answered (
            question_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY(question_id, user_id)
        )""")
        con.commit()


def get_question(exclude_id=None):
    with closing(db()) as con:
        if exclude_id is None:
            row = con.execute("SELECT id, photo_id, answer, options, source FROM questions ORDER BY RANDOM() LIMIT 1").fetchone()
        else:
            row = con.execute("SELECT id, photo_id, answer, options, source FROM questions WHERE id != ? ORDER BY RANDOM() LIMIT 1", (exclude_id,)).fetchone()
            if row is None:
                row = con.execute("SELECT id, photo_id, answer, options, source FROM questions ORDER BY RANDOM() LIMIT 1").fetchone()
    if not row:
        return None
    qid, photo_id, answer, options, source = row
    try:
        parsed_options = json.loads(options)
    except (json.JSONDecodeError, TypeError):
        # Backward compatibility with the original pipe-separated database format.
        parsed_options = options.split("|")
    return {"id": qid, "photo_id": photo_id, "answer": answer, "options": parsed_options, "source": source or ""}


def question_keyboard(q):
    builder = InlineKeyboardBuilder()
    opts = q["options"][:]
    random.shuffle(opts)
    for opt in opts:
        builder.button(text=opt, callback_data=f"guess:{q['id']}:{opt}")
    builder.adjust(2)
    return builder.as_markup()


def telegram_url(value: str):
    value = (value or "").strip()
    if not value:
        return None
    if value.startswith(("https://", "http://")):
        return value
    return f"https://t.me/{value.lstrip('@')}"


def main_keyboard():
    rows = [[InlineKeyboardButton(text="🎮 Play Game", callback_data="play")],
            [InlineKeyboardButton(text="🏆 Leaderboard", callback_data="leaderboard"),
             InlineKeyboardButton(text="❓ Help", callback_data="help")]]
    links = []
    if SUPPORT_GROUP:
        links.append(InlineKeyboardButton(text="👥 Support Group", url=telegram_url(SUPPORT_GROUP)))
    if SUPPORT_CHANNEL:
        links.append(InlineKeyboardButton(text="🆘 Support", url=telegram_url(SUPPORT_CHANNEL)))
    if UPDATE_CHANNEL:
        links.append(InlineKeyboardButton(text="📢 Update Channel", url=telegram_url(UPDATE_CHANNEL)))
    if links:
        rows.extend([links[i:i+2] for i in range(0, len(links), 2)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def add_question(photo_id, answer, options, source="admin upload"):
    with closing(db()) as con:
        cur = con.execute("INSERT INTO questions(photo_id, answer, options, source) VALUES (?, ?, ?, ?)",
                          (photo_id, answer, json.dumps(options, ensure_ascii=False), source))
        con.commit()
        return cur.lastrowid


def update_score(user_id, name, qid):
    with closing(db()) as con:
        cur = con.execute("INSERT OR IGNORE INTO answered(question_id, user_id) VALUES (?, ?)", (qid, user_id))
        if cur.rowcount == 0:
            return False
        con.execute("""INSERT INTO scores(user_id, name, points) VALUES (?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, points=points+1""", (user_id, name))
        con.commit()
        return True


def leaderboard_text():
    with closing(db()) as con:
        rows = con.execute("SELECT name, points FROM scores ORDER BY points DESC, name LIMIT 10").fetchall()
    if not rows:
        return "🏆 Abhi leaderboard khaali hai. Pehla point jeetne wale aap ban sakte hain!"
    return "🏆 <b>TOP PLAYERS</b>\n\n" + "\n".join(
        f"{i}. {html.escape(name)} — <b>{points}</b> points" for i, (name, points) in enumerate(rows, 1)
    )



async def send_question(target, q, delete_old=False):
    caption = "🎭 <b>Who is this actress?</b>\n\nPhoto dekho aur sahi naam choose karo!"
    if delete_old:
        try:
            await target.delete()
        except Exception:
            pass
    await target.answer_photo(photo=q["photo_id"], caption=caption, reply_markup=question_keyboard(q), parse_mode="HTML")


async def fetch_commons_photo(session: aiohttp.ClientSession, name: str):
    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f'filetype:bitmap "{name}"',
        "gsrnamespace": 6, "gsrlimit": 20, "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 900
    }
    headers = {"User-Agent": "ActressPhotoGuessBot/1.0 (Telegram quiz bot; contact admin)"}
    async with session.get(api, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=18)) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    pages = list(data.get("query", {}).get("pages", {}).values())
    random.shuffle(pages)
    allowed = ("cc0", "public domain", "cc by", "cc-by", "cc by-sa", "cc-by-sa", "cc by 4.0", "cc by-sa 4.0")
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        license_name = (meta.get("LicenseShortName", {}).get("value", "") or "").lower()
        usage = (meta.get("UsageTerms", {}).get("value", "") or "").lower()
        if not any(x in license_name or x in usage for x in allowed):
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        title = page.get("title", "Wikimedia Commons image")
        artist = meta.get("Artist", {}).get("value", "")
        artist_text = " ".join(html.unescape(artist).split())
        license_text = meta.get("LicenseShortName", {}).get("value", "License")
        source = f"Wikimedia Commons: {title}; {artist_text}; {license_text}"[:450]
        return url, source
    return None


async def ensure_auto_question():
    # Prefer an existing admin-uploaded question; otherwise fetch one freely licensed Commons image.
    q = get_question()
    if q:
        return q
    name = random.choice(ACTRESSES)
    distractors = random.sample([x for x in ACTRESSES if x != name], 3)
    timeout = aiohttp.ClientTimeout(total=22)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        result = await fetch_commons_photo(session, name)
    if not result:
        return None
    photo_url, source = result
    qid = add_question(photo_url, name, [name] + distractors, source)
    return {"id": qid, "photo_id": photo_url, "answer": name, "options": [name] + distractors, "source": source}


async def start(message: Message, bot: Bot):
    welcome = (
        "🌟 <b>WELCOME TO ACTRESS PHOTO GUESS!</b>\n\n"
        "🎭 Actress ki photo pehchano aur 4 options mein se sahi naam chuno.\n"
        "🏆 Har sahi jawab par +1 point.\n"
        "📊 Leaderboard par apni ranking dekho.\n\n"
        "👇 <b>Game shuru karne ke liye Play Game dabayein.</b>\n"
        "/help — commands aur game guide"
    )
    poster = Path(__file__).with_name("start_photo.png")
    if poster.is_file():
        await message.answer_photo(FSInputFile(poster), caption=welcome,
                                   reply_markup=main_keyboard(), parse_mode="HTML")
    else:
        await message.answer(welcome, reply_markup=main_keyboard(), parse_mode="HTML")


async def on_play(callback: CallbackQuery, bot: Bot):
    q = get_question()
    if not q:
        try:
            q = await ensure_auto_question()
        except Exception:
            log.exception("On-demand Commons photo fetch failed")
    if not q:
        await callback.answer("Abhi photo available nahi hai. Thodi der baad try karein ya admin /add se photo add kare.", show_alert=True)
        return
    await callback.answer()
    await send_question(callback.message, q)


async def on_guess(callback: CallbackQuery):
    try:
        _, qid_s, choice = callback.data.split(":", 2)
        qid = int(qid_s)
    except (ValueError, AttributeError):
        await callback.answer("Invalid option.", show_alert=True)
        return
    with closing(db()) as con:
        row = con.execute("SELECT answer FROM questions WHERE id=?", (qid,)).fetchone()
    if not row:
        await callback.answer("Question nahi mila.", show_alert=True)
        return
    answer = row[0]
    if choice.casefold() == answer.casefold():
        earned = update_score(callback.from_user.id, callback.from_user.full_name, qid)
        text = (f"✅ <b>Correct!</b>\nAnswer: <b>{html.escape(answer)}</b>\n\n🎉 +1 point mila." if earned
                else f"✅ <b>Correct!</b>\nAnswer: <b>{html.escape(answer)}</b>\n\nIs photo ka point aap pehle le chuke hain.")
    else:
        text = f"❌ <b>Wrong answer!</b>\nCorrect answer: <b>{html.escape(answer)}</b>\n\nNext photo try karein."
    await callback.answer("Correct!" if choice.casefold() == answer.casefold() else "Wrong answer")
    try:
        # No Next Photo button: users can start another round from the main menu.
        await callback.message.edit_caption(caption=text, reply_markup=None, parse_mode="HTML")
    except Exception as exc:
        log.info("Could not edit answer caption: %s", exc)


async def on_leaderboard(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(leaderboard_text(), parse_mode="HTML", reply_markup=main_keyboard())


async def on_how(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "ℹ️ <b>How to Play</b>\n1. Play Game dabayein.\n2. Photo dekhkar actress ka naam choose karein.\n3. Sahi jawab par +1 point.\n4. Leaderboard mein top players dekhein.\n\nAdmin photo add karne ke liye photo caption mein /add command likhein.",
        parse_mode="HTML", reply_markup=main_keyboard())


async def on_help_message(message: Message):
    await message.answer(
        "🆘 <b>ACTRESS QUIZ — HELP CENTER</b>\n\n"
        "🎮 <b>/start</b> — Main menu aur game open karein\n"
        "❓ <b>/help</b> — Ye help guide dekhein\n"
        "🏆 <b>/leaderboard</b> — Top 10 players dekhein\n"
        "📊 <b>/stats</b> — Admin photo/player statistics\n\n"
        "<b>How to play</b>\n"
        "1. Play Game dabayein.\n2. Actress ki photo dekhein.\n"
        "3. 4 options mein se sahi naam choose karein.\n"
        "4. Sahi jawab par +1 point milega.\n\n"
        "<b>Admin photo upload</b>\n"
        "Photo bhejein aur caption mein likhein:\n"
        "<code>/add Correct Name | Wrong 1 | Wrong 2 | Wrong 3</code>\n\n"
        "Auto-post ke liye bot ko channel admin banayein aur AUTO_POST_CHAT_ID set karein.",
        parse_mode="HTML", reply_markup=main_keyboard())


async def on_help_button(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "🆘 <b>HELP CENTER</b>\n\nPlay Game se quiz shuru karein. Photo dekhkar 4 options mein se ek choose karein. Sahi jawab par +1 point milta hai. /help command se ye guide kabhi bhi khol sakte hain.",
        parse_mode="HTML", reply_markup=main_keyboard())


async def on_leaderboard_message(message: Message):
    await message.answer(leaderboard_text(), parse_mode="HTML", reply_markup=main_keyboard())


async def add_photo(message: Message):
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔ Ye command sirf bot admin use kar sakta hai.")
        return
    if not message.photo:
        await message.reply("Photo ke saath caption dein:\n/add Correct Name | Wrong 1 | Wrong 2 | Wrong 3")
        return
    if not message.caption or not message.caption.startswith("/add "):
        await message.reply("Caption format:\n/add Correct Name | Wrong 1 | Wrong 2 | Wrong 3")
        return
    parts = [p.strip() for p in message.caption[5:].split("|")]
    if len(parts) != 4 or any(not p for p in parts) or len(set(x.casefold() for x in parts)) != 4:
        await message.reply("❌ Exactly 4 different names dein:\n/add Correct Name | Wrong 1 | Wrong 2 | Wrong 3")
        return
    add_question(message.photo[-1].file_id, parts[0], parts)
    await message.reply(f"✅ Photo added! Correct answer: <b>{html.escape(parts[0])}</b>", parse_mode="HTML")


async def stats(message: Message):
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔ Admin only.")
        return
    with closing(db()) as con:
        count = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        players = con.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    await message.reply(f"📊 Total photos/questions: {count}\n👥 Players: {players}\n⏱ Auto-post: every {AUTO_POST_INTERVAL_MINUTES} minutes")


async def auto_poster(bot: Bot):
    if not AUTO_POST_ENABLED or not AUTO_POST_CHAT_ID:
        log.info("Auto-post disabled: set AUTO_POST_CHAT_ID and AUTO_POST_ENABLED=true to enable it")
        return
    while True:
        try:
            # Try to fetch a fresh Commons image on every cycle; fall back to saved photos.
            q = await ensure_auto_question()
            if not q:
                q = get_question()
            if q:
                caption = "🎭 <b>ACTRESS PHOTO GUESS</b>\n\nWho is this actress? Choose the correct answer!"
                await bot.send_photo(chat_id=AUTO_POST_CHAT_ID, photo=q["photo_id"], caption=caption,
                                     reply_markup=question_keyboard(q), parse_mode="HTML")
                log.info("Auto-posted question id=%s", q["id"])
            else:
                log.warning("No usable question/photo found. Add photos with /add or check Commons access.")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Auto-post failed; will retry next interval")
        await asyncio.sleep(AUTO_POST_INTERVAL_MINUTES * 60)


async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN missing. Set it in Heroku Config Vars.")
    init_db()
    bot = Bot(TOKEN)
    dp = Dispatcher()
    dp.message.register(start, CommandStart())
    dp.message.register(add_photo, F.photo)
    dp.message.register(stats, Command("stats"))
    dp.message.register(on_help_message, Command("help"))
    dp.message.register(on_leaderboard_message, Command("leaderboard"))
    dp.callback_query.register(on_play, F.data == "play")
    dp.callback_query.register(on_guess, F.data.startswith("guess:"))
    dp.callback_query.register(on_leaderboard, F.data == "leaderboard")
    dp.callback_query.register(on_how, F.data == "how")
    dp.callback_query.register(on_help_button, F.data == "help")
    await bot.set_my_commands([
        BotCommand(command="start", description="Open the main menu"),
        BotCommand(command="help", description="Help and game guide"),
        BotCommand(command="leaderboard", description="Top 10 players"),
        BotCommand(command="stats", description="Admin statistics"),
    ])
    poster_task = asyncio.create_task(auto_poster(bot))
    log.info("Actress Photo Guess Bot started; auto-post interval=%s minutes", AUTO_POST_INTERVAL_MINUTES)
    try:
        await dp.start_polling(bot)
    finally:
        poster_task.cancel()
        await asyncio.gather(poster_task, return_exceptions=True)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
