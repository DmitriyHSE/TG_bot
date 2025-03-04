import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import motor.motor_asyncio

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

# Функция получения списка дел из базы данных для конкретного пользователя
async def get_todo_list(user_id):
    user = await collection.find_one({"user_id": user_id})
    if user and "tasks" in user:
        return user["tasks"]
    return []

# Функция добавления задачи в базу данных
async def add_task_to_db(user_id, username, task_name):
    await collection.update_one(
        {"user_id": user_id},
        {
            "$setOnInsert": {"user_id": user_id, "username": username},  # Устанавливаем при создании
            "$push": {"tasks": task_name}  # Добавляем задачу
        },
        upsert=True
    )

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
    await message.answer("Привет! Выберите действие:", reply_markup=main_keyboard)

# Обработчик кнопки "Показать список дел"
@dp.message(lambda message: message.text == "Показать список дел")
async def show_todo_list(message: types.Message):
    tasks = await get_todo_list(message.from_user.id)
    task_list_text = "\n".join(tasks) if tasks else "Список задач пуст."
    todo_keyboard = await create_todo_keyboard()
    await message.answer(f"Ваши задачи:\n{task_list_text}", reply_markup=todo_keyboard)

# Обработчик кнопки "Добавить задачу"
@dp.message(lambda message: message.text == "Добавить задачу")
async def add_task(message: types.Message, state: FSMContext):
    await message.answer("Введите задачу, которую хотите добавить:")
    await state.set_state(TaskForm.waiting_for_task)

# Обработчик для сохранения задачи, с использованием фильтра состояния
@dp.message(TaskForm.waiting_for_task)
async def save_task(message: types.Message, state: FSMContext):
    task_name = message.text
    user_id = message.from_user.id
    username = message.from_user.username  # Получаем тэг пользователя
    await add_task_to_db(user_id, username, task_name)
    await message.answer(f"Задача '{task_name}' успешно добавлена!")
    await state.clear()
    await show_todo_list(message)

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
