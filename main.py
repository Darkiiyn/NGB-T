import os
import json
import zipfile
import io
import base64
import asyncio
import logging
import struct
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from telethon import TelegramClient, functions, types as tel_types
from telethon.sessions import StringSession

# --- ВАШИ ДАННЫЕ ---
API_ID = 30033863
API_HASH = "9509a68309c27626547d0604f9419e21"
BOT_TOKEN = "8418740075:AAHMCYHf703ja9STlMQmwJ6i0BYPiYM1dOs"

# Настройка логирования
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ФУНКЦИЯ КОНВЕРТАЦИИ ---
def pyro_to_telethon_str(pyro_string):
    """Декодирует строку Pyrogram и упаковывает в формат Telethon"""
    try:
        # Убираем лишние пробелы и переносы
        pyro_string = pyro_string.strip()
        data = base64.urlsafe_b64decode(pyro_string + '=' * (-len(pyro_string) % 4))
        
        # Для большинства строк Pyrogram (v2/v3)
        # Формат: [DC_ID(1)][IP_TYPE(1)][IP(4)][PORT(2)][AUTH_KEY(256)]
        dc_id = data[0]
        auth_key = data[8:264] 
        
        # Генерируем строку сессии Telethon
        return StringSession.encode(dc_id, "149.154.167.50", 443, auth_key)
    except Exception as e:
        logging.error(f"Ошибка конвертации: {e}")
        return None

# --- СБОР ДАННЫХ ЧЕРЕЗ TELETHON ---
async def get_account_assets(tele_string):
    client = TelegramClient(StringSession(tele_string), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return "❌ Сессия невалидна (аккаунт вылетел).", None

        me = await client.get_me()
        
        # 1. Получаем баланс звезд
        stars_balance = 0
        try:
            # Запрос статуса звезд текущего пользователя
            status = await client(functions.payments.GetStarsStatusRequest(peer='me'))
            stars_balance = status.balance.amount if hasattr(status.balance, 'amount') else 0
        except Exception as e:
            logging.error(f"Ошибка получения звезд: {e}")
            stars_balance = "Не удалось определить"

        # 2. Получаем NFT-подарки
        nft_list = []
        try:
            result = await client(functions.payments.GetUserStarGiftsRequest(
                user_id='me', offset='', limit=100
            ))
            count = 1
            for gift in result.gifts:
                # Проверяем наличие NFT атрибута
                if hasattr(gift, 'nft_attribute') and gift.nft_attribute:
                    slug = gift.nft_attribute.slug
                    link = f"https://t.me/nft/{slug}"
                    nft_list.append(f"• <a href='{link}'>NFT {count}</a>")
                    count += 1
        except Exception as e:
            logging.error(f"Ошибка получения NFT: {e}")

        # Формируем отчет
        report = (
            f"✅ <b>Вход выполнен!</b>\n\n"
            f"👤 <b>Аккаунт:</b> {me.first_name} (ID: <code>{me.id}</code>)\n"
            f"⭐ <b>Звезды:</b> <code>{stars_balance}</code>\n"
            f"🎁 <b>NFT Подарки:</b>\n"
        )
        report += "\n".join(nft_list) if nft_list else "<i>NFT не обнаружены</i>"
        
        return report, me.id
    finally:
        await client.disconnect()

# --- ОБРАБОТЧИК ФАЙЛОВ ---
@dp.message(F.document)
async def handle_document(message: types.Message):
    if not message.document.file_name.lower().endswith('.zip'):
        return

    status = await message.answer("🔍 Читаю архив...")
    file_data = await bot.download(message.document.file_id)
    
    try:
        with zipfile.ZipFile(file_data) as z:
            # РЕКУРСИВНЫЙ ПОИСК session.json (игнорируем папки и регистр)
            session_file_path = None
            for file_info in z.infolist():
                if file_info.filename.lower().endswith('session.json'):
                    session_file_path = file_info.filename
                    break
            
            if not session_file_path:
                await status.edit_text("❌ Файл <b>session.json</b> не найден в архиве (даже в подпапках).")
                return
            
            # Читаем содержимое
            with z.open(session_file_path) as f:
                data = json.load(f)
                pyro_str = data.get("user")

        if not pyro_str:
            await status.edit_text("❌ В session.json отсутствует ключ 'user'.")
            return

        await status.edit_text("🔄 Конвертация сессии...")
        tele_str = pyro_to_telethon_str(pyro_str)
        
        if not tele_str:
            await status.edit_text("❌ Не удалось расшифровать строку сессии.")
            return

        await status.edit_text("🛰 Соединение с серверами Telegram...")
        report, _ = await get_account_assets(tele_str)
        
        await status.edit_text(report, parse_mode="HTML", disable_web_page_preview=False)

    except Exception as e:
        await status.edit_text(f"❌ Произошла ошибка: {e}")
        logging.exception(e)

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Пришли мне ZIP-архив с сессией, и я проверю баланс звезд и NFT.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
