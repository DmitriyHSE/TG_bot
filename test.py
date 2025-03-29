import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import motor.motor_asyncio
from datetime import datetime
from collections import Counter
from celery import Celery
from app_celery import check_overdue_tasks_and_notify
from app_celery import send_reminder

TOKEN = "7651886591:AAEAZfTe8f8ga-WJxcXo65mjBaYyixAd7fo"

MONGO_URI = "mongodb://localhost:27017"
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)

db = client.Telegram
collection = db.Tg

celery_app = Celery(
    "bot_tasks",
    broker="redis://localhost:6379/0",
    backend="mongodb://localhost:27017/Telegram"
)

async def check_connection():
    try:
        await client.admin.command("ping")
        print("✅ Подключение к MongoDB успешно!")
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")

# Создание бота и диспетчера
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

check_overdue_tasks_and_notify.delay()

# Состояния для FSM
class TaskForm(StatesGroup):
    waiting_for_task = State()
    waiting_for_deadline_date = State()
    waiting_for_deadline_time = State()
    waiting_for_notes = State()
    waiting_for_notes_media = State()
    waiting_for_edit_media = State()
    waiting_for_date_to_delete = State()
    waiting_for_new_task_text = State()
    waiting_for_new_deadline_date = State()
    waiting_for_new_deadline_time = State()
    waiting_for_new_notes = State()
    waiting_for_reminder_date = State()
    waiting_for_reminder_time = State()

# Функция получения списка дел из базы данных для конкретного пользователя
async def get_todo_list(user_id):
    user = await collection.find_one({"user_id": user_id})
    if user and "tasks" in user:
        return user["tasks"]
    return []

async def get_sorted_todo_list(user_id):
    tasks = await get_todo_list(user_id)

    # Обновляем статусы задач перед сортировкой
    updated_tasks = []
    for task in tasks:
        updated_task = await update_task_status(task)
        updated_tasks.append(updated_task)

    # Сортируем задачи по статусу и дедлайну
    def sort_key(task):
        status_order = {"в процессе": 0, "просрочено": 1, "выполнено": 2}
        deadline = datetime.strptime(task["deadline"], "%d-%m-%Y %H:%M")
        return (status_order.get(task["status"], 3), deadline)

    sorted_tasks = sorted(updated_tasks, key=sort_key)

    return sorted_tasks

# Функция добавления задачи в базу данных
async def add_task_to_db(user_id, username, task_text, deadline, notes="", notes_media=None):
    if notes_media is None:
        notes_media = []
    try:
        await collection.update_one(
            {"user_id": user_id},
            {
                "$setOnInsert": {"user_id": user_id, "username": username},
                "$push": {
                    "tasks": {
                        "task_text": task_text,
                        "deadline": deadline,
                        "notes": notes,
                        "notes_media": notes_media,  # Добавляем медиафайлы
                        "status": "в процессе"
                    }
                }
            },
            upsert=True
        )
        print(f"Задача добавлена в базу данных: user_id={user_id}, username={username}, task={task_text}, deadline={deadline}, notes={notes}, notes_media={notes_media}")
    except Exception as e:
        print(f"Ошибка при добавлении задачи в базу данных: {e}")

# Функция обновления статуса задачи
async def update_task_status(task):
    try:
        deadline = datetime.strptime(task["deadline"], "%d-%m-%Y %H:%M")
        now = datetime.now()
        if task["status"] != "выполнено":  # Если задача не выполнена
            if now > deadline:
                task["status"] = "просрочено"
    except ValueError as e:
        print(f"Ошибка при преобразовании даты: {e}")
    return task

