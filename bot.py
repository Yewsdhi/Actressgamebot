import asyncio
import html
import json
import logging
import os
from pathlib import Path
import random
import sqlite3
import time
import sys
from contextlib import closing
from urllib.parse import quote

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
NOTIFICATION_GROUP_ID = os.getenv("NOTIFICATION_GROUP_ID", "").strip()
DB_PATH = os.getenv("DB_PATH", "actress_game.db")
# Auto-post is group-only: destinations are discovered when this bot is added to a group.
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
        con.execute("""CREATE TABLE IF NOT EXISTS bot_users (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            username TEXT DEFAULT '',
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS answered (
            question_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY(question_id, user_id)
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS auto_post_groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT DEFAULT '',
            next_post_at REAL DEFAULT 0,
            last_question_id INTEGER DEFAULT 0
        )""")
        group_cols = {r[1] for r in con.execute("PRAGMA table_info(auto_post_groups)")}
        if "next_post_at" not in group_cols:
            con.execute("ALTER TABLE auto_post_groups ADD COLUMN next_post_at REAL DEFAULT 0")
        if "last_question_id" not in group_cols:
            con.execute("ALTER TABLE auto_post_groups ADD COLUMN last_question_id INTEGER DEFAULT 0")
        if "last_photo_id" not in group_cols:
            con.execute("ALTER TABLE auto_post_groups ADD COLUMN last_photo_id TEXT DEFAULT ''")
        con.commit()


def get_question(exclude_id=None, exclude_ids=None, exclude_photo_ids=None):
    excluded = set(exclude_ids or [])
    if exclude_id is not None:
        excluded.add(exclude_id)
    excluded_photos = {str(x) for x in (exclude_photo_ids or []) if x}
    clauses, params = [], []
    if excluded:
        clauses.append("id NOT IN (" + ",".join("?" for _ in excluded) + ")")
        params.extend(excluded)
    if excluded_photos:
        clauses.append("photo_id NOT IN (" + ",".join("?" for _ in excluded_photos) + ")")
        params.extend(excluded_photos)
    query = "SELECT id, photo_id, answer, options, source FROM questions"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY RANDOM() LIMIT 1"
    with closing(db()) as con:
        row = con.execute(query, tuple(params)).fetchone()
    if not row:
        return None
    qid, photo_id, answer, options, source = row
    try:
        parsed_options = json.loads(options)
    except (json.JSONDecodeError, TypeError):
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


async def ensure_auto_question(exclude_ids=None, exclude_photo_ids=None):
    # Fetch a fresh, freely licensed Commons photo for this group's cycle.
    # A photo already used by another group's current post is never selected.
    timeout = aiohttp.ClientTimeout(total=22)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for _ in range(30):
            name = random.choice(ACTRESSES)
            result = await fetch_commons_photo(session, name)
            if not result:
                continue
            photo_url, source = result
            with closing(db()) as con:
                exists = con.execute(
                    "SELECT 1 FROM questions WHERE photo_id = ? LIMIT 1", (photo_url,)
                ).fetchone()
            if exists or photo_url in set(exclude_photo_ids or []):
                continue
            distractors = random.sample([x for x in ACTRESSES if x != name], 3)
            qid = add_question(photo_url, name, [name] + distractors, source)
            return {"id": qid, "photo_id": photo_url, "answer": name,
                    "options": [name] + distractors, "source": source}

    # If Commons has no fresh image, use a different stored photo or skip this cycle.
    return get_question(exclude_ids=exclude_ids, exclude_photo_ids=exclude_photo_ids)


