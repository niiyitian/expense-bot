"""
SQLite storage layer for the expense tracker bot.

Everything lives in a single file: expenses.db
You can open it anytime with DB Browser for SQLite (https://sqlitebrowser.org/)
to inspect, edit, or manually fix entries.
"""
import aiosqlite
import csv
import io
from datetime import datetime, timedelta

import os

# On Railway, mount a Volume and set DB_PATH to its mount path (e.g. /data/expenses.db)
# so the database survives redeploys. Locally this just defaults to the current folder.
DB_PATH = os.environ.get("DB_PATH", "expenses.db")

DEFAULT_CATEGORIES = [
    "Food", "Transport", "Shopping", "Bills",
    "Entertainment", "Health", "Other"
]


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                description TEXT,
                category TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                UNIQUE(user_id, name)
            )
        """)
        await db.commit()


async def ensure_default_categories(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM categories WHERE user_id = ?", (user_id,)
        )
        (count,) = await cur.fetchone()
        if count == 0:
            await db.executemany(
                "INSERT OR IGNORE INTO categories (user_id, name) VALUES (?, ?)",
                [(user_id, c) for c in DEFAULT_CATEGORIES]
            )
            await db.commit()


async def get_categories(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT name FROM categories WHERE user_id = ? ORDER BY name", (user_id,)
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def add_category(user_id: int, name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO categories (user_id, name) VALUES (?, ?)",
                (user_id, name)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def add_expense(user_id: int, amount: float, description: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO expenses (user_id, amount, description, category, created_at)
               VALUES (?, ?, ?, NULL, ?)""",
            (user_id, amount, description, datetime.utcnow().isoformat())
        )
        await db.commit()
        return cur.lastrowid


async def set_category(expense_id: int, category: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE expenses SET category = ? WHERE id = ?", (category, expense_id)
        )
        await db.commit()


async def delete_expense(expense_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?", (expense_id, user_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def get_last_expense(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """SELECT id, amount, description, category, created_at
               FROM expenses WHERE user_id = ? ORDER BY id DESC LIMIT 1""",
            (user_id,)
        )
        return await cur.fetchone()


async def get_recent(user_id: int, limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """SELECT id, amount, description, category, created_at
               FROM expenses WHERE user_id = ? ORDER BY id DESC LIMIT ?""",
            (user_id, limit)
        )
        return await cur.fetchall()


async def get_summary(user_id: int, since: datetime):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """SELECT COALESCE(category, 'Uncategorized') as cat, SUM(amount), COUNT(*)
               FROM expenses
               WHERE user_id = ? AND created_at >= ?
               GROUP BY cat
               ORDER BY SUM(amount) DESC""",
            (user_id, since.isoformat())
        )
        rows = await cur.fetchall()
        total = sum(r[1] for r in rows)
        return rows, total


async def export_csv(user_id: int) -> io.StringIO:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """SELECT id, amount, description, category, created_at
               FROM expenses WHERE user_id = ? ORDER BY id""",
            (user_id,)
        )
        rows = await cur.fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "amount", "description", "category", "created_at"])
    writer.writerows(rows)
    buf.seek(0)
    return buf


def start_of_today():
    now = datetime.utcnow()
    return datetime(now.year, now.month, now.day)


def start_of_week():
    now = datetime.utcnow()
    today = datetime(now.year, now.month, now.day)
    return today - timedelta(days=today.weekday())


def start_of_month():
    now = datetime.utcnow()
    return datetime(now.year, now.month, 1)
