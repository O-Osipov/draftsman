"""FastAPI: разбор размеров и сравнение STL с чертежом."""

import asyncio
import json
from pathlib import Path
import re
import sys
import tempfile

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import ValidationError

from backend.config import ROOT, get_settings
from backend.errors import ApiError, install_error_handlers
from backend.models import AnalyzeResponse, Dimension, ParseRequest, ParseResponse, Report
from backend.parsing import make_checklist, parse_dimensions

settings = get_settings()
TEMP_DIR = ROOT / ".runtime" / "uploads"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEMP_DIR)
request_slots = asyncio.Semaphore(settings.max_concurrent_requests)

app = FastAPI(title="Чертёжник API")
install_error_handlers(app)


@app.post("/parse-dimensions", response_model=ParseResponse)
async def parse_dimensions_endpoint(request: ParseRequest) -> ParseResponse:
    async with request_slots:
        dimensions = parse_dimensions(request.raw_text, settings)
        return ParseResponse(dimensions=dimensions, checklist=make_checklist(dimensions))


@app.post("/analyze-model", response_model=AnalyzeResponse)
async def analyze_model_endpoint(
    user_id: int = Form(...),
    file: UploadFile = File(...),
    dimensions: str = Form(...),
) -> AnalyzeResponse:
    """Возвращает отчёт о сравнении контрольных размеров и STL."""
    async with request_slots:
        return await _handle_analysis(user_id, file, dimensions)


async def _handle_analysis(user_id: int, file: UploadFile, dimensions: str) -> AnalyzeResponse:
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
        for dimension in expected:
            rule = next(
                (rule for rule in settings.dimension_types if re.fullmatch(rule.pattern, dimension.name)),
                None,
            )
            if rule is None or dimension.type != rule.type:
                raise ApiError("INVALID_FORMAT", f"Недопустимый тип или название размера «{dimension.name}».")

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
        report = await _run_analysis(path, user_id, expected)
        return AnalyzeResponse(report=report)
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
        await file.close()


async def _run_analysis(path: Path, user_id: int, dimensions: list[Dimension]) -> Report:
    """Прерывает долгий анализ и дожидается процесса до удаления файла."""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "backend.worker", str(path), str(user_id),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=str(ROOT),
    )
    payload = json.dumps([item.model_dump(mode="json") for item in dimensions], ensure_ascii=False).encode()
    exchange = asyncio.create_task(process.communicate(payload))
    try:
        try:
            stdout, _ = await asyncio.wait_for(asyncio.shield(exchange), timeout=settings.timeout_sec)
        except TimeoutError as error:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await exchange
            raise ApiError("TIMEOUT", f"Анализ STL превысил {settings.timeout_sec} секунд. Попробуй ещё раз.") from error
        if process.returncode != 0:
            raise ApiError("INTERNAL_ERROR", "Не удалось завершить анализ STL.")
        try:
            result = json.loads(stdout)
            if result.get("status") == "error":
                code = result.get("code", "INTERNAL_ERROR")
                if code not in {"INVALID_FILE", "INTERNAL_ERROR"}:
                    code = "INTERNAL_ERROR"
                raise ApiError(code, result.get("message", "Ошибка анализа STL."))
            return Report.model_validate(result["report"])
        except (ValueError, KeyError, ValidationError, TypeError) as error:
            raise ApiError("INTERNAL_ERROR", "Сервис анализа вернул некорректный отчёт.") from error
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await exchange
