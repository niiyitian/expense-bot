"""
Expense Tracker Telegram Bot

Just send a message like "coffee 5.50" or "5.50 coffee" and the bot logs it.
Tap a category button to tag it. Use /today, /week, /month for summaries,
/export for a CSV dump, /undo to remove your last entry, /recent to browse
and delete recent entries.

Setup:
    1. Get a bot token from @BotFather on Telegram
    2. export BOT_TOKEN="your-token-here"
    3. pip install -r requirements.txt
    4. python bot.py
"""
import asyncio
import os
import re
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile, BotCommand, ForceReply, ReplyKeyboardMarkup, KeyboardButton
)

import db

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Set the BOT_TOKEN environment variable (get one from @BotFather)")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Matches things like "5.50 coffee", "coffee 5.50", "$5.50 coffee", "coffee $5.50"
AMOUNT_RE = re.compile(r"[-+]?\d+(?:\.\d{1,2})?")


def parse_expense(text: str):
    """Extract (amount, description) from free text, or None if no amount found."""
    match = AMOUNT_RE.search(text.replace(",", ""))
    if not match:
        return None
    amount = float(match.group())
    if amount <= 0:
        return None
    description = (text[:match.start()] + text[match.end():]).strip()
    description = description.strip("$-: ").strip()
    if not description:
        description = "Uncategorized expense"
    return amount, description


def category_keyboard(expense_id: int, categories: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for i, cat in enumerate(categories, 1):
        row.append(InlineKeyboardButton(text=cat, callback_data=f"cat:{expense_id}:{cat}"))
        if i % 3 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def delete_keyboard(expense_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Delete", callback_data=f"del:{expense_id}")]
    ])


MENU_BUTTONS = {
    "log": "➕ Log",
    "summary": "📊 Summary",
    "recent": "📝 Recent",
    "categories": "📁 Categories",
    "undo": "↩️ Undo",
    "export": "📄 Export",
}


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    # is_persistent=False (the default) means this stays tucked behind the
    # grid-toggle icon next to the emoji button, instead of always being open.
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU_BUTTONS["log"]), KeyboardButton(text=MENU_BUTTONS["summary"])],
            [KeyboardButton(text=MENU_BUTTONS["recent"]), KeyboardButton(text=MENU_BUTTONS["categories"])],
            [KeyboardButton(text=MENU_BUTTONS["undo"]), KeyboardButton(text=MENU_BUTTONS["export"])],
        ],
        resize_keyboard=True,
        input_field_placeholder="Type an expense, e.g. coffee 5.50"
    )


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await db.ensure_default_categories(message.from_user.id)
    await message.answer(
        "👋 <b>Expense Tracker</b>\n\n"
        "Just send me a message like:\n"
        "<code>coffee 5.50</code> or <code>5.50 coffee</code>\n\n"
        "I'll log it and ask you to tag a category.\n\n"
        "Tap the grid icon next to the emoji button anytime for quick actions.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )


@dp.message(Command("categories"))
async def cmd_categories(message: Message):
    parts = message.text.split(maxsplit=1)
    new_cat = parts[1].strip() if len(parts) > 1 else None
    await show_or_add_category(message, new_cat)


async def show_or_add_category(message: Message, new_cat: str | None):
    user_id = message.from_user.id
    await db.ensure_default_categories(user_id)

    if new_cat:
        added = await db.add_category(user_id, new_cat)
        if added:
            await message.answer(f"✅ Added category: {new_cat}")
        else:
            await message.answer(f"'{new_cat}' already exists.")
        return

    cats = await db.get_categories(user_id)
    await message.answer(
        "📁 <b>Your categories:</b>\n" + "\n".join(f"• {c}" for c in cats) +
        "\n\nAdd a new one with: <code>/categories Groceries</code>",
        parse_mode="HTML"
    )


@dp.message(Command("summary"))
async def cmd_summary(message: Message):
    await send_combined_summary(message)


@dp.message(Command("today"))
async def cmd_today(message: Message):
    await send_summary(message, db.start_of_today(), "Today")


@dp.message(Command("week"))
async def cmd_week(message: Message):
    await send_summary(message, db.start_of_week(), "This week")


@dp.message(Command("month"))
async def cmd_month(message: Message):
    await send_summary(message, db.start_of_month(), "This month")


async def send_summary(message: Message, since, label: str):
    rows, total = await db.get_summary(message.from_user.id, since)
    if not rows:
        await message.answer(f"No expenses logged for {label.lower()} yet.")
        return
    lines = [f"📊 <b>{label}'s spending: ${total:.2f}</b>\n"]
    for cat, amount, count in rows:
        pct = (amount / total * 100) if total else 0
        lines.append(f"• {cat}: ${amount:.2f} ({count}x, {pct:.0f}%)")
    await message.answer("\n".join(lines), parse_mode="HTML")


async def send_combined_summary(message: Message):
    user_id = message.from_user.id
    periods = [
        (db.start_of_today(), "Today"),
        (db.start_of_week(), "This week"),
        (db.start_of_month(), "This month"),
    ]
    lines = ["📊 <b>Spending Summary</b>\n"]
    any_data = False
    for since, label in periods:
        rows, total = await db.get_summary(user_id, since)
        if rows:
            any_data = True
        lines.append(f"<b>{label}:</b> ${total:.2f}")
    if not any_data:
        await message.answer("No expenses logged yet.")
        return
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("undo"))
async def cmd_undo(message: Message):
    last = await db.get_last_expense(message.from_user.id)
    if not last:
        await message.answer("Nothing to undo.")
        return
    expense_id, amount, desc, cat, created_at = last
    await db.delete_expense(expense_id, message.from_user.id)
    await message.answer(f"🗑 Removed: ${amount:.2f} — {desc}")


