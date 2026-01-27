import asyncio
import os
import shutil
import zipfile
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command
from pyrogram import Client
from pyrogram.errors import (
    AuthKeyUnregistered, 
    UserDeactivated, 
    SessionPasswordNeeded,
    AuthKeyDuplicated,
    FloodWait
)
from opentele.td import TDesktop
from opentele.api import UseCurrentSession

# --- НАСТРОЙКИ ---
BOT_TOKEN = '8418740075:AAHMCYHf703ja9STlMQmwJ6i0BYPiYM1dOs'
API_ID = 30033863        # ВАШ API_ID
API_HASH = '9509a68309c27626547d0604f9419e21'  # ВАШ API_HASH
# -----------------

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

async def check_account_status(session_path: str, work_dir: str):
    """
    Функция попытки входа и диагностики.
    Возвращает словарь с результатами.
    """
    # Инициализируем клиент. Используем MemoryStorage или файл в папке
    client = Client(
        name="checker_session",
        api_id=API_ID,
        api_hash=API_HASH,
        workdir=work_dir, # Важно: изолируем сессии
        in_memory=True    # Стараемся не мусорить на диске
    )

    # Пытаемся загрузить сессию, сконвертированную opentele
    # ВНИМАНИЕ: opentele работает специфично, здесь упрощенный пример
    # загрузки через TDesktop, если структура папки имитирует tdata
    
    result = {
        "status": "error",
        "details": "Неизвестная ошибка",
        "user_info": None
    }

    try:
        # Попытка подключения
        await client.connect()
    except AuthKeyUnregistered:
        result["status"] = "dead"
        result["details"] = "❌ **Сессия уничтожена.** (AuthKeyUnregistered)\nВладелец завершил сеанс или ключ устарел."
        return result
    except AuthKeyDuplicated:
        result["status"] = "dead"
        result["details"] = "❌ **Ключ дублирован.** Сессия невалидна."
        return result
    except Exception as e:
        result["status"] = "network_error"
        result["details"] = f"⚠️ **Ошибка подключения:** {str(e)}\nВозможно, прокси или проблема с DC."
        return result

    # Если подключились, проверяем авторизацию
    try:
        me = await client.get_me()
        
        # Сбор информации (если зашли успешно)
        is_premium = "🌟 Да" if me.is_premium else "Нет"
        username = f"@{me.username}" if me.username else "Нет юзернейма"
        
        result["status"] = "live"
        result["user_info"] = me
        result["details"] = (
            f"✅ **АККАУНТ ВАЛИДЕН**\n\n"
            f"👤 **Имя:** {me.first_name} {me.last_name or ''}\n"
            f"🆔 **ID:** `{me.id}`\n"
            f"🔗 **Юзернейм:** {username}\n"
            f"💎 **Premium:** {is_premium}\n"
            f"📱 **Телефон:** +{me.phone_number if me.phone_number else 'Скрыт'}"
        )

    except UserDeactivated:
        result["status"] = "banned"
        result["details"] = "🚫 **Аккаунт забанен.** (UserDeactivated)\nНомер удален или заблокирован Telegram."
    except AuthKeyUnregistered:
        result["status"] = "dead"
        result["details"] = "❌ **Сессия слетела в момент проверки.**"
    except SessionPasswordNeeded:
        # Это значит сессия ЖИВАЯ, но требует 2FA для некоторых действий.
        # Но get_me() обычно проходит и так. Если мы тут - значит валид.
        result["status"] = "live_2fa"
        result["details"] = "⚠️ **Аккаунт валиден, но стоит 2FA пароль.**"
    except Exception as e:
        result["status"] = "error"
        result["details"] = f"❓ Ошибка при получении данных: {e}"
    finally:
        if client.is_connected:
            await client.disconnect()

    return result

@dp.message(F.document)
async def handle_zip(message: Message):
    if not message.document.file_name.endswith('.zip'):
        await message.answer("Отправь мне ZIP архив.")
        return

    msg = await message.answer("📥 Скачиваю...")
    
    # Создаем уникальную папку для обработки
    unique_id = f"{message.from_user.id}_{message.message_id}"
    extract_path = f"temp/{unique_id}"
    os.makedirs(extract_path, exist_ok=True)

    try:
        # Скачиваем и распаковываем
        file = await bot.get_file(message.document.file_id)
        zip_path = f"{extract_path}/archive.zip"
        await bot.download_file(file.file_path, zip_path)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_path)
        
        await msg.edit_text("⚙️ Обработка файлов и попытка конвертации...")

        # --- ЛОГИКА КОНВЕРТАЦИИ ---
        # Здесь главная сложность. Nicegram (Android) -> TData (Desktop) -> Pyrogram.
        # Для упрощения мы пробуем найти tdata внутри, если opentele сможет её съесть.
        # Если это чистый Android export (только tgnet.dat), opentele может не справиться
        # без дополнительных map-файлов.
        
        # Попытка найти папку с tdata (обычно account0)
        tdata_folder = None
        for root, dirs, files in os.walk(extract_path):
            if "tgnet.dat" in files:
                tdata_folder = root
                break
        
        if not tdata_folder:
            await msg.edit_text("❌ Не найден `tgnet.dat` в архиве.")
            return

        # Пытаемся конвертировать через opentele
        try:
            # Opentele конвертирует папку tdata в session-string или session-file
            tdesk = TDesktop(tdata_folder)
            
            # Проверяем, загрузилась ли tdata
            if tdesk.isLoaded():
                # Конвертируем в Pyrogram сессию
                session_name = f"{extract_path}/converted.session"
                client = await tdesk.ToPyrogramClient(session_file=session_name, api_id=API_ID, api_hash=API_HASH)
                
                # Теперь проверяем этот клиент
                # Закрываем его, чтобы чекер мог открыть файл
                await client.disconnect() 
                
                # Запускаем проверку
                check_result = await check_account_status(session_name, extract_path)
                await msg.edit_text(check_result["details"], parse_mode="Markdown")
                
            else:
                await msg.edit_text("⚠️ **Ошибка конвертации.**\nСтруктура `tgnet.dat` не распознана библиотекой (возможно, версия Android слишком новая или старая).")

        except Exception as e:
            # Если конвертер упал, читаем session.json как запасной вариант
            # (Как мы делали в прошлом ответе, просто чтобы показать хоть что-то)
            await msg.edit_text(f"❌ **Критическая ошибка проверки:**\n`{str(e)}`\n\nБот не смог преобразовать файлы Android в сессию Pyrogram.")

    finally:
        # Очистка мусора
        if os.path.exists(extract_path):
            shutil.rmtree(extract_path)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
