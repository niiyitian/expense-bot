# Money Tracker Telegram Bot

Tracks spending, income, and savings/debt in one bot. Everything is stored in
a single local SQLite file (`expenses.db`) — easy to back up, inspect, or edit.

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
   export STARTING_DEBT="5340"   # optional, your current debt balance
   python bot.py
   ```

That's it — the bot will start polling. Message it on Telegram to try it out.

## Usage

Just type naturally — no button needed for any of these:

| You type | What happens |
|---|---|
| `coffee 5.50` | Logs an expense, prompts you to tag a category |
| `+50 sold shoes` | Logs money received (sales, transfers, refunds) |
| `save 2000` or `save 2000 bonus` | Adds to your savings balance |
| `withdraw 300 rent` | Takes money out of savings |
| `return 500` or `repay 500` or `paid 500` | Logs a debt repayment |

Or use the button grid (tap the grid icon next to the emoji button) for the
same actions with guided prompts.

## Commands

| Command | What it does |
|---|---|
| `/summary` | Spending/income for today, week, month + savings balance & debt remaining |
| `/savings` | Full savings & debt breakdown, plus recent activity |
| `/setdebt 5340` | Set or correct your starting debt amount |
| `/today` `/week` `/month` | Spending + income for just that period |
| `/recent` | Last 10 expenses, each with a delete button |
| `/undo` | Remove your most recent entry (expense, income, or savings — whichever was last) |
| `/categories` | List categories; `/categories Groceries` adds one |
| `/rename Other Social` | Rename a category, retagging past expenses too |
| `/export` | Download everything as a CSV file |

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
   - `STARTING_DEBT` = your current debt amount (optional, e.g. `5340`) — only
     used the very first time; after that use `/setdebt` to correct it
5. **Important — add a Volume**, or your data will be wiped on every redeploy:
   - Go to your service → **Settings → Volumes → New Volume**
   - Set the mount path to `/data`
   - Add another variable: `DB_PATH` = `/data/expenses.db`
6. Deploy. Check the **Deployments → Logs** tab to confirm it started
   without errors.

## Migrating from your old savings bot

This bot's savings/debt numbers start at zero (aside from `STARTING_DEBT`).
Your old savings bot's history isn't automatically imported — if you want your
past save/return entries carried over, share that bot's `savings.db` and I can
write a one-off migration script.
