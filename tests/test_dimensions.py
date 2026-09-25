import unittest
from unittest.mock import AsyncMock, Mock

from bot.dimensions import DimensionError, format_checklist, parse_dimensions
from bot.handlers import Dialog, receive_dimensions


class ParseDimensionsTests(unittest.TestCase):
    def test_multiple_dimensions_and_unit_conversion(self):
        dimensions = parse_dimensions(
            "габарит_длина=10 см, габарит_ширина=50\n"
            "отверстие_1_диаметр=0.5 in\n"
            "отверстие_1_глубина=2 см, фаска_1=1"
        )
        self.assertEqual([item.type for item in dimensions], [
            "LINEAR", "LINEAR", "DIAMETER", "DEPTH", "CHAMFER"
        ])
        self.assertEqual([item.value for item in dimensions], [100, 50, 12.7, 20, 1])
        self.assertTrue(all(item.unit == "мм" for item in dimensions))
        self.assertIn("Отверстие 1: диаметр — 12.7 мм", format_checklist(dimensions))

    def test_invalid_input_is_rejected(self):
        cases = [
            "габарит_длина", "габарит_длина=0", "габарит_длина=-1",
            "габарит_длина=abc", "произвольный=10",
            "габарит_длина=10, габарит_длина=20", "габарит_длина=1 км",
            "габарит_длина=10,5", "x" * 2001,
        ]
        for raw_text in cases:
            with self.subTest(raw_text=raw_text), self.assertRaises(DimensionError):
                parse_dimensions(raw_text)

    def test_one_bad_dimension_rejects_whole_message(self):
        with self.assertRaises(DimensionError):
            parse_dimensions("габарит_длина=100, отверстие_1_диаметр=не число")


class ReceiveDimensionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_saves_dimensions_and_moves_to_file_state(self):
        message = Mock(text="габарит_длина=100, отверстие_1_диаметр=10")
        message.answer = AsyncMock()
        state = Mock()
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()

        await receive_dimensions(message, state)

        state.update_data.assert_awaited_once()
        saved = state.update_data.await_args.kwargs["dimensions"]
        self.assertEqual([item["name"] for item in saved], [
            "габарит_длина", "отверстие_1_диаметр"
        ])
        state.set_state.assert_awaited_once_with(Dialog.awaiting_file)
        self.assertIn("Чек-лист", message.answer.await_args.args[0])

    async def test_invalid_input_keeps_current_state(self):
        message = Mock(text="габарит_длина=0")
        message.answer = AsyncMock()
        state = Mock()
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()

        await receive_dimensions(message, state)

        state.update_data.assert_not_awaited()
        state.set_state.assert_not_awaited()
        self.assertIn("Не удалось", message.answer.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
