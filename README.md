# Actress Photo Guess Bot — Full Fix

## 🚀 Deploy on Heroku

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/Yewsdhi/Actressgamebot)

Upload this folder to GitHub first, then replace `YOUR_GITHUB_USERNAME` and `YOUR_REPOSITORY` in this README and `app.json` with your real repository details.


Premium Black & Gold actress photo quiz with 4 choices, global leaderboard, daily challenge, Bollywood/South Indian categories, hints, player levels, profiles, streaks, achievements, custom start poster, optional support/update links, and automatic group posts every 15 minutes. Force-subscribe has been removed.

## Premium game features

- **Daily Challenge:** one daily question per player; a wrong answer uses that day's attempt.
- **Global Leaderboard:** top 10 players by total points.
- **Player Levels:** Beginner, Pro, Expert, Superstar and Legend based on points.
- **Hint System:** reveals the first letter and answer length.
- **Actress Categories:** Bollywood, South Indian and All Categories. The built-in category mapping is a curated starter list; other names are treated as Bollywood.
- **Winning Streak:** consecutive active-day streak and personal best.
- **My Profile:** points, global rank, level, streak and unlocked badges.
- **Achievements:** First Win, Quiz Pro (10 points), Superstar (50), Legend (100) and Hot Streak (5-day streak).

The new player stats, daily attempts and achievement tables are created automatically when the existing SQLite database starts. Existing questions, points, users, groups and answered-question records are preserved.

## Automatic photos: important limitation

The bot can automatically search **Wikimedia Commons** for images of a built-in list of Indian actresses. It accepts files only when Commons metadata indicates a Creative Commons/public-domain style license, and adds source/creator/license information to the post caption. Commons does not contain every actress or a guaranteed usable image for every search, so no bot can honestly promise “all actress photos.” Add your own licensed/permission-cleared images with `/add` to expand the library. If a Commons lookup fails, the bot falls back to saved photos.

## Heroku setup

1. Upload this project to your GitHub repository and deploy it as a **worker**.
2. Set these Heroku Config Vars:

| Variable | Value |
|---|---|
| `BOT_TOKEN` | Token from `@BotFather` |
| `ADMIN_IDS` | Your numeric Telegram user ID; comma-separated for multiple admins. This ID receives new-user notifications. |
| `DB_PATH` | `actress_game.db` (SQLite file; Heroku local disk is temporary) |
| `AUTO_POST_ENABLED` | `true` |
| `AUTO_POST_INTERVAL_MINUTES` | `15` |
| `SUPPORT_GROUP` | Support group username or invite URL |
| `SUPPORT_CHANNEL` | `@YourSupportChannel` or full `https://t.me/...` URL |
| `UPDATE_CHANNEL` | `@YourUpdateChannel` or full `https://t.me/...` URL |

3. Add the bot to each target group and allow it to send messages/photos. Channel auto-posting is disabled.
4. Keep exactly one worker running. Two workers would cause duplicate automatic posts.
5. Heroku's local filesystem is temporary. SQLite scores/photos can be lost on dyno replacement/redeploy. Use Heroku Postgres or another persistent database for production persistence; this starter still uses SQLite.

## Commands

- `/start` — open the game and main menu
- `/help` — detailed help and admin photo-upload guide
- `/leaderboard` — top 10 players
- `/stats` — admin-only photo/player count
- `/registergroup` — register the current group for automatic posts if it was added before the latest deploy or did not register automatically.
- New-user notification — sends one private alert to each configured `ADMIN_IDS` account when a person starts the bot for the first time; total registered users is included.
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
- The first auto-post happens immediately after worker startup; later posts follow the configured interval. Configure `SUPPORT_GROUP`, `SUPPORT_CHANNEL`, and `UPDATE_CHANNEL` to show their buttons in the start menu.
- Only one worker should run to avoid duplicate posts.


### Automatic posting to groups
The bot automatically registers a group when it is added there and posts to registered groups on the configured interval. It removes a group when it is kicked/removed. Add the bot to each group where you want posts, ensure it has permission to send messages/photos, then run `/registergroup` in each group. This also fixes groups that were added before deployment. It cannot post to groups it has not joined. Channel destinations are intentionally ignored; only groups where the bot is currently a member receive scheduled posts.


## New-user notifications in an admin group

1. Add the bot to your private notification group (use the invite link to join the group yourself, then add the bot).
2. In that group, send `/id` to the bot. It replies with the numeric chat ID.
3. In Heroku Config Vars, set `NOTIFICATION_GROUP_ID` to that numeric ID (usually starts with `-100`).
4. Ensure the bot can send messages in the group, then restart the Worker.

The bot sends one notification when a user starts it for the first time. The private invite link alone does not reveal the group ID; the `/id` command does.


## Admin commands
- `/broadcast`: Reply to a message with `/broadcast` to copy it to all users who have started the bot.
- `/broadcastgroups`: Reply to a message with `/broadcastgroups` to copy it to all registered auto-post groups.
- `/restart`: Restart the worker process.

Set `ADMIN_IDS` to your numeric Telegram user ID(s), comma-separated. Broadcast commands and restart are admin-only.
