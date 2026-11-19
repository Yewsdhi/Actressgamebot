import asyncio
import logging
import os
import random
import sqlite3
from contextlib import closing

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("DB_PATH", "actress_game.db")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("actress-game")

def db():
    return sqlite3.connect(DB_PATH)

def init_db():
    with closing(db()) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_id TEXT NOT NULL,
            answer TEXT NOT NULL,
            options TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS scores (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            points INTEGER NOT NULL DEFAULT 0
        )""")
        con.commit()

def get_question(exclude_id=None):
    with closing(db()) as con:
        if exclude_id is None:
            row = con.execute("SELECT id, photo_id, answer, options FROM questions ORDER BY RANDOM() LIMIT 1").fetchone()
        else:
            row = con.execute("SELECT id, photo_id, answer, options FROM questions WHERE id != ? ORDER BY RANDOM() LIMIT 1", (exclude_id,)).fetchone()
            if row is None:
                row = con.execute("SELECT id, photo_id, answer, options FROM questions ORDER BY RANDOM() LIMIT 1").fetchone()
    if not row:
        return None
    qid, photo_id, answer, options = row
    return {"id": qid, "photo_id": photo_id, "answer": answer, "options": options.split("|")}

def question_keyboard(q):
    builder = InlineKeyboardBuilder()
    opts = q["options"][:]
    random.shuffle(opts)
    for opt in opts:
        builder.button(text=opt, callback_data=f"guess:{q['id']}:{opt}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="➡️ Next Question", callback_data=f"next:{q['id']}"))
    return builder.as_markup()

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Play Game", callback_data="play")],
        [InlineKeyboardButton(text="🏆 Leaderboard", callback_data="leaderboard"),
         InlineKeyboardButton(text="ℹ️ How to Play", callback_data="how")]
    ])

def add_question(photo_id, answer, options):
    with closing(db()) as con:
        con.execute("INSERT INTO questions(photo_id, answer, options) VALUES (?, ?, ?)",
                    (photo_id, answer, "|".join(options)))
        con.commit()

def update_score(user_id, name):
    with closing(db()) as con:
        con.execute("""INSERT INTO scores(user_id, name, points) VALUES (?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, points=points+1""",
            (user_id, name))
        con.commit()

def leaderboard_text():
    with closing(db()) as con:
        rows = con.execute("SELECT name, points FROM scores ORDER BY points DESC LIMIT 10").fetchall()
    if not rows:
        return "🏆 Abhi leaderboard khaali hai. Pehla point jeetne wale aap ban sakte hain!"
    return "🏆 <b>TOP PLAYERS</b>\n\n" + "\n".join(
        f"{i}. {name} — <b>{points}</b> points" for i, (name, points) in enumerate(rows, 1)
    )

async def send_question(target, q, edit_message=None):
    caption = "🎭 <b>Who is this actress?</b>\n\nPhoto dekho aur sahi naam choose karo!"
    markup = question_keyboard(q)
    if edit_message:
        try:
            await edit_message.delete()
        except Exception:
            pass
    await target.answer_photo(photo=q["photo_id"], caption=caption, reply_markup=markup, parse_mode="HTML")

async def start(message: Message):
    await message.answer(
        "✨ <b>ACTRESS PHOTO GUESS</b>\n\nBollywood actress ki photo dekho aur naam guess karo.\nSahi jawab par +1 point milega!",
        reply_markup=main_keyboard(), parse_mode="HTML"
    )

async def on_play(callback: CallbackQuery, bot: Bot):
    q = get_question()
    if not q:
        await callback.answer("Abhi game mein photos add nahi hain.", show_alert=True)
        await callback.message.answer(
            "🎭 Game abhi ready nahi hai.\n\nAdmin ko actress ki photo is format mein bhejni hogi:\n"
            "<code>/add Correct Name | Wrong Option 1 | Wrong Option 2 | Wrong Option 3</code>\n\n"
            "Photo ke caption mein ye command likhein.", parse_mode="HTML")
        return
    await callback.answer()
    await send_question(callback.message, q)

async def on_guess(callback: CallbackQuery):
    _, qid, choice = callback.data.split(":", 2)
    with closing(db()) as con:
        row = con.execute("SELECT answer FROM questions WHERE id=?", (int(qid),)).fetchone()
    if not row:
        await callback.answer("Question nahi mila. Next dabayein.", show_alert=True)
        return
    answer = row[0]
    if choice.casefold() == answer.casefold():
        update_score(callback.from_user.id, callback.from_user.full_name)
        text = f"✅ <b>Correct!</b>\nAnswer: <b>{answer}</b>\n\n🎉 Aapko +1 point mila."
    else:
        text = f"❌ <b>Wrong answer!</b>\nCorrect answer: <b>{answer}</b>\n\nNext question try karein."
    await callback.answer("Correct! +1 point" if choice.casefold() == answer.casefold() else "Wrong answer", show_alert=False)
    try:
        await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➡️ Next Question", callback_data=f"next:{qid}")],
            [InlineKeyboardButton(text="🏆 Leaderboard", callback_data="leaderboard")]
        ]), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, parse_mode="HTML")

async def on_next(callback: CallbackQuery):
    try:
        old_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        old_id = None
    q = get_question(old_id)
    if not q:
        await callback.answer("Abhi aur photos available nahi hain.", show_alert=True)
        return
    await callback.answer()
    await send_question(callback.message, q)

async def on_leaderboard(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(leaderboard_text(), parse_mode="HTML", reply_markup=main_keyboard())

async def on_how(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "ℹ️ <b>How to Play</b>\n1. Play Game dabayein.\n2. Photo dekhkar actress ka naam choose karein.\n"
        "3. Sahi jawab par +1 point.\n4. Leaderboard mein top players dekhein.\n\n"
        "Admin photos add kar sakta hai: photo ke caption mein /add command likhein.",
        parse_mode="HTML", reply_markup=main_keyboard()
    )

async def add_photo(message: Message):
    if message.from_user.id not in ADMIN_IDS:
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
    photo_id = message.photo[-1].file_id
    add_question(photo_id, parts[0], parts)
    await message.reply(f"✅ Actress photo added!\nCorrect answer: <b>{parts[0]}</b>", parse_mode="HTML")

async def stats(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔ Admin only.")
        return
    with closing(db()) as con:
        count = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        players = con.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    await message.reply(f"📊 Questions: {count}\n👥 Players: {players}")

async def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN missing. Set it in your .env file.")
    init_db()
    bot = Bot(TOKEN)
    dp = Dispatcher()
    dp.message.register(start, CommandStart())
    dp.message.register(add_photo, F.photo)
    dp.message.register(stats, Command("stats"))
    dp.callback_query.register(on_play, F.data == "play")
    dp.callback_query.register(on_guess, F.data.startswith("guess:"))
    dp.callback_query.register(on_next, F.data.startswith("next:"))
    dp.callback_query.register(on_leaderboard, F.data == "leaderboard")
    dp.callback_query.register(on_how, F.data == "how")
    log.info("Actress Photo Guess Bot is running")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
