"""Настройки Telegram-бота."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_environment() -> None:
    load_dotenv(PROJECT_ROOT / ".env")


def get_bot_token() -> str:
    load_environment()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError("Не задан BOT_TOKEN. Добавь токен от @BotFather в .env.")
    return token


def get_api_url() -> str:
    load_environment()
    return os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
