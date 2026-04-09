import json
import os
import logging
from collections import defaultdict
from datetime import time

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
        }
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_participant(data, user_id=None, name=None):
    for p in data["participants"]:
        if user_id is not None and p.get("user_id") == user_id:
            return p
        if name is not None and p["name"].lower() == name.lower():
            return p
    return None


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


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("ПОЛУЧЕНА КОМАНДА /status")
    data = load_data()
    await update.message.reply_text("Команда /status получена ботом")
    await update.message.reply_text(build_status_text(data), reply_markup=build_keyboard())

def next_day_logic(data):
    for p in data["participants"]:
        if p["done_today"]:
            p["current_day"] += 1
        else:
            p["current_day"] = max(1, p["current_day"] - 1)
        p["done_today"] = False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Команда /start")
    await update.message.reply_text(
        "Команды:\n"
        "/bind — привязать чат\n"
        "/status — показать статус\n"
        "/add Имя — добавить участника\n"
        "/setday Имя 48 — установить день\n"
        "/nextday — закрыть текущий день"
    )


async def bind_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Команда /bind")
    data = load_data()
    data["chat_id"] = update.effective_chat.id
    save_data(data)
    await update.message.reply_text("Чат привязан.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Команда /status")
    data = load_data()
    await update.message.reply_text(build_status_text(data), reply_markup=build_keyboard())


async def add_participant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Команда /add", context.args)
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
            "current_day": 1,
            "done_today": False,
        }
    )
    save_data(data)

    await update.message.reply_text(f"{name} добавлен.")
    await send_status(context)


async def set_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Команда /setday", context.args)
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
        names = ", ".join(p["name"] for p in data["participants"]) or "никого"
        await update.message.reply_text(
            f"Участник '{name}' не найден.\nСейчас есть: {names}"
        )
        return

    participant["current_day"] = day
    save_data(data)

    await update.message.reply_text(f"{name}: установлен день {day}.")
    await send_status(context)


async def next_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Команда /nextday")
    data = load_data()

    if not data["participants"]:
        await update.message.reply_text("Участников нет.")
        return

    next_day_logic(data)
    save_data(data)

    await update.message.reply_text("День закрыт. Новый открыт.")
    await send_status(context)


async def auto_next_day(context: ContextTypes.DEFAULT_TYPE):
    print("Авто /nextday")
    data = load_data()

    if not data["participants"] or not data["chat_id"]:
        return

    next_day_logic(data)
    save_data(data)

    await send_status(context)


async def reminder(context: ContextTypes.DEFAULT_TYPE):
    print("Напоминание")
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

    p = find_participant(data, user_id=user.id)

    # если не найден — пробуем привязать по имени
    if p is None:
        for participant in data["participants"]:
            if participant["name"] == user.first_name:
                p = participant
                p["user_id"] = user.id
                break

    if not p:
        await query.answer("Ты не найден в списке участников", show_alert=True)
        return

    # 👉 если уже нажал — не спамим
    if p["done_today"]:
        await query.answer("Ты уже отметил сегодня 👍")
        return

    # 👉 ставим галочку
    p["done_today"] = True
    save_data(data)

    # 🔥 ВАЖНО: отправляем НОВОЕ сообщение
    await context.bot.send_message(
        chat_id=data["chat_id"],
        text=build_status_text(data),
        reply_markup=build_keyboard(),
    )

    if not participant:
        await query.answer("Не понял, кто ты. Добавьте участника через /add Имя", show_alert=True)
        return

    if participant["done_today"]:
        await query.answer("Ты уже отмечен на сегодня.")
        return

    participant["done_today"] = True
    save_data(data)

    await send_status(context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("ОШИБКА:", context.error)


def main():
    if not BOT_TOKEN:
        raise ValueError("Не найден BOT_TOKEN в .env")

    print("Текущая папка:", os.getcwd())
    print("Путь к data.json:", os.path.abspath(DATA_FILE))

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bind", bind_chat))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("add", add_participant))
    app.add_handler(CommandHandler("setday", set_day))
    app.add_handler(CommandHandler("nextday", next_day))
    app.add_handler(CallbackQueryHandler(done_callback, pattern="^done$"))
    app.add_error_handler(error_handler)

    if app.job_queue is not None:
        app.job_queue.run_daily(auto_next_day, time=time(0, 5))
        app.job_queue.run_daily(reminder, time=time(22, 0))
        print("Планировщик включен.")
    else:
        print("Планировщик отключен.")

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
