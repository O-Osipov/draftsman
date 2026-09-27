"""Проверки загрузки и отчёта по пользовательским STL."""

import json
from pathlib import Path
import tarfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
import trimesh

from backend.main import TEMP_DIR, app, settings
from backend.models import AnalyzeResponse, Dimension, Mismatch, Report, Session, SessionState
from bot.api_client import ApiClientError
from bot.handlers import BOT_TEMP_DIR, Dialog, receive_file, unsupported_file_message

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data" / "tests.tar.gz"


class StlApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        )
        parsed = await self.client.post(
            "/parse-dimensions",
            json={"user_id": 42, "raw_text": "габарит_длина=100"},
        )
        self.dimensions = parsed.json()["dimensions"]

    async def asyncTearDown(self):
        await self.client.aclose()
        self.assertEqual(list(TEMP_DIR.glob("*.stl")), [])

    async def upload(self, filename: str, content: bytes, dimensions=None):
        return await self.client.post(
            "/analyze-model",
            data={
                "user_id": "42",
                "dimensions": json.dumps(dimensions if dimensions is not None else self.dimensions, ensure_ascii=False),
            },
            files={"file": (filename, content, "model/stl")},
        )

    async def test_five_stl_files_from_user_archive(self):
        if not ARCHIVE.exists():
            self.skipTest("Локальный архив data/tests.tar.gz не предоставлен")
        fixtures = [
            (1, "model1_plate_1hole.stl", 200, 4, 0),
            (2, "model2_plate_2holes.stl", 200, 5, 0),
            (3, "model3_shaft.stl", 200, 2, 0),
            (4, "model4_plate_wrong_hole.stl", 200, 3, 1),
            (5, "model5_broken.stl", 422, None, None),
        ]
        with tarfile.open(ARCHIVE, "r:gz") as archive:
            for number, filename, expected_status, expected_matches, expected_mismatches in fixtures:
                with self.subTest(filename=filename):
                    text = archive.extractfile(f"tests/dimensions/model{number}.txt").read().decode("utf-8-sig")
                    parsed = await self.client.post(
                        "/parse-dimensions", json={"user_id": 42, "raw_text": text}
                    )
                    self.assertEqual(parsed.status_code, 200, parsed.text)
                    content = archive.extractfile(f"tests/fixtures/{filename}").read()
                    response = await self.upload(filename, content, parsed.json()["dimensions"])
                    self.assertEqual(response.status_code, expected_status, response.text)
                    if expected_status == 200:
                        report = response.json()["report"]
                        self.assertEqual(report["session_id"], 42)
                        self.assertEqual(len(report["matches"]), expected_matches)
                        self.assertEqual(len(report["mismatches"]), expected_mismatches)
                        self.assertIn("Отчёт о проверке:", report["telegram_text"])
                        self.assertLessEqual(len(report["telegram_text"]), settings.report_max_chars)
                        if number == 4:
                            mismatch = report["mismatches"][0]
                            self.assertEqual(mismatch["name"], "отверстие_1_диаметр")
                            self.assertAlmostEqual(mismatch["actual"], 8, places=3)
                            self.assertIn("получено 8 мм", report["telegram_text"])
                    else:
                        self.assertEqual(response.json()["code"], "INVALID_FILE")
                    self.assertEqual(list(TEMP_DIR.glob("*.stl")), [])

    async def test_ascii_and_binary_stl_are_accepted(self):
        mesh = trimesh.creation.box(extents=[100, 50, 10])
        for kind in ("stl", "stl_ascii"):
            with self.subTest(kind=kind):
                content = mesh.export(file_type=kind)
                if isinstance(content, str):
                    content = content.encode("ascii")
                response = await self.upload("box.stl", content)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(len(response.json()["report"]["matches"]), 1)

    async def test_file_errors_and_temporary_cleanup(self):
        cases = [
            ("wrong.txt", b"abc", 422, "INVALID_FILE"),
            ("empty.stl", b"", 422, "INVALID_FILE"),
            ("large.stl", b"x" * (10 * 1024 * 1024 + 1), 413, "FILE_TOO_LARGE"),
        ]
        for filename, content, status, code in cases:
            with self.subTest(filename=filename):
                response = await self.upload(filename, content)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["code"], code)
                self.assertEqual(list(TEMP_DIR.glob("*.stl")), [])

    async def test_bad_dimensions_and_missing_file(self):
        response = await self.client.post(
            "/analyze-model",
            data={"user_id": "42", "dimensions": "not json"},
            files={"file": ("model.stl", b"abc", "model/stl")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "INVALID_FORMAT")
        wrong_type = [{**self.dimensions[0], "type": "DIAMETER"}]
        response = await self.upload("box.stl", b"invalid contents", wrong_type)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "INVALID_FORMAT")
        response = await self.client.post(
            "/analyze-model", data={"user_id": "42", "dimensions": "[]"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "INVALID_FILE")
        response = await self.client.post(
            "/analyze-model",
            data={"user_id": "42"},
            files={"file": ("model.stl", b"abc", "model/stl")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "INVALID_FORMAT")

    async def test_timeout_has_504_and_deletes_temporary_file(self):
        mesh = trimesh.creation.box(extents=[100, 50, 10])
        with patch.object(settings, "timeout_sec", 0.001):
            response = await self.upload("box.stl", mesh.export(file_type="stl"))
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["code"], "TIMEOUT")
        self.assertEqual(list(TEMP_DIR.glob("*.stl")), [])

    async def test_unexpected_analysis_error_has_500_and_deletes_file(self):
        mesh = trimesh.creation.box(extents=[100, 50, 10])
        with patch("backend.main._run_analysis", new=AsyncMock(side_effect=RuntimeError("synthetic failure"))), patch("logging.exception"):
            response = await self.upload("box.stl", mesh.export(file_type="stl"))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], "INTERNAL_ERROR")
        self.assertEqual(list(TEMP_DIR.glob("*.stl")), [])