async def start(message: Message, bot: Bot):
    # Notify configured admins only once, when a Telegram user starts the bot for the first time.
    user = message.from_user
    if user and message.chat.type == "private":
        with closing(db()) as con:
            cur = con.execute(
                "INSERT OR IGNORE INTO bot_users(user_id, name, username) VALUES (?, ?, ?)",
                (user.id, user.full_name, user.username or "")
            )
            is_new_user = cur.rowcount == 1
            total_users = con.execute("SELECT COUNT(*) FROM bot_users").fetchone()[0]
            con.commit()
        if is_new_user:
            display_name = html.escape(user.full_name)
            username = f"@{html.escape(user.username)}" if user.username else "Not set"
            notice = (
                "🆕 <b>NEW USER STARTED THE BOT</b>\n\n"
                f"👤 Name: {display_name}\n"
                f"🔗 Username: {username}\n"
                f"🆔 User ID: <code>{user.id}</code>\n"
                f"📊 Total Users: <b>{total_users}</b>"
            )
            await _send_admin_notice(bot, notice)

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
        "📊 <b>/stats</b> — Admin photo/player statistics\n"
        "♻️ <b>/restart</b> — Admin: worker restart karein\n"
        "📢 <b>/broadcast</b> — Admin: /broadcast text sabhi users ko bhejein\n"
        "📢 <b>/broadcastgroups</b> — Admin: /broadcastgroups text sabhi groups ko bhejein\n"
        "👥 <b>/registergroup</b> — Is group mein har 15 minute auto-post enable karein (group mein use karein)\n\n"
        "<b>How to play</b>\n"
        "1. Play Game dabayein.\n2. Actress ki photo dekhein.\n"
        "3. 4 options mein se sahi naam choose karein.\n"
        "4. Sahi jawab par +1 point milega.\n\n"
        "<b>Admin photo upload</b>\n"
        "Photo bhejein aur caption mein likhein:\n"
        "<code>/add Correct Name | Wrong 1 | Wrong 2 | Wrong 3</code>\n\n"
        "<b>Group Auto-post</b>\n"
        "Bot ko group mein add karein, message bhejne ki permission dein, phir group mein <code>/registergroup</code> bhejein.\n"
        "Is command se wahi group har 15 minute auto-post ke liye register hoga.",
        parse_mode="HTML", reply_markup=main_keyboard())


async def on_help_button(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "🆘 <b>HELP CENTER</b>\n\n"
        "🎮 Play Game se quiz shuru karein. Photo dekhkar 4 options mein se ek choose karein. Sahi jawab par +1 point milta hai.\n\n"
        "👥 <b>/registergroup</b> — Is group mein har 15 minute auto-post enable karein. Ye command usi group mein bhejein jahan posts chahiye.\n"
        "❓ <b>/help</b> — Ye guide kabhi bhi khol sakte hain.\n"
        "♻️ <b>/restart</b> — Admin-only worker restart.\n"
        "📢 <b>/broadcast</b> — Admin: /broadcast message sabhi users ko bhejein (reply nahi).\n"
        "📢 <b>/broadcastgroups</b> — Admin: /broadcastgroups message sabhi groups ko bhejein (reply nahi).",
        parse_mode="HTML", reply_markup=main_keyboard())


async def on_leaderboard_message(message: Message):
    await message.answer(leaderboard_text(), parse_mode="HTML", reply_markup=main_keyboard())


async def add_photo(message: Message):
    # Ignore ordinary group photos; only /add-captioned photos are processed.
    caption = (message.caption or "").strip()
    if not caption.startswith("/add"):
        return
    # Only configured bot owner/admin IDs may add actress photos.
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        # Silently ignore /add attempts from anyone except the owner.
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


async def _send_admin_notice(bot: Bot, text: str):
    """Send event notifications to configured admin IDs and optional log group."""
    targets = set(ADMIN_IDS)
    if NOTIFICATION_GROUP_ID:
        try:
            targets.add(int(NOTIFICATION_GROUP_ID))
        except ValueError:
            log.error("NOTIFICATION_GROUP_ID must be a numeric chat ID")
    for target in targets:
        try:
            await bot.send_message(target, text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            log.exception("Could not send notification to %s", target)


async def broadcast_users(message: Message, bot: Bot):
    """Broadcast /broadcast <text> to every user who has started the bot."""
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔ Admin only.")
        return
    broadcast_text = (message.text or "").partition(" ")[2].strip()
    if not broadcast_text:
        await message.reply("Use: <code>/broadcast Your message here</code>\n\nYe message sabhi registered bot users ko jayega. Reply ki zaroorat nahi hai.", parse_mode="HTML")
        return
    with closing(db()) as con:
        targets = [row[0] for row in con.execute("SELECT user_id FROM bot_users").fetchall()]
    sent = failed = 0
    status = await message.reply(f"📢 Broadcast shuru: {len(targets)} users...")
    for user_id in targets:
        try:
            await bot.send_message(user_id, broadcast_text, parse_mode=None, disable_web_page_preview=True)
            sent += 1
        except Exception as exc:
            failed += 1
            log.info("Broadcast to user=%s failed: %s", user_id, exc)
        await asyncio.sleep(0.04)
    await status.edit_text(f"✅ <b>Broadcast complete</b>\n\n👥 Total users: {len(targets)}\n📨 Sent: {sent}\n❌ Failed: {failed}", parse_mode="HTML")


async def broadcast_groups(message: Message, bot: Bot):
    """Broadcast /broadcastgroups <text> to all groups where the bot is present."""
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔ Admin only.")
        return
    broadcast_text = (message.text or "").partition(" ")[2].strip()
    if not broadcast_text:
        await message.reply("Use: <code>/broadcastgroups Your message here</code>\n\nYe message bot wale sabhi registered groups mein jayega. Reply ki zaroorat nahi hai.", parse_mode="HTML")
        return
    with closing(db()) as con:
        targets = [row[0] for row in con.execute("SELECT chat_id FROM auto_post_groups").fetchall()]
    sent = failed = 0
    status = await message.reply(f"📢 Group broadcast shuru: {len(targets)} groups...")
    for chat_id in targets:
        try:
            await bot.send_message(chat_id, broadcast_text, parse_mode=None, disable_web_page_preview=True)
            sent += 1
        except Exception as exc:
            failed += 1
            log.info("Broadcast to group=%s failed: %s", chat_id, exc)
        await asyncio.sleep(0.05)
    await status.edit_text(f"✅ <b>Group broadcast complete</b>\n\n👥 Total groups: {len(targets)}\n📨 Sent: {sent}\n❌ Failed: {failed}", parse_mode="HTML")


async def restart_command(message: Message):
    """Restart the Heroku worker process; admin-only."""
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔ Admin only.")
        return
    await message.reply("♻️ Bot worker restart ho raha hai...")
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)


