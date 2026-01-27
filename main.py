import logging
import asyncio
import json
import zipfile
import io
import base64
import struct

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command
from aiogram.enums import ParseMode

from telethon import TelegramClient, functions
from telethon.sessions import StringSession
from telethon import types as tel_types

# --- КОНФИГУРАЦИЯ ---
API_ID = 30033863
API_HASH = "9509a68309c27626547d0604f9419e21"
BOT_TOKEN = "8418740075:AAHMCYHf703ja9STlMQmwJ6i0BYPiYM1dOs"

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ФУНКЦИИ КОНВЕРТАЦИИ ---

def pyro_to_telethon_str(pyro_string):
    """
    Конвертирует строку сессии Pyrogram v2/v3 в формат Telethon StringSession.
    """
    try:
        # Очистка строки от пробелов/переносов
        pyro_string = pyro_string.strip().replace("\n", "").replace("\r", "")
        
        # Добавляем паддинг для base64, если нужно
        padded_str = pyro_string + '=' * (-len(pyro_string) % 4)
        data = base64.urlsafe_b64decode(padded_str)
        
        # Структура Pyrogram сессии:
        # [DC_ID (1 байт)] ... [AUTH_KEY (256 байт)]
        # Обычно AuthKey начинается с 8-го байта (для v2)
        
        dc_id = data[0]
        # IP адрес DC2 (Европа) по умолчанию
        ip = "149.154.167.50" 
        port = 443
        auth_key = data[8:264]  # Вырезаем 256 байт ключа
        
        return StringSession.encode(dc_id, ip, port, auth_key)
    except Exception as e:
        logger.error(f"Ошибка декодирования строки сессии: {e}")
        return None

# --- РАБОТА С TELETHON ---

async def check_account_assets(telethon_session_str):
    """
    Подключается к аккаунту и проверяет Звезды и NFT.
    """
    client = TelegramClient(StringSession(telethon_session_str), API_ID, API_HASH)
    
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            return "❌ <b>Ошибка входа:</b> Сессия невалидна или требует 2FA пароль.", None

        # Получаем информацию о пользователе
        me = await client.get_me()
        
        # 1. Проверка баланса Telegram Stars
        stars_txt = "0"
        try:
            # Запрашиваем состояние звезд
            stars_status = await client(functions.payments.GetStarsStatusRequest(
                peer='me'
            ))
            # В зависимости от версии API структура может меняться, проверяем баланс
            if hasattr(stars_status, 'balance'):
                stars_txt = str(stars_status.balance.amount)
            else:
                stars_txt = "0"
        except Exception as e:
            logger.error(f"Не удалось получить звезды: {e}")
            stars_txt = "Ошибка доступа"

        # 2. Поиск NFT подарков
        nft_lines = []
        try:
            # Получаем список подарков пользователя
            gifts_result = await client(functions.payments.GetUserStarGiftsRequest(
                user_id='me',
                offset='',
                limit=100
            ))
            
            counter = 1
            for gift in gifts_result.gifts:
                # Проверяем, является ли подарок уникальным (NFT)
                # У NFT есть атрибут nft_attribute
                if hasattr(gift, 'nft_attribute') and gift.nft_attribute:
                    slug = gift.nft_attribute.slug
                    # Формируем красивую ссылку
                    link = f"https://t.me/nft/{slug}"
                    nft_lines.append(f"• <a href='{link}'>NFT {counter}</a>")
                    counter += 1
                    
        except Exception as e:
            logger.error(f"Не удалось получить подарки: {e}")

        # Формирование итогового отчета
        report = f"✅ <b>Анализ завершен!</b>\n\n"
        report += f"👤 <b>Аккаунт:</b> {me.first_name}\n"
        report += f"🆔 <b>ID:</b> <code>{me.id}</code>\n"
        report += f"⭐ <b>Баланс Stars:</b> {stars_txt}\n\n"
        
        report += "🎁 <b>NFT Коллекция:</b>\n"
        if nft_lines:
            report += "\n".join(nft_lines)
        else:
            report += "<i>Нет NFT подарков</i>"
            
        return report, me.id

    except Exception as e:
        return f"❌ <b>Критическая ошибка Telethon:</b> {str(e)}", None
    finally:
        await client.disconnect()

# --- ОБРАБОТЧИКИ БОТА ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я чекер сессий Nicegram.\n\n"
        "Отправь мне <b>.zip</b> архив (Export Settings), и я проверю:\n"
        "1. Баланс Telegram Stars\n"
        "2. Наличие NFT подарков"
    )

@dp.message(F.document)
async def handle_zip_file(message: Message):
    if not message.document.file_name.lower().endswith('.zip'):
        await message.answer("❌ Это не ZIP-архив.")
        return

    status_msg = await message.answer("⏳ <b>Скачиваю и анализирую архив...</b>")

    # Скачиваем файл в оперативную память (без сохранения на диск)
    file_in_memory = io.BytesIO()
    await bot.download(message.document, destination=file_in_memory)
    
    try:
        json_content = None
        
        # Открываем ZIP
        with zipfile.ZipFile(file_in_memory) as z:
            # Рекурсивный поиск session.json
            target_filename = None
            for fname in z.namelist():
                if fname.lower().endswith('session.json'):
                    target_filename = fname
                    break
            
            if not target_filename:
                await status_msg.edit_text("❌ В архиве не найден файл <b>session.json</b>")
                return
            
            # Читаем файл
            with z.open(target_filename) as f:
                # Читаем как байты, декодируем в utf-8, игнорируя ошибки
                raw_text = f.read().decode('utf-8', errors='ignore')
                
                # --- ГЛАВНОЕ ИСПРАВЛЕНИЕ ---
                # Удаляем все переносы строк, которые ломали JSON
                clean_text = raw_text.replace('\n', '').replace('\r', '')
                
                # Пытаемся распарсить JSON
                try:
                    json_data = json.loads(clean_text, strict=False)
                    json_content = json_data.get("user")
                except json.JSONDecodeError as je:
                    await status_msg.edit_text(f"❌ Ошибка структуры JSON файла: {je}")
                    return

        if not json_content:
            await status_msg.edit_text("❌ В session.json пусто или нет ключа 'user'")
            return

        await status_msg.edit_text("🔄 <b>Конвертирую сессию в новый формат...</b>")
        
        # Конвертация в Telethon
        telethon_str = pyro_to_telethon_str(json_content)
        
        if not telethon_str:
            await status_msg.edit_text("❌ Не удалось расшифровать строку сессии.")
            return
            
        await status_msg.edit_text("🚀 <b>Подключаюсь к аккаунту...</b>")
        
        # Проверка аккаунта
        report_text, _ = await check_account_assets(telethon_str)
        
        # Отправка результата
        await status_msg.edit_text(report_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Global error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Произошла системная ошибка: {str(e)}")

# --- ЗАПУСК ---

async def main():
    print("Бот запущен...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
