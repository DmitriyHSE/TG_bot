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
    waiting_for_date_to_delete = State()  # Новое состояние для ввода даты удаления

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
                "$push": {"tasks": {"task_text": task_text, "deadline": deadline, "notes": notes}}
            },
            upsert=True
        )
        print(f"Задача добавлена в базу данных: user_id={user_id}, username={username}, task={task_text}, deadline={deadline}, notes={notes}")
    except Exception as e:
        print(f"Ошибка при добавлении задачи в базу данных: {e}")

# Клавиатура списка дел
async def create_todo_keyboard(tasks):
    buttons = []
    for task in tasks:
        if isinstance(task, dict):
            task_text = task.get("task_text")
            if task_text:
                buttons.append([KeyboardButton(text=task_text)])
    buttons.append([KeyboardButton(text="Добавить задачу")])
    buttons.append([KeyboardButton(text="Удалить дела по дате")])  # Новая кнопка
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
                task_text = task_data.get('task_text')
                deadline = task_data.get('deadline')
                if task_text and deadline:
                    task_list_text += f"Задача: {task_text}, Дедлайн: {deadline}\n"
        todo_keyboard = await create_todo_keyboard(tasks)
        await message.answer(task_list_text, reply_markup=todo_keyboard)
    else:
        await message.answer("Список задач пуст.", reply_markup=main_keyboard)

# Асинхронная функция для проверки, является ли сообщение задачей
async def is_task_message(message: types.Message) -> bool:
    user_id = message.from_user.id
    tasks = await get_todo_list(user_id)
    return message.text in [task.get("task_text") for task in tasks]

# Обработчик выбора задачи для показа примечаний
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
            # Добавляем кнопку "Удалить задачу"
            markup = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="Назад к списку задач")],
                    [KeyboardButton(text="Удалить задачу")]
                ],
                resize_keyboard=True
            )
            await message.answer(f"Примечания к задаче '{task_text}':\n{notes}", reply_markup=markup)
            break

# Обработчик кнопки "Удалить задачу"
@dp.message(lambda message: message.text == "Удалить задачу")
async def delete_task(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    tasks = await get_todo_list(user_id)

    # Получаем текст задачи из состояния
    user_data = await state.get_data()
    task_to_delete = user_data.get("task_to_delete")

    if task_to_delete:
        # Удаляем задачу из базы данных
        await collection.update_one(
            {"user_id": user_id},
            {"$pull": {"tasks": {"task_text": task_to_delete}}}
        )
        await message.answer(f"Задача '{task_to_delete}' удалена.")

        # Обновляем список задач и выводим его
        tasks = await get_todo_list(user_id)
        if tasks:
            task_list_text = "Ваши задачи:\n"
            for task_data in tasks:
                if isinstance(task_data, dict):
                    task_text = task_data.get('task_text')
                    deadline = task_data.get('deadline')
                    if task_text and deadline:
                        task_list_text += f"Задача: {task_text}, Дедлайн: {deadline}\n"
            todo_keyboard = await create_todo_keyboard(tasks)
            await message.answer(task_list_text, reply_markup=todo_keyboard)
        else:
            await message.answer("Список задач пуст.", reply_markup=main_keyboard)
    else:
        await message.answer("Задача не найдена.", reply_markup=main_keyboard)

    # Очищаем состояние
    await state.clear()

# Обработчик кнопки "Удалить дела по дате"
@dp.message(lambda message: message.text == "Удалить дела по дате")
async def delete_tasks_by_date_start(message: types.Message, state: FSMContext):
    await message.answer("Введите дату для удаления задач в формате ДД-ММ-ГГГГ:")
    await state.set_state(TaskForm.waiting_for_date_to_delete)

# Обработчик для удаления задач по дате
@dp.message(TaskForm.waiting_for_date_to_delete)
async def delete_tasks_by_date(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    date_to_delete = message.text

    try:
        # Проверка формата даты
        datetime.strptime(date_to_delete, "%d-%m-%Y")

        # Удаляем задачи с указанной датой
        await collection.update_one(
            {"user_id": user_id},
            {"$pull": {"tasks": {"deadline": {"$regex": f"^{date_to_delete}"}}}}
        )
        await message.answer(f"Все задачи на дату {date_to_delete} удалены.")

        # Обновляем список задач и выводим его
        tasks = await get_todo_list(user_id)
        if tasks:
            task_list_text = "Ваши задачи:\n"
            for task_data in tasks:
                if isinstance(task_data, dict):
                    task_text = task_data.get('task_text')
                    deadline = task_data.get('deadline')
                    if task_text and deadline:
                        task_list_text += f"Задача: {task_text}, Дедлайн: {deadline}\n"
            todo_keyboard = await create_todo_keyboard(tasks)
            await message.answer(task_list_text, reply_markup=todo_keyboard)
        else:
            await message.answer("Список задач пуст.", reply_markup=main_keyboard)
    except ValueError:
        await message.answer("Неверный формат даты. Пожалуйста, используйте формат ДД-ММ-ГГГГ.")

    # Очищаем состояние
    await state.clear()

# Обработчик кнопки "Назад к списку задач"
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

        await state.update_data(deadline=deadline)
        await message.answer("Введите примечания к задаче (или нажмите /skip, чтобы пропустить):")
        await state.set_state(TaskForm.waiting_for_notes)

    except ValueError:
        await message.answer("Неверный формат времени. Пожалуйста, используйте формат ЧЧ:ММ (24-часовой формат).")

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

# Функция запуска бота
async def main():
    await check_connection()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

# Запуск через asyncio
if __name__ == "__main__":
    asyncio.run(main())
