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
TOKEN = "8173550758:AAGe9DSFiKnm24xvn7j5xGf4iQkxyfMZ14k"

MONGO_URI = "mongodb://localhost:27017"
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)

# Выбор базы данных и коллекции
db = client.Telegram
collection = db.tasks  # Используем collection tasks

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

# Функция получения списка дел из базы данных для конкретного пользователя
async def get_todo_list(user_id):
    user = await collection.find_one({"user_id": user_id})
    if user and "tasks" in user and user["tasks"]:
        return user["tasks"]
    return []

# Функция добавления задачи в базу данных (изменено)
async def add_task_to_db(user_id, username, task_text, deadline):
    try:
        await collection.update_one(
            {"user_id": user_id},
            {
                "$setOnInsert": {"user_id": user_id, "username": username},
                "$push": {"tasks": {"task_text": task_text, "deadline": deadline}}
            },
            upsert=True
        )
        print(f"Задача добавлена в базу данных: user_id={user_id}, username={username}, task={task_text}, deadline={deadline}")
    except Exception as e:
        print(f"Ошибка при добавлении задачи в базу данных: {e}")


# Клавиатура списка дел
async def create_todo_keyboard():
    buttons = [
        [KeyboardButton(text="Добавить задачу")],
        [KeyboardButton(text="Назад в меню")]
    ]
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
    tasks = await get_todo_list(message.from_user.id)
    if tasks:
        task_list_text = ""
        for task in tasks:
            task_text = task.get('task_text')
            deadline = task.get('deadline')
            if task_text and deadline:
                task_list_text += f"Задача: {task_text}, Дедлайн: {deadline}\n"
    else:
        task_list_text = "Список задач пуст."
    todo_keyboard = await create_todo_keyboard()
    await message.answer(f"Ваши задачи:\n{task_list_text}", reply_markup=todo_keyboard)


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


@dp.message(TaskForm.waiting_for_deadline_date)
async def get_deadline_date(message: types.Message, state: FSMContext):
    try:
        deadline_date = message.text
        datetime.strptime(deadline_date, "%d-%m-%Y")  # Проверка формата даты
        await state.update_data(deadline_date=deadline_date)
        await message.answer("Введите время дедлайна в формате ЧЧ:ММ (24-часовой формат):")
        await state.set_state(TaskForm.waiting_for_deadline_time)
    except ValueError:
        await message.answer("Неверный формат даты. Пожалуйста, используйте формат ДД-ММ-ГГГГ.")

@dp.message(TaskForm.waiting_for_deadline_time)
async def get_deadline_time(message: types.Message, state: FSMContext):
    try:
        deadline_time = message.text
        datetime.strptime(deadline_time, "%H:%M")  # Проверка формата времени
        user_data = await state.get_data()
        task_text = user_data.get('task_text')
        deadline_date = user_data.get('deadline_date')

        # Объединяем дату и время в строку
        deadline = f"{deadline_date} {deadline_time}"

        user_id = message.from_user.id
        username = message.from_user.username
        await add_task_to_db(user_id, username, task_text, deadline)
        await message.answer(f"Задача '{task_text}' с дедлайном '{deadline}' успешно добавлена!")
        await state.clear()
        await show_todo_list(message)

    except ValueError:
        await message.answer("Неверный формат времени. Пожалуйста, используйте формат ЧЧ:ММ (24-часовой формат).")

# Обработчик кнопки "Назад в меню"
@dp.message(lambda message: message.text == "Назад в меню")
async def back_to_main_menu(message: types.Message):
    await message.answer("Вы вернулись в главное меню:", reply_markup=main_keyboard)

# Функция запуска бота
async def main():
    await check_connection()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

# Запуск через asyncio
if __name__ == "__main__":
    asyncio.run(main())