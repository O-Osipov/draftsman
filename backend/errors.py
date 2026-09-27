"""Единый формат ошибок API."""

from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


ERROR_STATUSES = {
    "INVALID_FORMAT": 400,
    "INVALID_FILE": 422,
    "FILE_TOO_LARGE": 413,
    "TIMEOUT": 504,
    "INTERNAL_ERROR": 500,
}


@dataclass
class ApiError(Exception):
    code: str
    message: str

    @property
    def status_code(self) -> int:
        return ERROR_STATUSES[self.code]


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"status": "error", "code": error.code, "message": error.message},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
        has_file_error = any(item["loc"][-1] == "file" for item in error.errors())
        code = "INVALID_FILE" if request.url.path == "/analyze-model" and has_file_error else "INVALID_FORMAT"
        return JSONResponse(
            status_code=ERROR_STATUSES[code],
            content={"status": "error", "code": code, "message": "Проверь обязательные поля запроса и их формат."},
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, error: Exception) -> JSONResponse:
        import logging

        logging.exception("Unexpected API error", exc_info=error)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "code": "INTERNAL_ERROR", "message": "Внутренняя ошибка. Попробуйте позже."},
        )