async def chat_id_command(message: Message):
    """Show the current chat ID so it can be used in Heroku Config Vars."""
    await message.reply(f"Chat ID: <code>{message.chat.id}</code>", parse_mode="HTML")


async def stats(message: Message):
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔ Admin only.")
        return
    with closing(db()) as con:
        count = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        players = con.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    await message.reply(f"📊 Total photos/questions: {count}\n👥 Players: {players}\n⏱ Auto-post: every {AUTO_POST_INTERVAL_MINUTES} minutes")


async def register_group_command(message: Message):
    """Allow a group admin to manually register this group for scheduled posts."""
    chat = message.chat
    if chat.type not in {"group", "supergroup"}:
        await message.reply("Please use /registergroup inside the group where you want auto-posts.")
        return
    try:
        member = await message.bot.get_chat_member(chat.id, (await message.bot.get_me()).id)
        if member.status not in {"member", "administrator"}:
            await message.reply("Please add the bot to this group first.")
            return
    except Exception:
        log.exception("Could not verify bot membership in group=%s", chat.id)
        await message.reply("I could not verify my membership. Please check that I am still in this group.")
        return
    with closing(db()) as con:
        con.execute(
            "INSERT INTO auto_post_groups(chat_id, title, next_post_at, last_question_id, last_photo_id) VALUES (?, ?, ?, 0, '') "
            "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title",
            (chat.id, chat.title or "", time.time())
        )
        # Re-running /registergroup makes the first post due immediately; after
        # a successful post, mark_group_posted schedules the next one per group.
        con.execute("UPDATE auto_post_groups SET next_post_at=? WHERE chat_id=?", (time.time(), chat.id))
        con.commit()
    await message.reply("✅ Group registered. The first post will be attempted now; later posts are scheduled every %s minutes." % AUTO_POST_INTERVAL_MINUTES)
    log.info("Manually registered group for auto-post: %s (%s)", chat.title, chat.id)


async def track_group_membership(event: ChatMemberUpdated, bot: Bot):
    """Track bot group membership and notify admins when it is newly added."""
    chat = event.chat
    if chat.type not in {"group", "supergroup"}:
        return
    old_status = event.old_chat_member.status
    status = event.new_chat_member.status
    joined_now = old_status in {"left", "kicked"} and status in {"member", "administrator"}
    with closing(db()) as con:
        if status in {"member", "administrator"}:
            con.execute(
                "INSERT INTO auto_post_groups(chat_id, title, next_post_at, last_question_id, last_photo_id) VALUES (?, ?, ?, 0, '') "
                "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title",
                (chat.id, chat.title or "", time.time())
            )
            con.commit()
        elif status in {"left", "kicked"}:
            con.execute("DELETE FROM auto_post_groups WHERE chat_id = ?", (chat.id,))
            con.commit()
    if joined_now:
        added_by = event.from_user
        adder_name = html.escape(added_by.full_name) if added_by else "Unknown"
        adder_username = f"@{html.escape(added_by.username)}" if added_by and added_by.username else "Not set"
        notice = (
            "➕ <b>BOT ADDED TO NEW GROUP</b>\n\n"
            f"👥 Group: <b>{html.escape(chat.title or 'Unknown')}</b>\n"
            f"🆔 Group ID: <code>{chat.id}</code>\n"
            f"👤 Added by: {adder_name}\n"
            f"🔗 Username: {adder_username}\n"
            f"📊 Type: <b>{html.escape(str(chat.type))}</b>"
        )
        await _send_admin_notice(bot, notice)
        log.info("Bot added to group: %s (%s)", chat.title, chat.id)


