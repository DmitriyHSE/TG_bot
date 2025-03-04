import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import motor.motor_asyncio
from datetime import datetime

# Токен бота
TOKEN = "7651886591:AAEAZfTe8f8ga-WJxcXo65mjBaYyixAd7fo"

# Подключение к локальной MongoDB
MONGO_URI = "mongodb://localhost:27017"
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)

# Выбор базы данных и коллекции
db = client.Telegram
collection = db.Tg

# Проверка подключения к MongoDB
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

# Состояния для FSM
class TaskForm(StatesGroup):
    waiting_for_task = State()
    waiting_for_deadline_date = State()
    waiting_for_deadline_time = State()
    waiting_for_notes = State()
    waiting_for_date_to_delete = State()

# Функция получения списка дел из базы данных для конкретного пользователя
async def get_todo_list(user_id):
    user = await collection.find_one({"user_id": user_id})
    if user and "tasks" in user:
        return user["tasks"]
    return []

# Функция добавления задачи в базу данных
async def add_task_to_db(user_id, username, task_text, deadline, notes=""):
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
                        "status": "в процессе"  # Статус по умолчанию
                    }
                }
            },
            upsert=True
        )
        print(f"Задача добавлена в базу данных: user_id={user_id}, username={username}, task={task_text}, deadline={deadline}, notes={notes}")
    except Exception as e:
        print(f"Ошибка при добавлении задачи в базу данных: {e}")

# Функция обновления статуса задачи
async def update_task_status(task):
    deadline = datetime.strptime(task["deadline"], "%d-%m-%Y %H:%M")
    now = datetime.now()
    if task["status"] != "выполнено":  # Если задача не выполнена
        if now > deadline:
            task["status"] = "просрочено"
    return task

# Клавиатура списка дел
async def create_todo_keyboard(tasks):
    buttons = []
    for task in tasks:
        if isinstance(task, dict):
            task_text = task.get("task_text")
            if task_text:
                buttons.append([KeyboardButton(text=task_text)])
    buttons.append([KeyboardButton(text="Добавить задачу")])
    buttons.append([KeyboardButton(text="Удалить дела по дате")])
    buttons.append([KeyboardButton(text="Назад в меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

# Клавиатура главного меню
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[[
        KeyboardButton(text="Показать список дел")
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
@dp.message(lambda message: message.text == "Показать список дел")
async def show_todo_list(message: types.Message):
    user_id = message.from_user.id
    tasks = await get_todo_list(user_id)

    if tasks:
        task_list_text = "Ваши задачи:\n"
        for task_data in tasks:
            if isinstance(task_data, dict):
                # Обновляем статус задачи
                task_data = await update_task_status(task_data)
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
                    # Преобразуем строку дедлайна в объект datetime
                    deadline = datetime.strptime(deadline_str, "%d-%m-%Y %H:%M")
                    # Получаем текущее время
                    now = datetime.now()
                    # Вычисляем разницу между дедлайном и текущим временем
                    time_left = deadline - now
                    # Получаем количество дней, часов и минут
                    days = time_left.days
                    hours, remainder = divmod(time_left.seconds, 3600)
                    minutes = remainder // 60
                    # Формируем строку с оставшимся временем
                    time_left_str = f"{days} дней, {hours} часов, {minutes} минут"
                    # Добавляем задачу в список
                    if(time_left.days<0 or minutes<0 or hours<0):
                        task_list_text += f"{status_emoji} Задача: {task_text}, Просрочена\n"
                    else:
                        task_list_text += f"{status_emoji} Задача: {task_text}, Осталось: {time_left_str}\n"
        todo_keyboard = await create_todo_keyboard(tasks)
        await message.answer(task_list_text, reply_markup=todo_keyboard)
    else:
        # Если список задач пуст, показываем кнопки "Добавить задачу" и "Назад в меню"
        empty_list_keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Добавить задачу")],
                [KeyboardButton(text="Назад в меню")]
            ],
            resize_keyboard=True
        )
        await message.answer("Список задач пуст.", reply_markup=empty_list_keyboard)

# Асинхронная функция для проверки, является ли сообщение задачей
async def is_task_message(message: types.Message) -> bool:
    user_id = message.from_user.id
    tasks = await get_todo_list(user_id)
    return message.text in [task.get("task_text") for task in tasks]

# Обработчик выбора задачи
@dp.message(is_task_message)
async def show_task_notes(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    tasks = await get_todo_list(user_id)
    task_text = message.text

    for task in tasks:
        if task.get("task_text") == task_text:
            notes = task.get("notes", "Примечаний нет.")
            # Сохраняем текст задачи в состоянии
            await state.update_data(task_to_delete=task_text)
            # Добавляем кнопки для управления статусом
            markup = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="Задача выполнена")],
                    [KeyboardButton(text="Назад к списку задач")]
                ],
                resize_keyboard=True
            )
            await message.answer(f"Задача: {task_text}\nПримечания: {notes}", reply_markup=markup)
            break

# Обработчик для изменения статуса задачи
@dp.message(lambda message: message.text == "Задача выполнена")
async def mark_task_as_done(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await state.get_data()
    task_text = user_data.get("task_to_delete")

    if task_text:
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

# Обработчик для возврата к списку задач
@dp.message(lambda message: message.text == "Назад к списку задач")
async def back_to_tasks(message: types.Message):
    await show_todo_list(message)

# Обработчик кнопки "Добавить задачу"
@dp.message(lambda message: message.text == "Добавить задачу")
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
        await message.answer("❌ Неверный формат даты. Пожалуйста, используйте формат ДД-ММ-ГГГГ.")

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

# Обработчик для получения примечаний
@dp.message(TaskForm.waiting_for_notes)
async def get_notes(message: types.Message, state: FSMContext):
    notes = message.text
    if notes == "/skip":
        notes = ""

    user_data = await state.get_data()
    task_text = user_data.get('task_text')
    deadline = user_data.get('deadline')

    user_id = message.from_user.id
    username = message.from_user.username
    await add_task_to_db(user_id, username, task_text, deadline, notes)
    await message.answer(f"Задача '{task_text}' с дедлайном '{deadline}' и примечаниями '{notes}' успешно добавлена!")
    await state.clear()
    await show_todo_list(message)
# Обработчик кнопки "Назад в меню"
@dp.message(lambda message: message.text == "Назад в меню")
async def back_to_main_menu(message: types.Message):
    await message.answer("Вы вернулись в главное меню:", reply_markup=main_keyboard)
# Запуск бота
async def main():
    await check_connection()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
