"""Запуск: python -m bot."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import get_bot_token
from bot.handlers import router


async def main() -> None:
    bot = Bot(token=get_bot_token())
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)
    logging.info("Бот запущен. Ожидаю сообщения в Telegram.")
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")