def get_due_auto_post_groups(now=None):
    now = time.time() if now is None else now
    with closing(db()) as con:
        # Existing registered groups from older versions get their own first due time.
        con.execute("UPDATE auto_post_groups SET next_post_at=? WHERE next_post_at IS NULL OR next_post_at<=0", (now + AUTO_POST_INTERVAL_MINUTES * 60,))
        rows = con.execute(
            "SELECT chat_id, title, last_question_id, last_photo_id FROM auto_post_groups WHERE next_post_at<=? ORDER BY next_post_at",
            (now,)
        ).fetchall()
        con.commit()
    return rows


def mark_group_posted(chat_id, question_id, photo_id):
    next_time = time.time() + AUTO_POST_INTERVAL_MINUTES * 60
    with closing(db()) as con:
        con.execute(
            "UPDATE auto_post_groups SET next_post_at=?, last_question_id=?, last_photo_id=? WHERE chat_id=?",
            (next_time, question_id, str(photo_id), chat_id)
        )
        con.commit()


def get_all_group_current_photos():
    with closing(db()) as con:
        return con.execute("SELECT chat_id, title, last_question_id, last_photo_id FROM auto_post_groups").fetchall()


async def auto_poster(bot: Bot):
    if not AUTO_POST_ENABLED:
        log.info("Auto-post disabled: set AUTO_POST_ENABLED=true")
        return
    log.info("Per-group auto-post enabled; interval=%s minutes; database=%s", AUTO_POST_INTERVAL_MINUTES, DB_PATH)
    while True:
        try:
            due_groups = get_due_auto_post_groups()
            if not due_groups:
                await asyncio.sleep(5)
                continue
            log.info("Auto-post scheduler found %s due group(s)", len(due_groups))

            # Keep every group's current question distinct from every other group's
            # current question, and rotate each group's own question independently.
            current_rows = get_all_group_current_photos()
            used_question_ids = {row[2] for row in current_rows if row[2]}
            used_photo_ids = {str(row[3]) for row in current_rows if row[3]}
            for chat_id, title, last_question_id, last_photo_id in due_groups:
                try:
                    excluded_ids = set(used_question_ids)
                    excluded_photos = set(used_photo_ids)
                    if last_question_id:
                        excluded_ids.add(last_question_id)
                    if last_photo_id:
                        excluded_photos.add(str(last_photo_id))
                    # Prefer a fresh image for every group and every 15-minute cycle.
                    q = await ensure_auto_question(exclude_ids=excluded_ids, exclude_photo_ids=excluded_photos)
                    if not q:
                        log.error("No unique photo/question available for group=%s after Commons search; check outbound HTTPS access or add photo questions with /add", chat_id)
                        mark_group_posted(chat_id, last_question_id or 0, last_photo_id or '')
                        continue
                    caption = "🎭 <b>ACTRESS PHOTO GUESS</b>\n\nWho is this actress? Choose the correct answer!"
                    await bot.send_photo(
                        chat_id=chat_id, photo=q["photo_id"], caption=caption,
                        reply_markup=question_keyboard(q), parse_mode="HTML"
                    )
                    mark_group_posted(chat_id, q["id"], q["photo_id"])
                    used_question_ids.add(q["id"])
                    used_photo_ids.add(str(q["photo_id"]))
                    log.info("Auto-posted unique photo/question id=%s to group=%s (%s)", q["id"], chat_id, title)
                except Exception as exc:
                    log.exception("Auto-post failed for group=%s (%s): %s", chat_id, title, exc)
                    # Retry this group's post after one interval without affecting other groups.
                    mark_group_posted(chat_id, last_question_id or 0, last_photo_id or '')
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Per-group auto-post scheduler failed; will retry")
        await asyncio.sleep(5)


async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN missing. Set it in Heroku Config Vars.")
    init_db()
    bot = Bot(TOKEN)
    dp = Dispatcher()
    dp.my_chat_member.register(track_group_membership)
    dp.message.register(start, CommandStart())
    dp.message.register(add_photo, F.photo)
    dp.message.register(chat_id_command, Command("id"))
    dp.message.register(register_group_command, Command("registergroup"))
    dp.message.register(stats, Command("stats"))
    dp.message.register(restart_command, Command("restart"))
    dp.message.register(broadcast_users, Command("broadcast"))
    dp.message.register(broadcast_groups, Command("broadcastgroups"))
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
        BotCommand(command="restart", description="Admin: restart bot worker"),
        BotCommand(command="broadcast", description="Admin: broadcast to all bot users"),
        BotCommand(command="broadcastgroups", description="Admin: broadcast to registered groups"),
        BotCommand(command="registergroup", description="Enable auto-posts in this group"),
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
