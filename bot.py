import json
import os
import logging
from collections import defaultdict
from datetime import time, datetime

from dotenv import load_dotenv

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

DATA_FILE = "data.json"


def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "total_days": 100,
            "chat_id": None,
            "participants": [],
            "history": []
        }
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "history" not in data:
        data["history"] = []

    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_history(data, action, name, details=""):
    data["history"].append({
        "time": now_str(),
        "action": action,
        "name": name,
        "details": details
    })


def find_participant(data, user_id=None, name=None):
    for p in data["participants"]:
        if user_id is not None and p.get("user_id") == user_id:
            return p
        if name is not None and p["name"].lower() == name.lower():
            return p
    return None


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    chat = update.effective_chat

    if chat.type == "private":
        return True

    member = await context.bot.get_chat_member(chat.id, user.id)
    return member.status in ("administrator", "creator")


async def require_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    ok = await is_admin(update, context)
    if not ok:
        await update.message.reply_text("Эта команда только для админа.")
        return False
    return True


def build_status_text(data):
    participants = data["participants"]
    total_days = data["total_days"]

    if not participants:
        return "Пока нет участников."

    grouped = defaultdict(list)
    for p in participants:
        grouped[p["current_day"]].append(p)

    lines = ["Челлендж: отжимания", ""]

    for day in sorted(grouped.keys(), reverse=True):
        lines.append(f"День {day}/{total_days}")
        for p in grouped[day]:
            mark = "✅" if p["done_today"] else "❌"
            lines.append(f"{p['name']} {mark}")
        lines.append("")

    return "\n".join(lines).strip()


def build_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Я сделал", callback_data="done")]]
    )


async def send_status(context: ContextTypes.DEFAULT_TYPE, prefix: str | None = None):
    data = load_data()

    if not data["chat_id"]:
        return

    text = build_status_text(data)
    if prefix:
        text = f"{prefix}\n\n{text}"

    await context.bot.send_message(
        chat_id=data["chat_id"],
        text=text,
        reply_markup=build_keyboard(),
    )


def next_day_logic(data):
    for p in data["participants"]:
        old_day = p["current_day"]

        if p["done_today"]:
            p["current_day"] += 1
            log_history(data, "advance", p["name"], f"{old_day} -> {p['current_day']}")
        else:
            p["current_day"] = max(1, p["current_day"] - 1)
            log_history(data, "rollback", p["name"], f"{old_day} -> {p['current_day']}")

        p["done_today"] = False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/bind — привязать чат\n"
        "/status — показать статус\n"
        "/add Имя — добавить участника\n"
        "/join Имя — привязать себя к участнику\n"
        "/remove Имя — удалить участника (админ)\n"
        "/done Имя — отметить вручную (админ)\n"
        "/setday Имя 48 — установить день (админ)\n"
        "/nextday — закрыть текущий день (админ)\n"
        "/list — список участников\n"
        "/rating — рейтинг\n"
        "/history Имя — история участника\n"
    )


async def bind_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    data["chat_id"] = update.effective_chat.id
    save_data(data)
    await update.message.reply_text("Чат привязан.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    await update.message.reply_text(build_status_text(data), reply_markup=build_keyboard())


async def add_participant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, context):
        return

    data = load_data()

    if not context.args:
        await update.message.reply_text("Пример: /add Егор")
        return

    name = " ".join(context.args).strip()

    if find_participant(data, name=name):
        await update.message.reply_text("Такой участник уже есть.")
        return

    data["participants"].append(
        {
            "name": name,
            "user_id": None,
            "username": None,
            "current_day": 1,
            "done_today": False,
        }
    )

    log_history(data, "add", name, "participant added")
    save_data(data)

    await update.message.reply_text(f"{name} добавлен.")
    await send_status(context)


async def join_participant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()

    if not context.args:
        await update.message.reply_text("Пример: /join Санек")
        return

    name = " ".join(context.args).strip()
    participant = find_participant(data, name=name)

    if not participant:
        await update.message.reply_text("Такого участника нет.")
        return

    user = update.effective_user

    existing = find_participant(data, user_id=user.id)
    if existing and existing["name"].lower() != name.lower():
        await update.message.reply_text(
            f"Ты уже привязан к участнику '{existing['name']}'."
        )
        return

    participant["user_id"] = user.id
    participant["username"] = user.username
    log_history(data, "join", name, f"user_id={user.id}")
    save_data(data)

    await update.message.reply_text(f"Готово. Ты привязан к участнику '{name}'.")


async def remove_participant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, context):
        return

    data = load_data()

    if not context.args:
        await update.message.reply_text("Пример: /remove Алена")
        return

    name = " ".join(context.args).strip()
    participant = find_participant(data, name=name)

    if not participant:
        await update.message.reply_text("Такого участника нет.")
        return

    data["participants"] = [p for p in data["participants"] if p["name"].lower() != name.lower()]
    log_history(data, "remove", name, "participant removed")
    save_data(data)

    await update.message.reply_text(f"{name} удален.")
    await send_status(context)


async def list_participants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()

    if not data["participants"]:
        await update.message.reply_text("Пока нет участников.")
        return

    lines = ["Участники:", ""]
    for p in data["participants"]:
        bind_status = "привязан" if p.get("user_id") else "не привязан"
        username = f" (@{p['username']})" if p.get("username") else ""
        lines.append(f"{p['name']}{username} — день {p['current_day']} — {bind_status}")

    await update.message.reply_text("\n".join(lines))


