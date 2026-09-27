"""HTTP-клиент бота для локального FastAPI."""

import json

import httpx
from pydantic import ValidationError

from bot.config import get_api_url
from backend.models import AnalyzeResponse, Dimension, ParseResponse


class ApiClientError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _response_data(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError as error:
        raise ApiClientError("INTERNAL_ERROR", "API вернул некорректный ответ.") from error
    if response.is_error:
        raise ApiClientError(payload.get("code", "INTERNAL_ERROR"), payload.get("message", "Ошибка API."))
    return payload


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
        return ParseResponse.model_validate(_response_data(response))
    except ValidationError as error:
        raise ApiClientError("INTERNAL_ERROR", "API вернул ответ неверного формата.") from error


async def validate_model(user_id: int, filename: str, content: bytes, dimensions: list[Dimension]) -> AnalyzeResponse:
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.post(
                f"{get_api_url()}/analyze-model",
                data={
                    "user_id": str(user_id),
                    "dimensions": json.dumps([item.model_dump(mode="json") for item in dimensions], ensure_ascii=False),
                },
                files={"file": (filename, content, "model/stl")},
            )
    except httpx.HTTPError as error:
        raise ApiClientError("INTERNAL_ERROR", "Сервис проверки недоступен. Попробуй позже.") from error
    try:
        return AnalyzeResponse.model_validate(_response_data(response))
    except ValidationError as error:
        raise ApiClientError("INTERNAL_ERROR", "API вернул ответ неверного формата.") from error
