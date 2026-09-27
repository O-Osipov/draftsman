"""Сквозной путь бот → FastAPI → анализ → отчёт без Telegram-токена."""

from pathlib import Path
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from backend.main import TEMP_DIR, app
from bot.handlers import BOT_TEMP_DIR, Dialog, new, receive_dimensions, receive_file

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "tests" / "fixtures"
DIMENSIONS = ROOT / "data" / "tests" / "dimensions" / "model4.txt"


class MemoryState:
    def __init__(self):
        self.current = None
        self.data = {}

    async def clear(self):
        self.current = None
        self.data.clear()

    async def get_state(self):
        return self.current

    async def set_state(self, state):
        self.current = state.state

    async def get_data(self):
        return self.data.copy()

    async def update_data(self, **items):
        self.data.update(items)


def telegram_message(filename: str | None = None):
    message = Mock()
    message.from_user.id = 42
    message.answer = AsyncMock()
    if filename:
        path = FIXTURES / filename
        message.document.file_name = filename
        message.document.file_size = path.stat().st_size

        async def download(document, destination):
            destination.write_bytes(path.read_bytes())
            return None

        message.bot.download = AsyncMock(side_effect=download)
    return message


class BotApiIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_model_then_corrected_model(self):
        if not DIMENSIONS.exists():
            self.skipTest("Локальные STL из архива не предоставлены")
        original_client = httpx.AsyncClient

        def local_client(*args, **kwargs):
            return original_client(
                *args, transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), **kwargs
            )

        state = MemoryState()
        with patch("bot.api_client.httpx.AsyncClient", new=local_client), patch(
            "bot.api_client.get_api_url", return_value="http://test"
        ):
            start_message = telegram_message()
            await new(start_message, state)
            self.assertEqual(state.current, Dialog.awaiting_dimensions.state)

            dimensions_message = telegram_message()
            dimensions_message.text = DIMENSIONS.read_text(encoding="utf-8-sig")
            await receive_dimensions(dimensions_message, state)
            self.assertEqual(state.current, Dialog.awaiting_file.state)
            self.assertIn("Чек-лист", dimensions_message.answer.await_args.args[0])

            wrong = telegram_message("model4_plate_wrong_hole.stl")
            await receive_file(wrong, state)
            self.assertEqual(state.current, Dialog.awaiting_file.state)
            self.assertEqual(len(state.data["session"]["dimensions"]), 4)
            self.assertIn("Расхождения:", wrong.answer.await_args.args[0])
            self.assertIn("получено 8 мм", wrong.answer.await_args.args[0])
            self.assertEqual(list(BOT_TEMP_DIR.glob("*.stl")), [])
            self.assertEqual(list(TEMP_DIR.glob("*.stl")), [])

            corrected = telegram_message("model1_plate_1hole.stl")
            await receive_file(corrected, state)
            self.assertIsNone(state.current)
            self.assertEqual(state.data, {})
            self.assertIn("Совпало:", corrected.answer.await_args.args[0])
            self.assertIn("Расхождения:\n• Не обнаружены", corrected.answer.await_args.args[0])
            self.assertEqual(list(BOT_TEMP_DIR.glob("*.stl")), [])
            self.assertEqual(list(TEMP_DIR.glob("*.stl")), [])


if __name__ == "__main__":
    unittest.main()
