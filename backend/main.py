"""FastAPI: размеры и промежуточная проверка загруженного STL."""

import asyncio
import json
from pathlib import Path
import tempfile

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import ValidationError

from backend.config import ROOT, get_settings
from backend.errors import ApiError, install_error_handlers
from backend.models import Dimension, ParseRequest, ParseResponse, ValidateResponse
from backend.parsing import make_checklist, parse_dimensions
from backend.stl_validation import validate_stl

settings = get_settings()
TEMP_DIR = ROOT / ".runtime" / "uploads"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEMP_DIR)
validation_slots = asyncio.Semaphore(settings.max_concurrent_requests)

app = FastAPI(title="Чертёжник API")
install_error_handlers(app)


@app.post("/parse-dimensions", response_model=ParseResponse)
async def parse_dimensions_endpoint(request: ParseRequest) -> ParseResponse:
    dimensions = parse_dimensions(request.raw_text, settings)
    return ParseResponse(dimensions=dimensions, checklist=make_checklist(dimensions))


@app.post("/analyze-model", status_code=202, response_model=ValidateResponse)
async def analyze_model_endpoint(
    user_id: int = Form(...),
    file: UploadFile = File(...),
    dimensions: str = Form(...),
) -> ValidateResponse:
    """Пока проверяет файл; измерения и отчёт появятся на следующих этапах."""
    path: Path | None = None
    try:
        if not file.filename or not file.filename.lower().endswith(".stl"):
            raise ApiError("INVALID_FILE", "Загрузи файл с расширением .stl.")
        try:
            raw_dimensions = json.loads(dimensions)
            if not isinstance(raw_dimensions, list) or not raw_dimensions:
                raise ValueError("dimensions must be a non-empty list")
            expected = [Dimension.model_validate(item) for item in raw_dimensions]
        except (ValueError, TypeError, ValidationError) as error:
            raise ApiError("INVALID_FORMAT", "Поле dimensions должно содержать JSON-список размеров.") from error
        if len(expected) > settings.max_dimensions or len({item.name for item in expected}) != len(expected):
            raise ApiError("INVALID_FORMAT", "Слишком много размеров или повторяются названия.")

        size_bytes = 0
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".stl", dir=TEMP_DIR, delete=False) as target:
            path = Path(target.name)
            while chunk := await file.read(256 * 1024):
                size_bytes += len(chunk)
                if size_bytes > settings.max_file_size_bytes:
                    raise ApiError("FILE_TOO_LARGE", f"Максимальный размер STL — {settings.max_file_size_mb} МБ.")
                target.write(chunk)
        if size_bytes == 0:
            raise ApiError("INVALID_FILE", "Файл пуст.")
        async with validation_slots:
            await asyncio.to_thread(validate_stl, path)
        return ValidateResponse(
            size_bytes=size_bytes,
            message="STL прошёл проверку формата и структуры. Анализ размеров появится на следующем этапе.",
        )
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
        await file.close()