# Клавиатура списка дел
async def create_todo_keyboard(tasks):
    buttons = []
    for task in tasks:
        if isinstance(task, dict):
            task_text = task.get("task_text")
            if task_text:
                buttons.append([KeyboardButton(text=task_text)])
    buttons.append([KeyboardButton(text="Добавление задачи")])
    buttons.append([KeyboardButton(text="Удаление дел по дате")])
    buttons.append([KeyboardButton(text="Назад в меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

# Клавиатура главного меню
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[[
        KeyboardButton(text="Список дел")
    ],
    [
        KeyboardButton(text="Статистика")
    ]],
    resize_keyboard=True
)

# Обработчик команды /start
@dp.message(CommandStart())
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username

    # Проверяем, есть ли пользователь в базе данных
    user = await collection.find_one({"user_id": user_id})

    if user is None:
        # Если пользователя нет, добавляем его, сохраняя порядок полей
        new_user = {"user_id": user_id, "username": username}
        await collection.insert_one(new_user)
        print(f"Пользователь {username} с ID {user_id} добавлен в базу данных.")
    else:
        print(f"Пользователь {username} с ID {user_id} уже существует в базе данных.")

    await message.answer("Привет! Выберите действие:", reply_markup=main_keyboard)

# Обработчик кнопки "Показать список дел"
@dp.message(lambda message: message.text == "Список дел")
async def show_todo_list(message: types.Message):
    user_id = message.from_user.id
    tasks = await get_sorted_todo_list(user_id)  # Используем отсортированный список задач

    if tasks:
        task_list_text = "Ваши задачи:\n"
        for task_data in tasks:
            if isinstance(task_data, dict):
                task_text = task_data.get('task_text')
                deadline_str = task_data.get('deadline')
                status = task_data.get('status', 'в процессе')

                # Определяем смайлик для статуса
                status_emoji = {
                    "в процессе": "🟡",
                    "выполнено": "✅",
                    "просрочено": "❌"
                }.get(status, "🟡")

                if task_text and deadline_str:
                    try:
                        deadline = datetime.strptime(deadline_str, "%d-%m-%Y %H:%M")
                        now = datetime.now()
                        time_left = deadline - now
                        days = time_left.days
                        hours, remainder = divmod(time_left.seconds, 3600)
                        minutes = remainder // 60

                        time_left_str = f"{days} дней, {hours} часов, {minutes} минут"

                        task_list_text += f"<b>{status_emoji} Задача:</b> {task_text}\n"
                        task_list_text += f"<b>Дедлайн:</b> {deadline_str}\n"
                        if time_left.days < 0 or minutes < 0 or hours < 0:
                            task_list_text += f"<b>Просрочена!</b>\n"
                        else:
                            task_list_text += f"<b>Осталось:</b> {time_left_str}\n"
                        task_list_text += "------\n"

                    except ValueError as e:
                        print(f"Ошибка при преобразовании даты: {e}")
                        task_list_text += f"Ошибка при отображении дедлайна\n"

        todo_keyboard = await create_todo_keyboard(tasks)
        await message.answer(task_list_text, reply_markup=todo_keyboard, parse_mode="HTML")
    else:
        empty_list_keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Добавление задачи")],
                [KeyboardButton(text="Назад в меню")]
            ],
            resize_keyboard=True
        )
        await message.answer("Список задач пуст.", reply_markup=empty_list_keyboard, parse_mode="HTML")

# Асинхронная функция для проверки, является ли сообщение задачей
async def is_task_message(message: types.Message) -> bool:
    user_id = message.from_user.id
    tasks = await get_todo_list(user_id)
    return message.text in [task.get("task_text") for task in tasks]