async def set_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, context):
        return

    data = load_data()

    if len(context.args) < 2:
        await update.message.reply_text("Пример: /setday Егор 48")
        return

    name = " ".join(context.args[:-1]).strip()

    try:
        day = int(context.args[-1])
    except ValueError:
        await update.message.reply_text("Последний аргумент должен быть числом.")
        return

    if day < 1:
        await update.message.reply_text("День не может быть меньше 1.")
        return

    participant = find_participant(data, name=name)
    if not participant:
        await update.message.reply_text(f"Участник '{name}' не найден.")
        return

    old_day = participant["current_day"]
    participant["current_day"] = day
    log_history(data, "setday", name, f"{old_day} -> {day}")
    save_data(data)

    await update.message.reply_text(f"{name}: установлен день {day}.")
    await send_status(context)


async def done_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, context):
        return

    data = load_data()

    if not context.args:
        await update.message.reply_text("Пример: /done Санек")
        return

    name = " ".join(context.args).strip()
    participant = find_participant(data, name=name)

    if not participant:
        await update.message.reply_text("Такого участника нет.")
        return

    if participant["done_today"]:
        await update.message.reply_text(f"{name} уже отмечен на сегодня.")
        return

    participant["done_today"] = True
    log_history(data, "done_manual", name, "marked done manually")
    save_data(data)

    await update.message.reply_text(f"{name} отмечен ✅")
    await send_status(context)


async def rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()

    if not data["participants"]:
        await update.message.reply_text("Пока нет участников.")
        return

    sorted_participants = sorted(
        data["participants"],
        key=lambda x: (-x["current_day"], x["name"].lower())
    )

    lines = ["🏆 Рейтинг:", ""]
    for i, p in enumerate(sorted_participants, start=1):
        lines.append(f"{i}. {p['name']} — день {p['current_day']}")

    await update.message.reply_text("\n".join(lines))


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()

    if not context.args:
        await update.message.reply_text("Пример: /history Санек")
        return

    name = " ".join(context.args).strip()

    items = [h for h in data["history"] if h["name"].lower() == name.lower()]
    if not items:
        await update.message.reply_text(f"История по '{name}' пустая.")
        return

    items = items[-15:]

    lines = [f"История: {name}", ""]
    for h in items:
        lines.append(f"{h['time']} — {h['action']} — {h['details']}")

    await update.message.reply_text("\n".join(lines))


async def next_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, context):
        return

    data = load_data()

    if not data["participants"]:
        await update.message.reply_text("Участников нет.")
        return

    next_day_logic(data)
    save_data(data)

    await update.message.reply_text("День закрыт. Новый открыт.")
    await send_status(context, prefix="Новый день челленджа.")


async def auto_next_day(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()

    if not data["participants"] or not data["chat_id"]:
        return

    next_day_logic(data)
    save_data(data)

    await send_status(context, prefix="Новый день челленджа.")


async def morning_status(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()

    if not data["participants"] or not data["chat_id"]:
        return

    await send_status(context, prefix="Доброе утро. Новый день челленджа.")


async def reminder(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()

    if not data["chat_id"]:
        return

    not_done = [p["name"] for p in data["participants"] if not p["done_today"]]
    if not not_done:
        return

    text = "🔥 Напоминание:\nНе сделали сегодня:\n\n" + "\n".join(not_done)
    await context.bot.send_message(chat_id=data["chat_id"], text=text)


async def done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    data = load_data()

    participant = find_participant(data, user_id=user.id)

    if not participant:
        await query.answer("Сначала привяжи себя через /join Имя", show_alert=True)
        return

    if participant["done_today"]:
        await query.answer("Ты уже отмечен на сегодня.")
        return

    participant["done_today"] = True
    log_history(data, "done_button", participant["name"], "marked done by button")
    save_data(data)

    await context.bot.send_message(
        chat_id=data["chat_id"],
        text=build_status_text(data),
        reply_markup=build_keyboard(),
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("ОШИБКА:", repr(context.error))


def main():
    if not BOT_TOKEN:
        raise ValueError("Не найден BOT_TOKEN в .env")

    print("Текущая папка:", os.getcwd())
    print("Путь к data.json:", os.path.abspath(DATA_FILE))

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(60)
        .read_timeout(60)
        .write_timeout(60)
        .pool_timeout(60)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bind", bind_chat))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("add", add_participant))
    app.add_handler(CommandHandler("join", join_participant))
    app.add_handler(CommandHandler("remove", remove_participant))
    app.add_handler(CommandHandler("list", list_participants))
    app.add_handler(CommandHandler("setday", set_day))
    app.add_handler(CommandHandler("done", done_manual))
    app.add_handler(CommandHandler("rating", rating))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("nextday", next_day))
    app.add_handler(CallbackQueryHandler(done_callback, pattern="^done$"))
    app.add_error_handler(error_handler)

    if app.job_queue is not None:
        app.job_queue.run_daily(auto_next_day, time=time(0, 5))
        app.job_queue.run_daily(reminder, time=time(22, 0))
        app.job_queue.run_daily(morning_status, time=time(8, 0))
        print("Планировщик включен.")
    else:
        print("Планировщик отключен.")

    print("Бот запущен...")
    app.run_polling(drop_pending_updates=True, bootstrap_retries=5)


if __name__ == "__main__":
    main()
