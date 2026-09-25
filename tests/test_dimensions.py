"""Проверка этапа ввода размеров: HTTP-контракт, ошибки и диалог."""

import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from backend.config import get_settings
from backend.main import app
from backend.models import Dimension, ParseResponse, Session, SessionState
from bot.api_client import ApiClientError
from bot.handlers import Dialog, new, receive_dimensions


class ParseApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_contract_units_types_and_checklist(self):
        response = await self.client.post("/parse-dimensions", json={
            "user_id": 42,
            "raw_text": "габарит_длина=10 см, габарит_ширина=50\nотверстие_1_диаметр=0.5 in",
        })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual([item["value"] for item in body["dimensions"]], [100, 50, 12.7])
        self.assertEqual([item["type"] for item in body["dimensions"]], ["LINEAR", "LINEAR", "DIAMETER"])
        self.assertEqual(body["dimensions"][0]["tolerance"], 0.5)
        self.assertIn("100 × 50", body["checklist"][0])
        self.assertIn("Ø12.7", body["checklist"][1])

    async def test_invalid_inputs_have_standard_400_error(self):
        for text in ("габарит_длина=0", "габарит_длина=abc", "габарит_длина=10, габарит_длина=20", "x" * 2001):
            with self.subTest(text=text[:30]):
                response = await self.client.post("/parse-dimensions", json={"user_id": 42, "raw_text": text})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["status"], "error")
                self.assertEqual(response.json()["code"], "INVALID_FORMAT")
                self.assertIn("message", response.json())

    async def test_missing_field_has_standard_error(self):
        response = await self.client.post("/parse-dimensions", json={"user_id": 42})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "INVALID_FORMAT")

    async def test_unknown_name_and_duplicate_are_rejected(self):
        for text in ("неизвестный=10", "фаска_1=2, фаска_1=3"):
            response = await self.client.post("/parse-dimensions", json={"user_id": 42, "raw_text": text})
            self.assertEqual(response.status_code, 400)


class BotDialogTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_creates_session(self):
        message = Mock()
        message.from_user.id = 42
        message.answer = AsyncMock()
        state = Mock()
        state.clear = AsyncMock()
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()
        await new(message, state)
        session = Session.model_validate(state.update_data.await_args.kwargs["session"])
        self.assertEqual(session.user_id, 42)
        self.assertEqual(session.state, SessionState.AWAITING_DIMENSIONS)
        self.assertIsNotNone(session.created_at)
        state.set_state.assert_awaited_once_with(Dialog.awaiting_dimensions)

    async def test_valid_dimensions_saved_and_invalid_input_keeps_state(self):
        message = Mock(text="габарит_длина=100")
        message.from_user.id = 42
        message.answer = AsyncMock()
        state = Mock()
        state.get_data = AsyncMock(return_value={"session": Session(user_id=42, state=SessionState.AWAITING_DIMENSIONS).model_dump(mode="json")})
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()
        result = ParseResponse(dimensions=[Dimension(name="габарит_длина", value=100, type="LINEAR")], checklist=["Проверьте длину: 100 мм"])
        with patch("bot.handlers.api_client.parse_dimensions", new=AsyncMock(return_value=result)):
            await receive_dimensions(message, state)
        saved = Session.model_validate(state.update_data.await_args.kwargs["session"])
        self.assertEqual(saved.dimensions[0].value, 100)
        self.assertEqual(saved.state, SessionState.AWAITING_FILE)
        self.assertIn("Чек-лист", message.answer.await_args.args[0])
        state.update_data.reset_mock()
        state.set_state.reset_mock()
        with patch("bot.handlers.api_client.parse_dimensions", new=AsyncMock(side_effect=ApiClientError("INVALID_FORMAT", "Ошибка."))):
            await receive_dimensions(message, state)
        state.update_data.assert_not_awaited()
        state.set_state.assert_not_awaited()


class ModelAndConfigTests(unittest.TestCase):
    def test_config_and_entities(self):
        settings = get_settings()
        self.assertEqual(settings.max_text_length, 2000)
        self.assertEqual(settings.tolerance_mm, 0.5)
        dimension = Dimension(name="габарит_длина", value=100, type="LINEAR")
        self.assertEqual(dimension.unit, "мм")
        self.assertEqual(dimension.tolerance, 0.5)


if __name__ == "__main__":
    unittest.main()
