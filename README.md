# Expense Tracker Telegram Bot

Log expenses by just typing them naturally. Everything is stored in a single
local SQLite file (`expenses.db`) — easy to back up, inspect, or edit.

## Setup

1. **Get a bot token**
   - Open Telegram, message [@BotFather](https://t.me/BotFather)
   - Send `/newbot`, follow the prompts, copy the token it gives you

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set your token and run**
   ```bash
   export BOT_TOKEN="123456:ABC-your-token-here"
   python bot.py
   ```

That's it — the bot will start polling. Message it on Telegram to try it out.

## Usage

Just send a message like:
```
coffee 5.50
5.50 coffee
$12 lunch with team
```

The bot logs it and shows category buttons to tap. Then use:

| Command | What it does |
|---|---|
| `/today` `/week` `/month` | Spending summary by category |
| `/recent` | Last 10 entries, each with a delete button |
| `/undo` | Remove your most recent entry |
| `/categories` | List categories; `/categories Groceries` adds one |
| `/export` | Download all expenses as a CSV file |

## Viewing/editing the raw data

`expenses.db` is a standard SQLite file. Open it anytime with
[DB Browser for SQLite](https://sqlitebrowser.org/) (free, GUI, no setup)
to browse, filter, or manually fix entries — no need to touch the bot code.

## Keeping it running

For actual day-to-day use you'll want the bot running continuously rather
than in a terminal window. Easiest options:
- Run it on a small VPS/cloud box with `screen`, `tmux`, or a `systemd` service
- Use a free-tier host like Railway or Fly.io
- Run it on a Raspberry Pi at home

### Deploying on Railway

1. Push this folder to a GitHub repo (or use the Railway CLI to deploy directly)
2. In Railway: **New Project → Deploy from GitHub repo**, pick the repo
3. Railway auto-detects Python and installs `requirements.txt`. It runs the
   `Procfile`, which tells it to start the bot as a **worker** (not a web
   service, since this bot doesn't listen on a port)
4. Go to your service's **Variables** tab and add:
   - `BOT_TOKEN` = your token from BotFather
5. **Important — add a Volume**, or your expenses will be wiped on every
   redeploy:
   - Go to your service → **Settings → Volumes → New Volume**
   - Set the mount path to `/data`
   - Add another variable: `DB_PATH` = `/data/expenses.db`
6. Deploy. Check the **Deployments → Logs** tab to confirm it started
   without errors — you should see aiogram's polling log lines.

## Notes on your "savings bot"

If you're not sure where that other bot's data lives, it's worth checking
whichever server or notebook it's deployed from for a `.db`, `.json`, or
`.csv` file, or checking if it logs to Google Sheets — happy to help track
it down if you paste the bot's code or point me to the repo.
