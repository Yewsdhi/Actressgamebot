# Actress Photo Guess Bot - Individual Group Auto Posts

Each registered group has its own independent 15-minute timer. Each group receives a separately selected question/photo; groups do not share one common post.

In every group, run `/registergroup` once. The timer for that group starts from registration. Keep the Heroku worker running and retain the persistent SQLite database (or use a persistent volume) so registrations and schedules survive restarts.

Set `AUTO_POST_ENABLED=true` and `AUTO_POST_INTERVAL_MINUTES=15`. Channel auto-posting remains disabled.
