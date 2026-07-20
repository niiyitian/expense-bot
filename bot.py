"""
Money Tracker Telegram Bot (expenses + income + savings/debt)

Just send a message like "coffee 5.50" and the bot logs it as an expense.
"+50 sold shoes" logs money in. "save 2000", "withdraw 300 rent", and
"return 500" (or "repay 500") log savings/debt activity. Use /summary,
/savings, /export, /undo, /recent as needed.

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
    "save": "🏦 Save",
    "withdraw": "🏧 Withdraw",
    "repay": "📉 Repay Debt",
    "summary": "📊 Summary",
    "recent": "📝 Recent",
    "categories": "📁 Categories",
    "undo": "↩️ Undo",
    "export": "📄 Export",
}

# Prompt text markers used to tell which flow a reply belongs to
LOG_PROMPT_TEXT = "💸 What did you spend on?\nE.g. <code>coffee 5.50</code>"
MONEY_PROMPT_TEXT = "💰 What did you receive, and for what?\nE.g. <code>50 sold shoes</code>"
SAVE_PROMPT_TEXT = "🏦 How much are you putting into savings?\nE.g. <code>2000</code> or <code>2000 bonus</code>"
WITHDRAW_PROMPT_TEXT = "🏧 How much are you withdrawing from savings?\nE.g. <code>300 rent</code>"
REPAY_PROMPT_TEXT = "📉 How much are you repaying towards debt?\nE.g. <code>500</code>"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    # is_persistent=False (the default) means this stays tucked behind the
    # grid-toggle icon next to the emoji button, instead of always being open.
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU_BUTTONS["log"]), KeyboardButton(text=MENU_BUTTONS["money"])],
            [KeyboardButton(text=MENU_BUTTONS["save"]), KeyboardButton(text=MENU_BUTTONS["withdraw"])],
            [KeyboardButton(text=MENU_BUTTONS["repay"]), KeyboardButton(text=MENU_BUTTONS["summary"])],
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
        "👋 <b>Money Tracker</b>\n\n"
        "Just send me a message like:\n"
        "<code>coffee 5.50</code> or <code>5.50 coffee</code>\n\n"
        "I'll log it and ask you to tag a category.\n\n"
        "Got money in (sold something, got paid back)? Send it with a "
        "<code>+</code> in front, like <code>+50 sold shoes</code>.\n\n"
        "Putting money into savings, taking it out, or repaying debt? Just type "
        "it naturally: <code>save 2000</code>, <code>withdraw 300 rent</code>, "
        "<code>return 500</code> — or use the buttons.\n\n"
        "Tap the grid icon next to the emoji button anytime for quick actions.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )


@dp.message(Command("rename"))
async def cmd_rename(message: Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(
            "Usage: <code>/rename OldName NewName</code>\n"
            "E.g. <code>/rename Other Social</code>",
            parse_mode="HTML"
        )
        return

    old_name, new_name = parts[1].strip(), parts[2].strip()
    user_id = message.from_user.id
    await db.ensure_default_categories(user_id)

    ok = await db.rename_category(user_id, old_name, new_name)
    if ok:
        await message.answer(f"✅ Renamed '{old_name}' to '{new_name}' — past expenses updated too.")
    else:
        await message.answer(f"Couldn't find a category called '{old_name}'.")


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
        "\n\nAdd a new one with: <code>/categories Groceries</code>"
        "\nRename one with: <code>/rename Other Social</code>",
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

    saved, returned, withdrawn = await db.get_savings_totals(user_id)
    starting_debt = await db.get_starting_debt(user_id)
    savings_balance = saved - withdrawn
    debt_remaining = max(starting_debt - returned, 0)
    lines.append(f"\n🏦 <b>Savings balance:</b> ${savings_balance:.2f}")
    lines.append(f"🔴 <b>Debt remaining:</b> ${debt_remaining:.2f}")

    if not any_data and saved == 0 and returned == 0 and withdrawn == 0:
        await message.answer("Nothing logged yet.")
        return
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("savings"))
async def cmd_savings(message: Message):
    user_id = message.from_user.id
    saved, returned, withdrawn = await db.get_savings_totals(user_id)
    starting_debt = await db.get_starting_debt(user_id)
    savings_balance = saved - withdrawn
    debt_remaining = starting_debt - returned

    lines = [
        "🏦 <b>Savings & Debt</b>\n",
        f"💰 Total saved: ${saved:.2f}",
        f"🏧 Total withdrawn: ${withdrawn:.2f}",
        f"<b>Savings balance: ${savings_balance:.2f}</b>\n",
        f"📉 Total repaid: ${returned:.2f}",
        f"🧾 Starting debt: ${starting_debt:.2f}",
        f"<b>Debt remaining: ${max(debt_remaining, 0):.2f}</b>",
    ]
    if debt_remaining <= 0 and starting_debt > 0:
        lines.append("\n🎉 Debt fully paid off!")
        if debt_remaining < 0:
            lines.append(f"(Overpaid by ${abs(debt_remaining):.2f})")

    recent = await db.get_savings_recent(user_id, limit=5)
    if recent:
        lines.append("\n<b>Recent:</b>")
        icons = {"save": "🏦", "return": "📉", "withdraw": "🏧"}
        for _id, entry_type, amount, note, created_at in recent:
            note_suffix = f" — {note}" if note else ""
            lines.append(f"{icons[entry_type]} ${amount:.2f}{note_suffix} ({created_at[:10]})")

    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("setdebt"))
async def cmd_setdebt(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: <code>/setdebt 5340</code>", parse_mode="HTML")
        return
    try:
        amount = float(parts[1].replace(",", "").replace("$", ""))
    except ValueError:
        await message.answer("Please provide a valid number, e.g. <code>/setdebt 5340</code>", parse_mode="HTML")
        return
    await db.set_starting_debt(message.from_user.id, amount)
    await message.answer(f"✅ Starting debt set to ${amount:.2f}")


@dp.message(Command("undo"))
async def cmd_undo(message: Message):
    user_id = message.from_user.id
    last_expense = await db.get_last_expense(user_id)
    last_income = await db.get_last_income(user_id)
    last_savings = await db.get_last_savings_entry(user_id)

    candidates = []
    if last_expense:
        candidates.append(("expense", last_expense[4], last_expense))
    if last_income:
        candidates.append(("income", last_income[3], last_income))
    if last_savings:
        candidates.append(("savings", last_savings[4], last_savings))

    if not candidates:
        await message.answer("Nothing to undo.")
        return

    # Pick whichever was logged most recently (ISO timestamp strings compare correctly)
    kind, _, row = max(candidates, key=lambda c: c[1])

    if kind == "expense":
        expense_id, amount, desc, cat, created_at = row
        await db.delete_expense(expense_id, user_id)
        await message.answer(f"🗑 Removed: ${amount:.2f} — {desc}")
    elif kind == "income":
        income_id, amount, desc, created_at = row
        await db.delete_income(income_id, user_id)
        await message.answer(f"🗑 Removed income: ${amount:.2f} — {desc}")
    else:
        savings_id, entry_type, amount, note, created_at = row
        label = {"save": "savings", "return": "debt repayment", "withdraw": "withdrawal"}[entry_type]
        await db.delete_savings_entry(savings_id, user_id)
        await message.answer(f"🗑 Removed {label}: ${amount:.2f}")


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


@dp.message(Command("save"))
async def cmd_save(message: Message):
    await message.answer(
        SAVE_PROMPT_TEXT,
        parse_mode="HTML",
        reply_markup=ForceReply(input_field_placeholder="2000")
    )


@dp.message(Command("withdraw"))
async def cmd_withdraw(message: Message):
    await message.answer(
        WITHDRAW_PROMPT_TEXT,
        parse_mode="HTML",
        reply_markup=ForceReply(input_field_placeholder="300 rent")
    )


@dp.message(Command("repay"))
async def cmd_repay(message: Message):
    await message.answer(
        REPAY_PROMPT_TEXT,
        parse_mode="HTML",
        reply_markup=ForceReply(input_field_placeholder="500")
    )


@dp.message(F.text == MENU_BUTTONS["log"])
async def btn_log(message: Message):
    await cmd_log(message)


@dp.message(F.text == MENU_BUTTONS["money"])
async def btn_money(message: Message):
    await cmd_money(message)


@dp.message(F.text == MENU_BUTTONS["save"])
async def btn_save(message: Message):
    await cmd_save(message)


@dp.message(F.text == MENU_BUTTONS["withdraw"])
async def btn_withdraw(message: Message):
    await cmd_withdraw(message)


@dp.message(F.text == MENU_BUTTONS["repay"])
async def btn_repay(message: Message):
    await cmd_repay(message)


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


# Verbs recognized when typed directly, e.g. "save 2000", "withdraw 300 rent"
SAVE_WORDS = {"save", "saved", "saving"}
WITHDRAW_WORDS = {"withdraw", "withdrew", "withdrawing"}
RETURN_WORDS = {"return", "returned", "returning", "repay", "repaid", "pay", "paid"}
SAVINGS_VERB_RE = re.compile(
    r"^(" + "|".join(SAVE_WORDS | WITHDRAW_WORDS | RETURN_WORDS) + r")\s+(.*)$",
    re.IGNORECASE
)


def detect_entry_type(message: Message) -> tuple[str, str]:
    """Returns (entry_type, text_to_parse) where entry_type is one of
    'expense', 'income', 'save', 'withdraw', 'return'."""
    text = message.text.strip()

    # Reply to one of our prompts takes priority — bare "2000" replies work
    if message.reply_to_message and message.reply_to_message.text:
        rt = message.reply_to_message.text
        if rt.startswith("💸"):
            return "expense", text
        if rt.startswith("💰"):
            return "income", text.lstrip("+").strip()
        if rt.startswith("🏦"):
            return "save", text
        if rt.startswith("🏧"):
            return "withdraw", text
        if rt.startswith("📉"):
            return "return", text

    # Verb-led typed message, e.g. "save 2000 bonus"
    m = SAVINGS_VERB_RE.match(text)
    if m:
        verb, rest = m.group(1).lower(), m.group(2)
        if verb in SAVE_WORDS:
            return "save", rest
        if verb in WITHDRAW_WORDS:
            return "withdraw", rest
        return "return", rest

    # '+' prefix shortcut for income
    if text.startswith("+"):
        return "income", text.lstrip("+").strip()

    return "expense", text


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_money_text(message: Message):
    entry_type, text = detect_entry_type(message)

    if entry_type == "income":
        await handle_income_text(message, text)
        return
    if entry_type in ("save", "withdraw", "return"):
        await handle_savings_text(message, entry_type, text)
        return

    # entry_type == "expense"
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


async def handle_income_text(message: Message, text: str):
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


async def handle_savings_text(message: Message, entry_type: str, text: str):
    parsed = parse_expense(text)
    if not parsed:
        example = {"save": "2000", "withdraw": "300 rent", "return": "500"}[entry_type]
        await message.answer(
            f"I couldn't find an amount in that message. Try something like "
            f"<code>{example}</code>",
            parse_mode="HTML"
        )
        return

    amount, note = parsed
    if note == "Uncategorized expense":
        note = ""
    user_id = message.from_user.id
    await db.add_savings_entry(user_id, entry_type, amount, note)

    saved, returned, withdrawn = await db.get_savings_totals(user_id)
    starting_debt = await db.get_starting_debt(user_id)
    savings_balance = saved - withdrawn
    debt_remaining = max(starting_debt - returned, 0)

    if entry_type == "save":
        await message.answer(
            f"🏦 Saved <b>${amount:.2f}</b>\nSavings balance: ${savings_balance:.2f}",
            parse_mode="HTML"
        )
    elif entry_type == "withdraw":
        await message.answer(
            f"🏧 Withdrew <b>${amount:.2f}</b>\nSavings balance: ${savings_balance:.2f}",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"📉 Repaid <b>${amount:.2f}</b> towards debt\nDebt remaining: ${debt_remaining:.2f}",
            parse_mode="HTML"
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
    """Registers commands (for the '/' autocomplete) and explicitly reverts
    the chat menu button to default, so only the keyboard-toggle icon next
    to the emoji button shows — not the separate blue commands icon."""
    await bot.set_my_commands([
        BotCommand(command="log", description="Log a new expense"),
        BotCommand(command="money", description="Add money received (sales, transfers)"),
        BotCommand(command="save", description="Put money into savings"),
        BotCommand(command="withdraw", description="Withdraw money from savings"),
        BotCommand(command="repay", description="Repay towards debt"),
        BotCommand(command="savings", description="Savings balance & debt remaining"),
        BotCommand(command="setdebt", description="Set your starting debt amount"),
        BotCommand(command="summary", description="Today / week / month spending"),
        BotCommand(command="recent", description="Browse & delete recent entries"),
        BotCommand(command="categories", description="View/add categories"),
        BotCommand(command="rename", description="Rename a category (updates past expenses too)"),
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
