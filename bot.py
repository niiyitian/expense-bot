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
    BufferedInputFile, BotCommand, ForceReply, ReplyKeyboardMarkup, KeyboardButton,
    MenuButtonDefault
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
    "money": "💰 Add Money",
    "summary": "📊 Summary",
    "recent": "📝 Recent",
    "categories": "📁 Categories",
    "undo": "↩️ Undo",
    "export": "📄 Export",
}

# Prompt text markers used to tell an expense reply apart from an income reply
LOG_PROMPT_TEXT = "💸 What did you spend on?\nE.g. <code>coffee 5.50</code>"
MONEY_PROMPT_TEXT = "💰 What did you receive, and for what?\nE.g. <code>50 sold shoes</code>"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    # is_persistent=False (the default) means this stays tucked behind the
    # grid-toggle icon next to the emoji button, instead of always being open.
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU_BUTTONS["log"]), KeyboardButton(text=MENU_BUTTONS["money"])],
            [KeyboardButton(text=MENU_BUTTONS["summary"]), KeyboardButton(text=MENU_BUTTONS["recent"])],
            [KeyboardButton(text=MENU_BUTTONS["categories"]), KeyboardButton(text=MENU_BUTTONS["undo"])],
            [KeyboardButton(text=MENU_BUTTONS["export"])],
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
        "Got money in (sold something, got paid back)? Send it with a "
        "<code>+</code> in front, like <code>+50 sold shoes</code>, or use "
        "the 💰 Add Money button.\n\n"
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
    income_total = await db.get_income_total(message.from_user.id, since)
    if not rows and not income_total:
        await message.answer(f"Nothing logged for {label.lower()} yet.")
        return
    lines = [f"📊 <b>{label}</b>\n"]
    lines.append(f"💸 Spent: ${total:.2f}")
    for cat, amount, count in rows:
        pct = (amount / total * 100) if total else 0
        lines.append(f"   • {cat}: ${amount:.2f} ({count}x, {pct:.0f}%)")
    lines.append(f"\n💰 Received: ${income_total:.2f}")
    lines.append(f"\n<b>Net: ${income_total - total:.2f}</b>")
    await message.answer("\n".join(lines), parse_mode="HTML")


async def send_combined_summary(message: Message):
    user_id = message.from_user.id
    periods = [
        (db.start_of_today(), "Today"),
        (db.start_of_week(), "This week"),
        (db.start_of_month(), "This month"),
    ]
    lines = ["📊 <b>Summary</b>\n"]
    any_data = False
    for since, label in periods:
        rows, total = await db.get_summary(user_id, since)
        income_total = await db.get_income_total(user_id, since)
        if rows or income_total:
            any_data = True
        net = income_total - total
        lines.append(f"<b>{label}:</b> spent ${total:.2f}, received ${income_total:.2f}, net ${net:.2f}")
    if not any_data:
        await message.answer("Nothing logged yet.")
        return
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("undo"))
async def cmd_undo(message: Message):
    user_id = message.from_user.id
    last_expense = await db.get_last_expense(user_id)
    last_income = await db.get_last_income(user_id)

    if not last_expense and not last_income:
        await message.answer("Nothing to undo.")
        return

    # Compare timestamps (both are ISO strings, so string comparison works) to
    # find whichever was logged most recently, expense or income.
    if last_income and (not last_expense or last_income[3] > last_expense[4]):
        income_id, amount, desc, created_at = last_income
        await db.delete_income(income_id, user_id)
        await message.answer(f"🗑 Removed income: ${amount:.2f} — {desc}")
    else:
        expense_id, amount, desc, cat, created_at = last_expense
        await db.delete_expense(expense_id, user_id)
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
        LOG_PROMPT_TEXT,
        parse_mode="HTML",
        reply_markup=ForceReply(input_field_placeholder="coffee 5.50")
    )


@dp.message(Command("money"))
async def cmd_money(message: Message):
    await message.answer(
        MONEY_PROMPT_TEXT,
        parse_mode="HTML",
        reply_markup=ForceReply(input_field_placeholder="50 sold shoes")
    )


@dp.message(F.text == MENU_BUTTONS["log"])
async def btn_log(message: Message):
    await cmd_log(message)


@dp.message(F.text == MENU_BUTTONS["money"])
async def btn_money(message: Message):
    await cmd_money(message)


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


def is_income_message(message: Message) -> bool:
    if message.text.strip().startswith("+"):
        return True
    if message.reply_to_message and message.reply_to_message.text:
        return message.reply_to_message.text.startswith("💰")
    return False


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_expense_text(message: Message):
    if is_income_message(message):
        await handle_income_text(message)
        return

    text = message.text.lstrip("+").strip()
    parsed = parse_expense(text)
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


async def handle_income_text(message: Message):
    text = message.text.lstrip("+").strip()
    parsed = parse_expense(text)
    if not parsed:
        await message.answer(
            "I couldn't find an amount in that message. Try something like "
            "<code>50 sold shoes</code>",
            parse_mode="HTML"
        )
        return

    amount, description = parsed
    if description == "Uncategorized expense":
        description = "Income"
    user_id = message.from_user.id
    await db.add_income(user_id, amount, description)
    await message.answer(f"💰 Added <b>${amount:.2f}</b> — {description}", parse_mode="HTML")


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
    """Registers commands (for the '/' autocomplete) and explicitly reverts
    the chat menu button to default, so only the keyboard-toggle icon next
    to the emoji button shows — not the separate blue commands icon."""
    await bot.set_my_commands([
        BotCommand(command="log", description="Log a new expense"),
        BotCommand(command="money", description="Add money received (sales, transfers)"),
        BotCommand(command="summary", description="Today / week / month spending"),
        BotCommand(command="recent", description="Browse & delete recent entries"),
        BotCommand(command="categories", description="View/add categories"),
        BotCommand(command="undo", description="Remove your last entry"),
        BotCommand(command="export", description="Download all expenses as CSV"),
        BotCommand(command="today", description="Today's spending only"),
        BotCommand(command="week", description="This week's spending only"),
        BotCommand(command="month", description="This month's spending only"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonDefault())


async def main():
    await db.init_db()
    await set_menu_button()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
