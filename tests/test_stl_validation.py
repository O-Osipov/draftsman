"""Проверки загрузки STL без геометрического сравнения."""

import io
import json
from pathlib import Path
import tarfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
import trimesh

from backend.main import TEMP_DIR, app
from backend.models import Dimension, Session, SessionState, ValidateResponse
from bot.api_client import ApiClientError
from bot.handlers import Dialog, receive_file

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
            (1, "model1_plate_1hole.stl", 202),
            (2, "model2_plate_2holes.stl", 202),
            (3, "model3_shaft.stl", 202),
            (4, "model4_plate_wrong_hole.stl", 202),
            (5, "model5_broken.stl", 422),
        ]
        with tarfile.open(ARCHIVE, "r:gz") as archive:
            for number, filename, expected_status in fixtures:
                with self.subTest(filename=filename):
                    text = archive.extractfile(f"tests/dimensions/model{number}.txt").read().decode("utf-8-sig")
                    parsed = await self.client.post(
                        "/parse-dimensions", json={"user_id": 42, "raw_text": text}
                    )
                    self.assertEqual(parsed.status_code, 200, parsed.text)
                    content = archive.extractfile(f"tests/fixtures/{filename}").read()
                    response = await self.upload(filename, content, parsed.json()["dimensions"])
                    self.assertEqual(response.status_code, expected_status, response.text)
                    if expected_status == 202:
                        self.assertEqual(response.json()["size_bytes"], len(content))
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
                self.assertEqual(response.status_code, 202, response.text)

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


class BotUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_upload_preserves_dimensions_for_retry(self):
        message = Mock()
        message.from_user.id = 42
        message.document.file_name = "model.stl"
        message.document.file_size = 100
        message.document.file_id = "telegram-file"
        message.bot.download = AsyncMock(return_value=io.BytesIO(b"example"))
        message.answer = AsyncMock()
        session = Session(user_id=42, state=SessionState.AWAITING_FILE, dimensions=[Dimension(name="габарит_длина", value=100, type="LINEAR")])
        state = Mock()
        state.get_data = AsyncMock(return_value={"session": session.model_dump(mode="json")})
        state.get_state = AsyncMock(return_value=Dialog.processing.state)
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()
        response = ValidateResponse(size_bytes=7, message="STL проверен.")
        with patch("bot.handlers.api_client.validate_model", new=AsyncMock(return_value=response)) as validate:
            await receive_file(message, state)
        validate.assert_awaited_once()
        self.assertEqual(validate.await_args.args[1], "model.stl")
        self.assertEqual(validate.await_args.args[2], b"example")
        self.assertEqual(state.set_state.await_args.args[0], Dialog.awaiting_file)
        saved = Session.model_validate(state.update_data.await_args.kwargs["session"])
        self.assertEqual(saved.state, SessionState.AWAITING_FILE)
        self.assertEqual(saved.dimensions[0].value, 100)
        self.assertIn("Временный файл удалён", message.answer.await_args.args[0])

    async def test_invalid_stl_can_be_retried_with_saved_dimensions(self):
        message = Mock()
        message.from_user.id = 42
        message.document.file_name = "broken.stl"
        message.document.file_size = 43
        message.document.file_id = "broken-file"
        message.bot.download = AsyncMock(return_value=io.BytesIO(b"broken"))
        message.answer = AsyncMock()
        session = Session(user_id=42, state=SessionState.AWAITING_FILE, dimensions=[Dimension(name="габарит_длина", value=100, type="LINEAR")])
        state = Mock()
        state.get_data = AsyncMock(return_value={"session": session.model_dump(mode="json")})
        state.get_state = AsyncMock(return_value=Dialog.processing.state)
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()
        with patch("bot.handlers.api_client.validate_model", new=AsyncMock(side_effect=ApiClientError("INVALID_FILE", "Файл повреждён."))):
            await receive_file(message, state)
        saved = Session.model_validate(state.update_data.await_args.kwargs["session"])
        self.assertEqual(saved.state, SessionState.AWAITING_FILE)
        self.assertEqual(saved.dimensions[0].value, 100)
        self.assertIn("INVALID_FILE", message.answer.await_args.args[0])

    async def test_oversize_metadata_rejected_before_download(self):
        message = Mock()
        message.document.file_name = "large.stl"
        message.document.file_size = 10 * 1024 * 1024 + 1
        message.bot.download = AsyncMock()
        message.answer = AsyncMock()
        state = Mock()
        await receive_file(message, state)
        message.bot.download.assert_not_awaited()
        self.assertIn("FILE_TOO_LARGE", message.answer.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
