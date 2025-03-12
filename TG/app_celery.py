from celery import Celery
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta
from aiogram import Bot
import asyncio

# Настройки Celery
celery_app = Celery(
    "bot_tasks",
    broker="redis://127.0.0.1:6379/0",  # Используем Redis как брокер
    backend="mongodb://127.0.0.1:27017/Telegram"  # Используем MongoDB как бэкенд
)

# Подключение к MongoDB
MONGO_URI = "mongodb://127.0.0.1:27017"
client = AsyncIOMotorClient(MONGO_URI)
db = client.Telegram
collection = db.Tg

# Токен бота (замените на ваш токен)
TOKEN = "7651886591:AAEAZfTe8f8ga-WJxcXo65mjBaYyixAd7fo"
bot = Bot(token=TOKEN)

# Задача для проверки просроченных задач и отправки уведомлений
@celery_app.task
def check_overdue_tasks_and_notify():
    """
    Проверяет все задачи на просроченность.
    Если задача просрочена, отправляет уведомление пользователю и продлевает дедлайн на 1 день.
    """
    loop = asyncio.get_event_loop()
    loop.run_until_complete(check_overdue_tasks_and_notify_async())

async def check_overdue_tasks_and_notify_async():
    print("Проверка просроченных задач...")
    users = await collection.find({}).to_list(None)
    for user in users:
        tasks = user.get("tasks", [])
        for task in tasks:
            deadline = datetime.strptime(task["deadline"], "%d-%m-%Y %H:%M")
            now = datetime.now()
            if task["status"] != "выполнено" and now > deadline:
                # Уведомление о просроченной задаче
                await bot.send_message(
                    chat_id=user["user_id"],
                    text=f"⚠️ Задача '{task['task_text']}' просрочена! Дедлайн продлен на 1 день."
                )

                # Продление дедлайна на 1 день
                new_deadline = deadline + timedelta(days=1)
                task["deadline"] = new_deadline.strftime("%d-%m-%Y %H:%M")

                # Обновление задачи в базе данных
                await collection.update_one(
                    {"user_id": user["user_id"], "tasks.task_text": task["task_text"]},
                    {"$set": {"tasks.$.deadline": task["deadline"]}}
                )
    print("Проверка просроченных задач завершена")

# Задача для отправки напоминания
@celery_app.task
def send_reminder(user_id, task_text, reminder_time):
    """
    Отправляет напоминание пользователю в указанное время.
    """
    loop = asyncio.get_event_loop()
    loop.run_until_complete(send_reminder_async(user_id, task_text, reminder_time))

async def send_reminder_async(user_id, task_text, reminder_time):
    await bot.send_message(
        chat_id=user_id,
        text=f"⏰ Напоминание: задача '{task_text}' должна быть выполнена к {reminder_time}."
    )

# Задача для проверки и отправки напоминаний
@celery_app.task
def check_and_send_reminders():
    """
    Периодическая задача для проверки и отправки напоминаний.
    """
    loop = asyncio.get_event_loop()
    loop.run_until_complete(check_and_send_reminders_async())

async def check_and_send_reminders_async():
    print("Проверка напоминаний...")
    users = await collection.find({}).to_list(None)
    now = datetime.now()

    for user in users:
        tasks = user.get("tasks", [])
        for task in tasks:
            if "reminder" in task:  # Проверяем, есть ли напоминание
                reminder_time = datetime.strptime(task["reminder"], "%d-%m-%Y %H:%M")
                if now >= reminder_time:  # Если время напоминания наступило
                    # Отправляем напоминание с указанием дедлайна
                    await bot.send_message(
                        chat_id=user["user_id"],
                        text=f"⏰ Напоминание: задача '{task['task_text']}' должна быть выполнена к {task['deadline']}."
                    )
                    # Удаляем напоминание после отправки
                    await collection.update_one(
                        {"user_id": user["user_id"], "tasks.task_text": task["task_text"]},
                        {"$unset": {"tasks.$.reminder": ""}}
                    )
    print("Проверка напоминаний завершена")

# Периодические задачи (Celery Beat)
celery_app.conf.beat_schedule = {
    "check-overdue-tasks": {
        "task": "app_celery.check_overdue_tasks_and_notify",
        "schedule": timedelta(minutes=1),  # Запускать каждую минуту
    },
    "check-and-send-reminders": {
        "task": "app_celery.check_and_send_reminders",
        "schedule": timedelta(minutes=1),  # Запускать каждую минуту
    },
}
