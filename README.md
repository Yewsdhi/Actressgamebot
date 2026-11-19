# Actress Photo Guess Bot

Telegram Bollywood actress photo-guessing game with multiple-choice answers, points, and a top-10 leaderboard.

## Heroku deployment

This project runs as a background **worker**, not a web server.

1. Push this project to a **public GitHub repository**.
2. Replace `YOUR_GITHUB_USERNAME` and `YOUR_REPOSITORY` in `app.json` and the Deploy button URL below with the real repository details.
3. Open the GitHub repository and click the Deploy button.
4. Set Config Vars:
   - `BOT_TOKEN`: token from `@BotFather`
   - `ADMIN_IDS`: numeric Telegram user ID (comma-separated if multiple)
   - `DB_PATH`: `actress_game.db`
5. Deploy. `app.json` requests one worker using Heroku's `eco` dyno size.
6. If needed, open **Heroku Dashboard → app → Resources**, set worker quantity to `1`, and save.

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://www.heroku.com/deploy/?template=https://github.com/Yewsdhi/Actressgamebot)

**Important:** The Deploy button remains a template until the GitHub placeholders are replaced. Eco dyno scaling requires an eligible Eco subscription/account. A project file cannot activate or purchase the subscription; Heroku must permit dyno scaling on the account.

## Run locally

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, set `BOT_TOKEN` and `ADMIN_IDS`, then run `python bot.py`.

## Add question photos

An admin sends a photo with this caption:

```text
/add Correct Actress Name | Wrong Option 1 | Wrong Option 2 | Wrong Option 3
```

Use images you own, have permission to use, or are licensed to use. The bot stores Telegram's photo `file_id`.

## Commands

- `/start` — open the game
- `/stats` — admin-only question and player count

## Data persistence warning

The starter bot stores questions and scores in SQLite. Heroku's dyno filesystem is ephemeral, so this data can be lost when the dyno is replaced or redeployed. For persistent production data, migrate to PostgreSQL.
