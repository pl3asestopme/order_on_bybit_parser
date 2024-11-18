import asyncio
import logging
import sys
import json
import ssl
import certifi
import websockets

from config import BOT_TOKEN
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from datetime import datetime

# Bot token
TOKEN = BOT_TOKEN

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

storage = MemoryStorage()

router = Router()
dp = Dispatcher(storage=storage)

# Подключение маршрутов
dp.include_router(router)

# Логирование
logger = logging.getLogger(__name__)

# Список для хранения chat_id пользователей, которые написали /start
user_chat_ids = []
# Флаги для фильтрации ордеров
is_started = False
filter_orders = False  # Флаг для включения фильтрации по объему и цене
websocket_task = None  # Переменная для отслеживания активной задачи WebSocket

# Настройки WebSocket
MIN_PRICE = 85000
MAX_PRICE = 100000
MIN_VOLUME = 10000  # Установлено минимальное значение объема
MAX_VOLUME = float('inf')  # Можно оставить как бесконечность, чтобы не ограничивать сверху

async def parse_orders():
    global is_started, websocket_task
    url = 'wss://stream.bybit.com/v5/public/linear'
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    try:
        async with websockets.connect(url, ssl=ssl_context) as websocket:
            payload = {
                "op": "subscribe",
                "args": [
                    "orderbook.500.BTCUSDT",
                    "orderbook.500.ETHUSDT",
                    "orderbook.500.SOLUSDT",
                    "orderbook.500.XRPUSDT",
                    "orderbook.500.ADAUSDT",
                    "orderbook.500.DOGEUSDT",
                    "orderbook.500.LTCUSDT",
                    "orderbook.500.TRXUSDT",
                    "orderbook.500.BNBUSDT",
                    "orderbook.500.DOTUSDT",
                    "orderbook.500.AVAXUSDT",
                    "orderbook.500.MATICUSDT"
                ]
            }
            await websocket.send(json.dumps(payload))

            while True:
                if not is_started:
                    logger.info("Ожидание команды для начала...")
                    await asyncio.sleep(1)
                    continue

                response = await websocket.recv()
                data = json.loads(response)
                logger.info(f"Order data: {json.dumps(data, indent=2)}")
                await process_order_data(data)
    except (websockets.exceptions.WebSocketException, ssl.SSLError) as e:
        logger.error(f"Ошибка при подключении или получении данных WebSocket: {e}")
        await asyncio.sleep(5)
        if is_started:
            websocket_task = asyncio.create_task(parse_orders())  # Перезапуск задачи, если процесс активен

async def process_order_data(data):
    logger.info("В поиске ордеров...")
    if filter_orders:
        if matches_criteria(data):
            logger.info("Поиск по критериям")
            await send_alert(data)
        else:
            logger.info("Подходящий ордер пока не найден. Ожидайте")
    else:
        await send_alert(data)

def matches_criteria(data):
    if 'data' not in data or 'a' not in data['data'] or 'b' not in data['data']:
        return False

    for order in data['data']['a'] + data['data']['b']:
        try:
            price = float(order[0])
            volume = float(order[1])
        except ValueError as e:
            logger.error(f"ValueError: {e}")
            continue

        if volume == 0:
            continue

        logger.info(f"Checking order - Price: {price} | Volume: {volume}")

        # Проверка условия на минимальный объем
        if volume >= MIN_VOLUME and MIN_PRICE <= price <= MAX_PRICE:
            return True

    return False

async def send_alert(data):
    if 'topic' not in data or 'data' not in data:
        return

    # Extract the trading pair from the topic
    trading_pair = data['topic'].split('.')[-1]
    formatted_pair = trading_pair[:3] + '-' + trading_pair[3:]  # Форматируем в "BTC-USDT"
    matching_orders = []
    current_time = datetime.now().strftime("%d/%m/%Y %H-%M-%S-%f")[:-3]

    for order in data['data']['a'] + data['data']['b']:
        try:
            price = float(order[0])
            volume = float(order[1])
            order_id = order if order else "N/A"  # Adjust index as needed for order ID
        except ValueError as e:
            logger.error(f"ValueError: {e}")
            continue

        if volume == 0:
            continue

        # Check filter conditions
        if not filter_orders or (MIN_PRICE <= price <= MAX_PRICE and MIN_VOLUME <= volume <= MAX_VOLUME):
            # Format volume with up to 9 decimal places
            formatted_volume = f"{volume:.9f}"
            order_type = "Sell" if order in data['data']['a'] else "Buy"
            purchase_link = f"https://www.bybit.com/trade/spot/{order_type.lower()}?symbol={trading_pair}"

            matching_orders.append(
                f"{order_type} Ордер:\nПара: {formatted_pair}\nИнформация о ордере: {order_id}\nЦена: {price:.2f}\nОбъем: {formatted_volume}\n"
                f"Ссылка на покупку:\n({purchase_link})"
            )

    if matching_orders:
        for order in matching_orders:
            for chat_id in user_chat_ids:
                await bot.send_message(
                    chat_id,
                    f"✅ {order}\nТекущее время: {current_time}",
                    disable_web_page_preview=True
                )
                logger.info(f"✅ {order} at {current_time}")

@router.message(Command("start"))
async def start_command(message: Message):
    chat_id = message.chat.id
    if chat_id not in user_chat_ids:
        user_chat_ids.append(chat_id)
    await message.answer(
        "Бот запущен! Используйте /all чтобы получать все ордера \nИли /etc чтобы получать ордера по фильтру. \n\n/etc ОБЪЕМ_ОТ ОБЪЕМ_ДО ЦЕНА_ОТ ЦЕНА_ДО (цена в USDT)\n\nПРИМЕР:\n(/etc 10 100 85000 100000)")

@router.message(Command("all"))
async def all_command(message: Message):
    global is_started, filter_orders, websocket_task
    filter_orders = False
    if not is_started:
        is_started = True
        if websocket_task is None or websocket_task.done():
            websocket_task = asyncio.create_task(parse_orders())
    await message.answer("Вы будете получать все ордера.")

@router.message(Command("etc"))
async def etc_command(message: Message):
    global is_started, filter_orders, websocket_task
    filter_orders = True

    args = message.text.split()
    if len(args) == 5:
        try:
            global MIN_VOLUME, MAX_VOLUME, MIN_PRICE, MAX_PRICE
            MIN_VOLUME = float(args[1])
            MAX_VOLUME = float(args[2])
            MIN_PRICE = float(args[3])
            MAX_PRICE = float(args[4])
            logger.info(f"Фильтрация установлена на объем от {MIN_VOLUME} до {MAX_VOLUME} и цену от {MIN_PRICE} до {MAX_PRICE}")
        except ValueError:
            await message.answer("Неверные параметры фильтрации.")
            return

    if not is_started:
        is_started = True
        if websocket_task is None or websocket_task.done():
            websocket_task = asyncio.create_task(parse_orders())

    await message.answer(
        f"Вы будете получать ордера по фильтру (Объем: от {MIN_VOLUME} до {MAX_VOLUME}, Цена: от {MIN_PRICE} до {MAX_PRICE}).\n\nОжидайте совпадений по фильтру.")

@router.message(Command("stop"))
async def stop_command(message: Message):
    global is_started, websocket_task
    is_started = False
    if websocket_task and not websocket_task.done():
        websocket_task.cancel()
        websocket_task = None
        await message.answer("Поиск ордеров остановлен.")
        logger.info("Поиск ордеров был остановлен пользователем.")
    else:
        await message.answer("Поиск уже остановлен.")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
