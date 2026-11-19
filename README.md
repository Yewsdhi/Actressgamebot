# Actress Photo Guess Bot — Full Fix

Telegram actress photo quiz with 4 choices, points, leaderboard, channel buttons, optional force-subscribe, and automatic channel posts every 15 minutes.

## Automatic photos: important limitation

The bot can automatically search **Wikimedia Commons** for images of a built-in list of Indian actresses. It accepts files only when Commons metadata indicates a Creative Commons/public-domain style license, and adds source/creator/license information to the post caption. Commons does not contain every actress or a guaranteed usable image for every search, so no bot can honestly promise “all actress photos.” Add your own licensed/permission-cleared images with `/add` to expand the library. If a Commons lookup fails, the bot falls back to saved photos.

## Heroku setup

1. Upload this project to your GitHub repository and deploy it as a **worker**.
2. Set these Heroku Config Vars:

| Variable | Value |
|---|---|
| `BOT_TOKEN` | Token from `@BotFather` |
| `ADMIN_IDS` | Your numeric Telegram user ID; comma-separated for multiple admins |
| `DB_PATH` | `actress_game.db` |
| `AUTO_POST_ENABLED` | `true` |
| `AUTO_POST_CHAT_ID` | `@YourPublicChannel` or numeric channel ID |
| `AUTO_POST_INTERVAL_MINUTES` | `15` |
| `SUPPORT_CHANNEL` | `@YourSupportChannel` or full `https://t.me/...` URL |
| `UPDATE_CHANNEL` | `@YourUpdateChannel` or full `https://t.me/...` URL |
| `FORCE_SUB_CHANNEL` | Optional; channel username/ID required before playing, blank disables |

3. Add the bot as an **administrator** in the auto-post channel with permission to post messages/photos. If using force-subscribe, the bot must also be able to check membership in that channel.
4. Keep exactly one worker running. Two workers would cause duplicate automatic posts.
5. Heroku's local filesystem is temporary. SQLite scores/photos can be lost on dyno replacement/redeploy. Use Heroku Postgres or another persistent database for production persistence; this starter still uses SQLite.

## Commands

- `/start` — open the game
- `/stats` — admin-only photo/player count
- Add a photo: send a photo with this caption:

```text
/add Correct Actress Name | Wrong Option 1 | Wrong Option 2 | Wrong Option 3
```

Example:

```text
/add Deepika Padukone | Alia Bhatt | Priyanka Chopra | Katrina Kaif
```

Use images you own, have permission to use, or are licensed to use. For automatically fetched Commons images, source details are included in the caption.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env, then:
python bot.py
```

## Reliability notes

- Automatic posting runs inside the worker process and retries on the next 15-minute cycle after errors.
- Telegram must be able to access the image URL returned by Wikimedia Commons.
- The first auto-post happens immediately after worker startup; later posts follow the configured interval.
- Only one worker should run to avoid duplicate posts.
