import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
import motor.motor_asyncio

# Токен бота
TOKEN = "7651886591:AAEAZfTe8f8ga-WJxcXo65mjBaYyixAd7fo"

# Подключение к локальной MongoDB
MONGO_URI = "mongodb://localhost:27017"  # Локальное подключение
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)

# Выбор базы данных и коллекции
db = client.Telegram  # Название базы
collection = db.Tg  # Название коллекции


# Проверка подключения к MongoDB
async def check_connection():
    try:
        await client.admin.command("ping")
        print("✅ Подключение к MongoDB успешно!")
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")


# Создание бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()


# Обработчик команды /start
@dp.message(CommandStart())
async def start_handler(message: types.Message):
    # Создаем клавиатуру с кнопкой "Показать список дел"
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Показать список дел")]
        ],
        resize_keyboard=True
    )

    await message.answer("Привет! Выберите действие:", reply_markup=keyboard)


# Функция запуска бота
async def main():
    await check_connection()  # Проверяем соединение с БД
    await bot.delete_webhook(drop_pending_updates=True)  # Удаляем старые обновления
    await dp.start_polling(bot)  # Запускаем бота


# Запуск через asyncio
if __name__ == "__main__":
    asyncio.run(main())
