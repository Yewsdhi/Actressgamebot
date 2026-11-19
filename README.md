# Actress Photo Guess Bot

A Telegram photo-quiz bot. Players identify the actress shown in a photo, earn points, and compete on a leaderboard.

## Features

- Photo-based multiple-choice quiz
- Random question selection
- +1 point for a correct answer
- Top 10 leaderboard
- Admin-only photo upload command
- SQLite database (no external database required)
- Heroku Deploy Button configuration (`app.json`)

## Deploy to Heroku

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://www.heroku.com/deploy/?template=https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPOSITORY)

**Before using the button:** replace `YOUR_GITHUB_USERNAME` and `YOUR_REPOSITORY` in the badge URL above and in `app.json` with your actual public GitHub repository details. Commit and push those changes.

1. Upload all project files to a **public GitHub repository**.
2. Replace the placeholder GitHub username/repository in:
   - `README.md` deploy-button URL
   - `app.json` `website` and `repository` values
3. Open your GitHub repository's README and click **Deploy to Heroku**.
4. On Heroku's app creation page, choose an app name and set:
   - `BOT_TOKEN`: token from `@BotFather`
   - `ADMIN_IDS`: your numeric Telegram user ID (comma-separated IDs are supported)
   - `DB_PATH`: leave as `actress_game.db` unless you have a reason to change it
5. Click **Deploy**. The `worker` process is configured to run one copy of `python bot.py`.

The app uses a background worker, not a web server. The Procfile must remain:

```procfile
worker: python bot.py
```

If the worker is not started automatically, open the Heroku app's **Resources** tab and enable one `worker` dyno.

## Run locally

1. Create a bot with **@BotFather** and copy its token.
2. Copy `.env.example` to `.env`.
3. Set `BOT_TOKEN` and `ADMIN_IDS` in `.env`.
4. Install dependencies and start:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## Add actress photos

An admin sends a photo to the bot with this exact caption format:

```text
/add Correct Actress Name | Wrong Option 1 | Wrong Option 2 | Wrong Option 3
```

Use images you own, have permission to use, or are otherwise licensed for this use. The bot stores Telegram's photo `file_id`.

## Commands

- `/start` — open the game
- `/stats` — admin-only question and player count

## Important data-storage note

This starter project stores scores and questions in SQLite. Heroku's local filesystem is ephemeral, so SQLite data may be lost when the dyno restarts, is replaced, or redeployed. For a production deployment where game data must persist, migrate the database to a persistent PostgreSQL service.

## GitHub upload

Upload the project files to a new GitHub repository. Do **not** upload `.env`, bot tokens, or database files.
