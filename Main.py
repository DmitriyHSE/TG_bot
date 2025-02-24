import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
import motor.motor_asyncio

# Токен бота
TOKEN = "7651886591:AAEAZfTe8f8ga-WJxcXo65mjBaYyixAd7fo"

# Создание бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Подключение к локальному MongoDB
MONGO_URI = "mongodb://localhost:27017"
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)

# Выбор базы данных и коллекции
db = client.Telegram  # Название базы данных
collection = db.Tg  # Название коллекции

# Проверка подключения
async def check_connection():
    try:
        await client.admin.command("ping")
        print("✅ Подключение к MongoDB успешно!")
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")

# Обработчик команды /start
@dp.message(CommandStart())
async def start_handler(message: types.Message):
    user = {"user_id": message.from_user.id, "username": message.from_user.username}
    print(message.from_user.id)
    print(message.from_user.username)
    await collection.insert_one(user)  # Сохранение пользователя в БД
    await message.answer("Привет! Ты был добавлен в базу данных.")

# Функция запуска бота
async def main():
    await check_connection()
    await bot.delete_webhook(drop_pending_updates=True)  # Удаляем старые обновления
    await dp.start_polling(bot)  # Запускаем бота

# Запуск через asyncio
if __name__ == "__main__":
    asyncio.run(main())