class BotUploadTests(unittest.IsolatedAsyncioTestCase):
    def make_message_and_state(self, content: bytes = b"example"):
        message = Mock()
        message.from_user.id = 42
        message.document.file_name = "model.stl"
        message.document.file_size = len(content)
        message.document.file_id = "telegram-file"

        async def download(document, destination):
            destination.write_bytes(content)
            return None

        message.bot.download = AsyncMock(side_effect=download)
        message.answer = AsyncMock()
        session = Session(user_id=42, state=SessionState.AWAITING_FILE, dimensions=[
            Dimension(name="габарит_длина", value=100, type="LINEAR")
        ])
        state = Mock()
        state.get_data = AsyncMock(return_value={"session": session.model_dump(mode="json")})
        state.get_state = AsyncMock(return_value=Dialog.processing.state)
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()
        state.clear = AsyncMock()
        return message, state

    async def test_mismatch_keeps_dimensions_for_retry_and_deletes_temp_file(self):
        message, state = self.make_message_and_state()
        report = Report(
            session_id=42, summary="0 из 1 размеров совпали.",
            telegram_text="Отчёт о проверке:\nРасхождения:\n• габарит_длина",
            mismatches=[Mismatch(dimension_name="габарит_длина", expected=100, actual=90, delta=-10)],
        )
        with patch("bot.handlers.api_client.validate_model", new=AsyncMock(return_value=AnalyzeResponse(report=report))) as validate:
            await receive_file(message, state)
        validate.assert_awaited_once()
        self.assertEqual(validate.await_args.args[1], "model.stl")
        self.assertFalse(validate.await_args.args[2].exists())
        self.assertEqual(state.set_state.await_args.args[0], Dialog.awaiting_file)
        saved = Session.model_validate(state.update_data.await_args.kwargs["session"])
        self.assertEqual(saved.dimensions[0].value, 100)
        self.assertIn("Расхождения", message.answer.await_args.args[0])
        self.assertEqual(list(BOT_TEMP_DIR.glob("*.stl")), [])

    async def test_all_matching_ends_session(self):
        message, state = self.make_message_and_state()
        report = Report(session_id=42, summary="1 из 1 размеров совпали.", telegram_text="Отчёт о проверке:\nСовпало:")
        with patch("bot.handlers.api_client.validate_model", new=AsyncMock(return_value=AnalyzeResponse(report=report))):
            await receive_file(message, state)
        state.clear.assert_awaited_once()
        self.assertIn("Отчёт о проверке", message.answer.await_args.args[0])
        self.assertEqual(list(BOT_TEMP_DIR.glob("*.stl")), [])

    async def test_invalid_stl_can_be_retried_with_saved_dimensions(self):
        message, state = self.make_message_and_state(b"broken")
        with patch("bot.handlers.api_client.validate_model", new=AsyncMock(side_effect=ApiClientError("INVALID_FILE", "Файл повреждён."))):
            await receive_file(message, state)
        saved = Session.model_validate(state.update_data.await_args.kwargs["session"])
        self.assertEqual(saved.state, SessionState.AWAITING_FILE)
        self.assertEqual(saved.dimensions[0].value, 100)
        self.assertIn("INVALID_FILE", message.answer.await_args.args[0])
        self.assertIn("Экспортируй", message.answer.await_args.args[0])
        self.assertEqual(list(BOT_TEMP_DIR.glob("*.stl")), [])

    async def test_timeout_keeps_dimensions_and_gives_retry_advice(self):
        message, state = self.make_message_and_state()
        with patch("bot.handlers.api_client.validate_model", new=AsyncMock(side_effect=ApiClientError("TIMEOUT", "Анализ превысил 30 секунд."))):
            await receive_file(message, state)
        self.assertEqual(state.set_state.await_args.args[0], Dialog.awaiting_file)
        self.assertIn("TIMEOUT", message.answer.await_args.args[0])
        self.assertIn("Упрости STL", message.answer.await_args.args[0])
        self.assertEqual(list(BOT_TEMP_DIR.glob("*.stl")), [])

    async def test_photo_in_file_state_gets_file_guidance(self):
        message = Mock()
        message.answer = AsyncMock()
        await unsupported_file_message(message)
        self.assertIn("Загрузи STL как документ", message.answer.await_args.args[0])

    async def test_oversize_metadata_rejected_before_download(self):
        message, state = self.make_message_and_state()
        message.document.file_size = 10 * 1024 * 1024 + 1
        await receive_file(message, state)
        message.bot.download.assert_not_awaited()
        self.assertIn("FILE_TOO_LARGE", message.answer.await_args.args[0])

    async def test_actual_download_size_is_checked_and_deleted(self):
        message, state = self.make_message_and_state(b"123456789")
        message.document.file_size = 1
        with patch("bot.handlers.get_settings") as configured:
            configured.return_value.max_file_size_bytes = 8
            await receive_file(message, state)
        self.assertIn("FILE_TOO_LARGE", message.answer.await_args.args[0])
        self.assertEqual(list(BOT_TEMP_DIR.glob("*.stl")), [])


if __name__ == "__main__":
    unittest.main()
