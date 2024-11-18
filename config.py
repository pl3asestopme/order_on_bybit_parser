import os
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if BOT_TOKEN is None:
    raise ValueError("Токен не найден! Проверьте файл .env.")
else:
    print('Токен найден!')