@dp.message(is_task_message)
async def show_task_details(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    tasks = await get_todo_list(user_id)
    task_text = message.text

    for task in tasks:
        if task.get("task_text") == task_text:
            # Обновляем статус задачи перед отображением
            task = await update_task_status(task)

            deadline_str = task.get("deadline")
            notes = task.get("notes", "Примечаний нет.")
            notes_media = task.get("notes_media", [])  # Получаем медиафайлы
            status = task.get("status", "в процессе")
            status_emoji = {
                "в процессе": "🟡",
                "выполнено": "✅",
                "просрочено": "❌"
            }.get(status, "🟡")

            try:
                deadline = datetime.strptime(deadline_str, "%d-%m-%Y %H:%M")
                now = datetime.now()
                time_left = deadline - now
                days = time_left.days
                hours, remainder = divmod(time_left.seconds, 3600)
                minutes = remainder // 60
                time_left_str = f"{days} дней, {hours} часов, {minutes} минут"

                # Формируем текст задачи
                response_text = f"<b>{status_emoji} Задача:</b> {task_text}\n"
                response_text += f"<b>Дедлайн:</b> {deadline_str}\n"
                if time_left.days < 0 or minutes < 0 or hours < 0:
                    response_text += f"<b>Просрочена!</b>\n"
                else:
                    response_text += f"<b>Осталось:</b> {time_left_str}\n"
                response_text += f"<b>Примечания:</b> {notes}\n"

                # Отправляем описание задачи
                await message.answer(response_text, parse_mode="HTML")

                # Отправляем прикрепленные файлы (если они есть)
                if notes_media:
                    for media in notes_media:
                        if media["type"] == "photo":
                            await message.answer_photo(media["file_id"])
                        elif media["type"] == "document":
                            await message.answer_document(media["file_id"])

            except ValueError as e:
                print(f"Ошибка при преобразовании даты: {e}")
                response_text = f"<b>{status_emoji} {task_text}</b>\n"
                response_text += f"<b>Дедлайн:</b> Ошибка при отображении дедлайна\n"
                response_text += f"<b>Примечания:</b> {notes}\n"
                await message.answer(response_text, parse_mode="HTML")

            # Сохраняем текст задачи в состоянии
            await state.update_data(task_to_delete=task_text)
            # Добавляем кнопки для управления статусом и изменения задачи
            if task.get("status") in ["в процессе", "выполнено"]:
                markup = ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text="Задача выполнена")],
                        [KeyboardButton(text="Возврат задачу в ожидание")] if task.get("status") == "выполнено" else [],
                        [KeyboardButton(text="Удаление задачи")],
                        [KeyboardButton(text="Изменение названия задачи")],
                        [KeyboardButton(text="Изменение дедлайна задачи")],
                        [KeyboardButton(text="Изменение примечания задачи")],
                        [KeyboardButton(text="Изменить прикреплённые файлы")],  # Новая кнопка
                        [KeyboardButton(text="Напоминание")],
                        [KeyboardButton(text="Назад к списку задач")]
                    ],
                    resize_keyboard=True
                )
            else:
                markup = ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text="Удаление задачи")],
                        [KeyboardButton(text="Назад к списку задач")]
                    ],
                    resize_keyboard=True
                )
            await message.answer("Выберите действие:", reply_markup=markup)
            break
    else:
        await message.answer("Задача не найдена.", reply_markup=main_keyboard)

