"""HTTP-клиент бота для POST /parse-dimensions."""

import httpx
from pydantic import ValidationError

from bot.config import get_api_url
from backend.models import ParseResponse


class ApiClientError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


async def parse_dimensions(user_id: int, raw_text: str) -> ParseResponse:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                f"{get_api_url()}/parse-dimensions",
                json={"user_id": user_id, "raw_text": raw_text},
            )
    except httpx.HTTPError as error:
        raise ApiClientError("INTERNAL_ERROR", "Сервис проверки недоступен. Запусти FastAPI и попробуй снова.") from error
    try:
        payload = response.json()
    except ValueError as error:
        raise ApiClientError("INTERNAL_ERROR", "API вернул некорректный ответ.") from error
    if response.is_error:
        raise ApiClientError(payload.get("code", "INTERNAL_ERROR"), payload.get("message", "Ошибка API."))
    try:
        return ParseResponse.model_validate(payload)
    except ValidationError as error:
        raise ApiClientError("INTERNAL_ERROR", "API вернул ответ неверного формата.") from error
