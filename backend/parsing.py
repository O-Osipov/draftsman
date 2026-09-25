"""Разбор контрольных размеров выполняется на стороне FastAPI."""

import math
import re

from backend.config import Settings, get_settings
from backend.errors import ApiError
from backend.models import Dimension, DimensionType

VALUE_PATTERN = re.compile(r"([+]?(?:\d+(?:\.\d*)?|\.\d+))(?:\s*(мм|см|дюйм|in))?", re.I)
UNIT_FACTORS = {"мм": 1.0, "см": 10.0, "дюйм": 25.4, "in": 25.4}


def parse_dimensions(raw_text: str, settings: Settings | None = None) -> list[Dimension]:
    settings = settings or get_settings()
    if not raw_text or not raw_text.strip():
        raise ApiError("INVALID_FORMAT", "Введи хотя бы один размер в формате название=значение.")
    if len(raw_text) > settings.max_text_length:
        raise ApiError("INVALID_FORMAT", f"Максимум {settings.max_text_length} символов.")
    parts = [part.strip() for part in re.split(r"[,\n]+", raw_text) if part.strip()]
    if len(parts) > settings.max_dimensions:
        raise ApiError("INVALID_FORMAT", f"Максимум {settings.max_dimensions} размеров.")
    dimensions: list[Dimension] = []
    names: set[str] = set()
    for part in parts:
        if part.count("=") != 1:
            raise ApiError("INVALID_FORMAT", f"Не удалось прочитать «{part}». Используй название=значение.")
        raw_name, raw_value = (piece.strip() for piece in part.split("=", 1))
        name = raw_name.lower()
        rule = next((rule for rule in settings.dimension_types if re.fullmatch(rule.pattern, name)), None)
        if rule is None:
            raise ApiError("INVALID_FORMAT", f"Неизвестное название «{raw_name}». Посмотри примеры в /help.")
        if name in names:
            raise ApiError("INVALID_FORMAT", f"Размер «{name}» указан дважды.")
        match = VALUE_PATTERN.fullmatch(raw_value)
        if not match:
            raise ApiError("INVALID_FORMAT", f"Неверное значение у «{name}». Пример: 10.5 см.")
        value = float(match.group(1))
        value_mm = value * UNIT_FACTORS[(match.group(2) or "мм").lower()]
        if not math.isfinite(value_mm) or value_mm <= 0:
            raise ApiError("INVALID_FORMAT", f"Размер «{name}» должен быть конечным числом больше нуля.")
        dimensions.append(Dimension(
            name=name, value=value_mm, unit="мм",
            type=DimensionType(rule.type), tolerance=settings.tolerance_mm,
        ))
        names.add(name)
    if not dimensions:
        raise ApiError("INVALID_FORMAT", "Введи хотя бы один размер.")
    return dimensions


def format_number(value: float) -> str:
    return f"{value:g}"


def make_checklist(dimensions: list[Dimension]) -> list[str]:
    by_name = {dimension.name: dimension for dimension in dimensions}
    checklist: list[str] = []
    length = by_name.get("габарит_длина")
    width = by_name.get("габарит_ширина")
    height = by_name.get("габарит_высота")
    used: set[str] = set()
    if length and width:
        measures = [length, width]
        if height:
            measures.append(height)
        values = " × ".join(format_number(item.value) for item in measures)
        checklist.append(f"Постройте деталь с габаритами {values} мм")
        used.update(item.name for item in measures)
    for dimension in dimensions:
        if dimension.name in used:
            continue
        value = format_number(dimension.value)
        number = dimension.name.split("_")[1] if "_" in dimension.name else ""
        if dimension.type == DimensionType.LINEAR:
            checklist.append(f"Проверьте {number}: {value} мм")
        elif dimension.type == DimensionType.DIAMETER:
            label = f"Сделайте отверстие {number}" if dimension.name.startswith("отверстие_") else f"Проверьте диаметр {number}"
            checklist.append(f"{label}: Ø{value} мм")
        elif dimension.type == DimensionType.DEPTH:
            label = f"Проверьте глубину отверстия {number}" if dimension.name.startswith("отверстие_") else f"Проверьте глубину {number}"
            checklist.append(f"{label}: {value} мм")
        else:
            checklist.append(f"Сделайте фаску {number}: {value} мм")
    return checklist
