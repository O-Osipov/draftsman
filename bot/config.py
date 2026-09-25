"""Загрузка настроек бота."""

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_bot_token() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError(
            "Не задан BOT_TOKEN. Создайте .env по образцу .env.example "
            "и вставьте токен от @BotFather."
        )
    return token