@dp.message(Command("recent"))
async def cmd_recent(message: Message):
    rows = await db.get_recent(message.from_user.id, limit=10)
    if not rows:
        await message.answer("No expenses logged yet.")
        return
    for expense_id, amount, desc, cat, created_at in rows:
        cat_label = cat or "uncategorized"
        date_label = created_at[:10]
        await message.answer(
            f"${amount:.2f} — {desc} <i>({cat_label}, {date_label})</i>",
            parse_mode="HTML",
            reply_markup=delete_keyboard(expense_id)
        )


@dp.message(Command("export"))
async def cmd_export(message: Message):
    buf = await db.export_csv(message.from_user.id)
    file = BufferedInputFile(buf.getvalue().encode(), filename="expenses.csv")
    await message.answer_document(file, caption="📄 Your full expense history")


@dp.message(Command("log"))
async def cmd_log(message: Message):
    await message.answer(
        "💸 What did you spend on?\nE.g. <code>coffee 5.50</code>",
        parse_mode="HTML",
        reply_markup=ForceReply(input_field_placeholder="coffee 5.50")
    )


@dp.message(F.text == MENU_BUTTONS["log"])
async def btn_log(message: Message):
    await cmd_log(message)


@dp.message(F.text == MENU_BUTTONS["summary"])
async def btn_summary(message: Message):
    await send_combined_summary(message)


@dp.message(F.text == MENU_BUTTONS["recent"])
async def btn_recent(message: Message):
    await cmd_recent(message)


@dp.message(F.text == MENU_BUTTONS["undo"])
async def btn_undo(message: Message):
    await cmd_undo(message)


@dp.message(F.text == MENU_BUTTONS["categories"])
async def btn_categories(message: Message):
    await show_or_add_category(message, None)


@dp.message(F.text == MENU_BUTTONS["export"])
async def btn_export(message: Message):
    await cmd_export(message)


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_expense_text(message: Message):
    parsed = parse_expense(message.text)
    if not parsed:
        await message.answer(
            "I couldn't find an amount in that message. Try something like "
            "<code>coffee 5.50</code>",
            parse_mode="HTML"
        )
        return

    amount, description = parsed
    user_id = message.from_user.id
    await db.ensure_default_categories(user_id)

    expense_id = await db.add_expense(user_id, amount, description)
    categories = await db.get_categories(user_id)

    await message.answer(
        f"💸 Logged <b>${amount:.2f}</b> — {description}\nTag a category:",
        parse_mode="HTML",
        reply_markup=category_keyboard(expense_id, categories)
    )


@dp.callback_query(F.data.startswith("cat:"))
async def handle_category_choice(callback: CallbackQuery):
    _, expense_id, category = callback.data.split(":", 2)
    await db.set_category(int(expense_id), category)
    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ Tagged as {category}"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("del:"))
async def handle_delete(callback: CallbackQuery):
    _, expense_id = callback.data.split(":", 1)
    deleted = await db.delete_expense(int(expense_id), callback.from_user.id)
    if deleted:
        await callback.message.edit_text(callback.message.text + "\n\n🗑 Deleted")
    await callback.answer()


async def set_menu_button():
    """Registers the ☰ menu icon next to the text box with a command dropdown."""
    await bot.set_my_commands([
        BotCommand(command="log", description="Log a new expense"),
        BotCommand(command="summary", description="Today / week / month spending"),
        BotCommand(command="recent", description="Browse & delete recent entries"),
        BotCommand(command="categories", description="View/add categories"),
        BotCommand(command="undo", description="Remove your last entry"),
        BotCommand(command="export", description="Download all expenses as CSV"),
        BotCommand(command="today", description="Today's spending only"),
        BotCommand(command="week", description="This week's spending only"),
        BotCommand(command="month", description="This month's spending only"),
    ])


async def main():
    await db.init_db()
    await set_menu_button()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