# Обработчик для изменения статуса задачи
@dp.message(lambda message: message.text == "Задача выполнена")
async def mark_task_as_done(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await state.get_data()
    task_text = user_data.get("task_to_delete")

    if task_text:
        # Получаем задачу из базы данных
        user = await collection.find_one({"user_id": user_id, "tasks.task_text": task_text})
        task = next((t for t in user["tasks"] if t["task_text"] == task_text), None)

        if task:
            # Проверяем, не просрочена ли задача
            deadline = datetime.strptime(task["deadline"], "%d-%m-%Y %H:%M")
            now = datetime.now()
            if now > deadline:
                await message.answer("❌ Невозможно отметить просроченную задачу как выполненную.")
                return

            # Обновляем статус задачи в базе данных
            await collection.update_one(
                {"user_id": user_id, "tasks.task_text": task_text},
                {"$set": {"tasks.$.status": "выполнено"}}
            )
            await message.answer(f"Задача '{task_text}' отмечена как выполненная ✅.")

            # Возвращаем пользователя к списку задач
            await show_todo_list(message)
        else:
            await message.answer("Задача не найдена.", reply_markup=main_keyboard)
    else:
        await message.answer("Задача не найдена.", reply_markup=main_keyboard)

# Обработчик для изменения статуса задачи с "выполнено" на "в ожидании"
@dp.message(lambda message: message.text == "Возврат задачу в ожидание")
async def mark_task_as_pending(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await state.get_data()
    task_text = user_data.get("task_to_delete")

    if task_text:
        # Обновляем статус задачи в базе данных
        await collection.update_one(
            {"user_id": user_id, "tasks.task_text": task_text},
            {"$set": {"tasks.$.status": "в процессе"}}
        )
        await message.answer(f"Задача '{task_text}' возвращена в ожидание 🟡.")

        # Возвращаем пользователя к списку задач
        await show_todo_list(message)
    else:
        await message.answer("Задача не найдена.", reply_markup=main_keyboard)

# Обработчик для удаления задачи
@dp.message(lambda message: message.text == "Удаление задачи")
async def delete_task(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await state.get_data()
    task_text = user_data.get("task_to_delete")

    if task_text:
        # Удаляем задачу из базы данных
        await collection.update_one(
            {"user_id": user_id},
            {"$pull": {"tasks": {"task_text": task_text}}}
        )
        await message.answer(f"Задача '{task_text}' удалена 🗑️.")

        # Возвращаем пользователя к списку задач
        await show_todo_list(message)
    else:
        await message.answer("Задача не найдена.", reply_markup=main_keyboard)

# Обработчик для возврата к списку задач
@dp.message(lambda message: message.text == "Назад к списку задач")
async def back_to_tasks(message: types.Message):
    await show_todo_list(message)

# Обработчик кнопки "Добавить задачу"
@dp.message(lambda message: message.text == "Добавление задачи")
async def add_task(message: types.Message, state: FSMContext):
    await message.answer("Введите текст задачи:")
    await state.set_state(TaskForm.waiting_for_task)

# Обработчик для сохранения задачи
@dp.message(TaskForm.waiting_for_task)
async def get_task_text(message: types.Message, state: FSMContext):
    task_text = message.text
    await state.update_data(task_text=task_text)
    await message.answer("Введите дату дедлайна в формате ДД-ММ-ГГГГ:")
    await state.set_state(TaskForm.waiting_for_deadline_date)

# Обработчик для получения даты дедлайна
@dp.message(TaskForm.waiting_for_deadline_date)
async def get_deadline_date(message: types.Message, state: FSMContext):
    try:
        deadline_date = message.text
        deadline_datetime = datetime.strptime(deadline_date, "%d-%m-%Y")
        now = datetime.now()
        if deadline_datetime.date() < now.date():
            await message.answer("❌ Нельзя выбрать дату из прошлого. Пожалуйста, введите корректную дату в формате ДД-ММ-ГГГГ:")
            return
        await state.update_data(deadline_date=deadline_date)
        await message.answer("Введите время дедлайна в формате ЧЧ:ММ (24-часовой формат):")
        await state.set_state(TaskForm.waiting_for_deadline_time)
    except ValueError:
        await message.answer("❌ НевеФрный формат даты. Пожалуйста, используйте формат ДД-ММ-ГГГГ.")

# Обработчик для получения времени дедлайна
@dp.message(TaskForm.waiting_for_deadline_time)
async def get_deadline_time(message: types.Message, state: FSMContext):
    try:
        deadline_time = message.text
        datetime.strptime(deadline_time, "%H:%M")  # Проверка формата времени
        user_data = await state.get_data()
        task_text = user_data.get('task_text')
        deadline_date = user_data.get('deadline_date')

        # Объединяем дату и время в строку
        deadline_str = f"{deadline_date} {deadline_time}"
        deadline = datetime.strptime(deadline_str, "%d-%m-%Y %H:%M")

        # Проверяем, что дедлайн не в прошлом
        now = datetime.now()
        if deadline < now:
            await message.answer("❌ Нельзя выбрать время из прошлого. Пожалуйста, введите корректное время в формате ЧЧ:ММ:")
            return

        await state.update_data(deadline=deadline_str)
        await message.answer("Введите примечания к задаче (или нажмите /skip, чтобы пропустить):")
        await state.set_state(TaskForm.waiting_for_notes)

    except ValueError:
        await message.answer("❌ Неверный формат времени. Пожалуйста, используйте формат ЧЧ:ММ (24-часовой формат).")


@dp.message(lambda message: message.text == "Изменение дедлайна задачи")
async def change_deadline(message: types.Message, state: FSMContext):
    await message.answer("Введите новую дату дедлайна в формате ДД-ММ-ГГГГ:")
    await state.set_state(TaskForm.waiting_for_new_deadline_date)


@dp.message(TaskForm.waiting_for_new_deadline_date)
async def get_new_deadline_date(message: types.Message, state: FSMContext):
    try:
        new_deadline_date = message.text
        deadline_datetime = datetime.strptime(new_deadline_date, "%d-%m-%Y")
        now = datetime.now()
        if deadline_datetime.date() < now.date():
            await message.answer(
                "❌ Нельзя выбрать дату из прошлого. Пожалуйста, введите корректную дату в формате ДД-ММ-ГГГГ:")
            return
        await state.update_data(new_deadline_date=new_deadline_date)
        await message.answer("Введите новое время дедлайна в формате ЧЧ:ММ (24-часовой формат):")
        await state.set_state(TaskForm.waiting_for_new_deadline_time)
    except ValueError:
        await message.answer("❌ Неверный формат даты. Пожалуйста, используйте формат ДД-ММ-ГГГГ.")


@dp.message(TaskForm.waiting_for_new_deadline_time)
async def get_new_deadline_time(message: types.Message, state: FSMContext):
    try:
        new_deadline_time = message.text
        datetime.strptime(new_deadline_time, "%H:%M")  # Проверка формата времени
        user_data = await state.get_data()
        task_text = user_data.get('task_to_delete')
        new_deadline_date = user_data.get('new_deadline_date')

        # Объединяем дату и время в строку
        new_deadline_str = f"{new_deadline_date} {new_deadline_time}"
        new_deadline = datetime.strptime(new_deadline_str, "%d-%m-%Y %H:%M")

        # Проверяем, что дедлайн не в прошлом
        now = datetime.now()
        if new_deadline < now:
            await message.answer(
                "❌ Нельзя выбрать время из прошлого. Пожалуйста, введите корректное время в формате ЧЧ:ММ:")
            return

        user_id = message.from_user.id

        # Обновляем дедлайн задачи в базе данных
        await collection.update_one(
            {"user_id": user_id, "tasks.task_text": task_text},
            {"$set": {"tasks.$.deadline": new_deadline_str}}
        )

        await message.answer(f"Дедлайн задачи '{task_text}' успешно изменен на {new_deadline_str}.")
        await state.clear()
        await show_todo_list(message)

    except ValueError:
        await message.answer("❌ Неверный формат времени. Пожалуйста, используйте формат ЧЧ:ММ (24-часовой формат).")

@dp.message(TaskForm.waiting_for_notes)
async def get_notes(message: types.Message, state: FSMContext):
    if message.text == "/skip":
        await state.update_data(notes="")  # Устанавливаем пустое примечание
        await message.answer("Примечания пропущены. Вы можете прикрепить файлы или нажмите /skip для завершения.")
        await state.set_state(TaskForm.waiting_for_notes_media)  # Переходим к прикреплению файлов
    else:
        await state.update_data(notes=message.text)  # Сохраняем примечание
        await message.answer("Вы можете прикрепить фотографии или файлы к примечаниям. Если не хотите, нажмите /skip.")
        await state.set_state(TaskForm.waiting_for_notes_media)  # Переходим к прикреплению файлов

@dp.message(lambda message: message.text == "Изменение примечания задачи")
async def change_notes(message: types.Message, state: FSMContext):
    await message.answer("Введите новое примечание для задачи:")
    await state.set_state(TaskForm.waiting_for_new_notes)

@dp.message(TaskForm.waiting_for_new_notes)
async def get_new_notes(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    task_text = user_data.get('task_to_delete')
    user_id = message.from_user.id

    # Обновляем примечание задачи в базе данных
    await collection.update_one(
        {"user_id": user_id, "tasks.task_text": task_text},
        {"$set": {"tasks.$.notes": message.text}}
    )

    await message.answer(f"Примечание задачи '{task_text}' успешно изменено.")
    await state.clear()
    await show_todo_list(message)

# Обработчик для получения медиафайлов
@dp.message(TaskForm.waiting_for_notes_media, lambda message: message.photo or message.document)
async def get_notes_media(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    notes_media = user_data.get("notes_media", [])

    if message.photo:
        # Сохраняем фото
        file_id = message.photo[-1].file_id
        notes_media.append({"type": "photo", "file_id": file_id})
    elif message.document:
        # Сохраняем документ
        file_id = message.document.file_id
        notes_media.append({"type": "document", "file_id": file_id})

    await state.update_data(notes_media=notes_media)
    await message.answer("Файл прикреплен. Вы можете добавить еще файлы или нажмите /skip для завершения.")

@dp.message(TaskForm.waiting_for_notes_media, lambda message: message.text == "/skip")
async def skip_notes_media(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    task_text = user_data.get('task_text')
    deadline = user_data.get('deadline')
    notes = user_data.get('notes', '')  # Получаем примечание (может быть пустым)
    notes_media = user_data.get('notes_media', [])  # Получаем медиафайлы (может быть пустым)

    user_id = message.from_user.id
    username = message.from_user.username

    # Сохраняем задачу в базу данных
    await collection.update_one(
        {"user_id": user_id},
        {
            "$setOnInsert": {"user_id": user_id, "username": username},
            "$push": {
                "tasks": {
                    "task_text": task_text,
                    "deadline": deadline,
                    "notes": notes,  # Сохраняем примечание (даже если оно пустое)
                    "notes_media": notes_media,  # Сохраняем медиафайлы (даже если их нет)
                    "status": "в процессе"
                }
            }
        },
        upsert=True
    )

    await message.answer(f"Задача '{task_text}' с дедлайном '{deadline}' успешно добавлена!")
    await state.clear()  # Очищаем состояние
    await show_todo_list(message)  # Возвращаем пользователя к списку задач

# Обработчик кнопки "Удалить дела по дате"
@dp.message(lambda message: message.text == "Удаление дел по дате")
async def delete_tasks_by_date(message: types.Message, state: FSMContext):
    await message.answer("Введите дату в формате ДД-ММ-ГГГГ для удаления задач:")
    await state.set_state(TaskForm.waiting_for_date_to_delete)

# Обработчик для удаления задач по дате
@dp.message(TaskForm.waiting_for_date_to_delete)
async def delete_tasks_by_date_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    date_to_delete = message.text

    try:
        # Преобразуем введенную дату в формат datetime
        date_to_delete = datetime.strptime(date_to_delete, "%d-%m-%Y").date()

        # Удаляем задачи с указанной датой
        await collection.update_one(
            {"user_id": user_id},
            {"$pull": {"tasks": {"deadline": {"$regex": f"{date_to_delete.strftime('%d-%m-%Y')}"}}}}
        )
        await message.answer(f"Все задачи на {date_to_delete.strftime('%d-%m-%Y')} удалены 🗑️.")
    except ValueError:
        await message.answer("❌ Неверный формат даты. Пожалуйста, используйте формат ДД-ММ-ГГГГ.")

    await state.clear()
    await show_todo_list(message)

# Обработчик для кнопки "Изменение названия задачи"
@dp.message(lambda message: message.text == "Изменение названия задачи")
async def change_task_name(message: types.Message, state: FSMContext):
    await message.answer("Введите новое название задачи:")
    await state.set_state(TaskForm.waiting_for_new_task_text)

# Обработчик для получения нового названия задачи
@dp.message(TaskForm.waiting_for_new_task_text)
async def get_new_task_name(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    old_task_text = user_data.get("task_to_delete")  # Старое название задачи
    new_task_text = message.text  # Новое название задачи
    user_id = message.from_user.id

    if not old_task_text:
        await message.answer("❌ Ошибка: задача не найдена.")
        await state.clear()
        return

    # Обновляем название задачи в базе данных
    await collection.update_one(
        {"user_id": user_id, "tasks.task_text": old_task_text},
        {"$set": {"tasks.$.task_text": new_task_text}}
    )

    await message.answer(f"Название задачи успешно изменено с '{old_task_text}' на '{new_task_text}'.")
    await state.clear()
    await show_todo_list(message)  # Возвращаем пользователя к списку задач

# Обработчик кнопки "Статистика"
@dp.message(lambda message: message.text == "Статистика")
async def show_statistics(message: types.Message):
    user_id = message.from_user.id
    tasks = await get_todo_list(user_id)

    if tasks:
        # Обновляем статус каждой задачи перед подсчетом статистики
        updated_tasks = []
        for task in tasks:
            updated_task = await update_task_status(task)
            updated_tasks.append(updated_task)

        # Создаем список статусов задач на основе обновленных задач
        statuses = [task.get("status", "в процессе") for task in updated_tasks]

        # Используем Counter для подсчета количества каждого статуса
        status_counts = Counter(statuses)

        # Формируем текст статистики
        stats_text = "📊 <b>Статистика по задачам:</b>\n"
        stats_text += f"🟡 В процессе: {status_counts.get('в процессе', 0)}\n"
        stats_text += f"✅ Выполнено: {status_counts.get('выполнено', 0)}\n"
        stats_text += f"❌ Просрочено: {status_counts.get('просрочено', 0)}\n"

        await message.answer(stats_text, parse_mode="HTML")
    else:
        await message.answer("У вас пока нет задач для статистики.")

# Обработчик кнопки "Изменить прикреплённые файлы"
@dp.message(lambda message: message.text == "Изменить прикреплённые файлы")
async def edit_task_media(message: types.Message, state: FSMContext):
    await message.answer(
        "Вы можете добавить новые файлы или удалить существующие.\n"
        "Отправьте новые файлы (фото или документы), чтобы добавить их.\n"
        "Используйте команду /delete_media для удаления прикреплённых файлов.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Удалить все файлы")],
                [KeyboardButton(text="Назад к задаче")]
            ],
            resize_keyboard=True
        )
    )
    await state.set_state(TaskForm.waiting_for_edit_media)

# Обработчик для добавления новых файлов
@dp.message(TaskForm.waiting_for_edit_media, lambda message: message.photo or message.document)
async def add_new_media(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    task_text = user_data.get("task_to_delete")
    user_id = message.from_user.id

    # Получаем текущие файлы задачи
    user = await collection.find_one({"user_id": user_id, "tasks.task_text": task_text})
    task = next((t for t in user["tasks"] if t["task_text"] == task_text), None)
    notes_media = task.get("notes_media", [])

    if message.photo:
        # Добавляем новое фото
        file_id = message.photo[-1].file_id
        notes_media.append({"type": "photo", "file_id": file_id})
    elif message.document:
        # Добавляем новый документ
        file_id = message.document.file_id
        notes_media.append({"type": "document", "file_id": file_id})

    # Обновляем задачу в базе данных
    await collection.update_one(
        {"user_id": user_id, "tasks.task_text": task_text},
        {"$set": {"tasks.$.notes_media": notes_media}}
    )

    await message.answer("Файл успешно добавлен. Вы можете добавить ещё файлы или нажмите /done для завершения.")

# Обработчик для удаления всех файлов
@dp.message(TaskForm.waiting_for_edit_media, lambda message: message.text == "Удалить все файлы")
async def delete_all_media(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    task_text = user_data.get("task_to_delete")
    user_id = message.from_user.id

    # Удаляем все файлы из задачи
    await collection.update_one(
        {"user_id": user_id, "tasks.task_text": task_text},
        {"$set": {"tasks.$.notes_media": []}}
    )

    await message.answer("Все прикреплённые файлы удалены.")
    await state.set_state(TaskForm.waiting_for_edit_media)

# Обработчик для завершения редактирования файлов
@dp.message(TaskForm.waiting_for_edit_media, lambda message: message.text == "Назад к задаче")
async def finish_editing_media(message: types.Message, state: FSMContext):
    await state.clear()
    await show_task_details(message, state)

@dp.message(lambda message: message.text == "Напоминание")
async def set_reminder(message: types.Message, state: FSMContext):
    await message.answer("Введите дату напоминания в формате ДД-ММ-ГГГГ:")
    await state.set_state(TaskForm.waiting_for_reminder_date)

@dp.message(TaskForm.waiting_for_reminder_date)
async def get_reminder_date(message: types.Message, state: FSMContext):
    try:
        reminder_date = message.text
        # Проверяем корректность формата даты
        datetime.strptime(reminder_date, "%d-%m-%Y")
        await state.update_data(reminder_date=reminder_date)
        await message.answer("Введите время напоминания в формате ЧЧ:ММ (24-часовой формат):")
        await state.set_state(TaskForm.waiting_for_reminder_time)
    except ValueError:
        await message.answer("❌ Неверный формат даты. Пожалуйста, используйте формат ДД-ММ-ГГГГ.")
@dp.message(TaskForm.waiting_for_reminder_time)
async def get_reminder_time(message: types.Message, state: FSMContext):
    try:
        reminder_time = message.text
        # Проверяем корректность формата времени
        datetime.strptime(reminder_time, "%H:%M")

        user_data = await state.get_data()
        reminder_date = user_data.get("reminder_date")
        task_text = user_data.get("task_to_delete")
        user_id = message.from_user.id

        # Объединяем дату и время
        reminder_datetime_str = f"{reminder_date} {reminder_time}"
        reminder_datetime = datetime.strptime(reminder_datetime_str, "%d-%m-%Y %H:%M")

        # Проверяем, что напоминание не в прошлом
        now = datetime.now()
        if reminder_datetime < now:
            await message.answer("❌ Нельзя установить напоминание в прошлом. Пожалуйста, введите корректное время.")
            return

        # Сохраняем напоминание в базе данных
        await collection.update_one(
            {"user_id": user_id, "tasks.task_text": task_text},
            {"$set": {"tasks.$.reminder": reminder_datetime_str}}
        )

        # Планируем напоминание с помощью Celery
        send_reminder.apply_async(
            args=[user_id, task_text, reminder_datetime_str],
            eta=reminder_datetime
        )

        await message.answer(f"Напоминание для задачи '{task_text}' установлено на {reminder_datetime_str}.")
        await state.clear()
        await show_todo_list(message)

    except ValueError:
        await message.answer("❌ Неверный формат времени. Пожалуйста, используйте формат ЧЧ:ММ (24-часовой формат).")

@dp.message(lambda message: message.text == "Назад в меню")
async def back_to_menu(message: types.Message):
    await message.answer("Вы вернулись в главное меню.", reply_markup=main_keyboard)
# Запуск бота
async def main():
    await check_connection()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())