"""Проверка контрольных размеров и формирование чек-листа."""

from dataclasses import asdict, dataclass
import math
import re


MAX_TEXT_LENGTH = 2000
MAX_DIMENSIONS = 30
DEFAULT_TOLERANCE_MM = 0.5

NAME_PATTERN = re.compile(
    r"(?:габарит_(?:длина|ширина|высота)|"
    r"отверстие_[1-9]\d*_(?:диаметр|глубина)|"
    r"фаска_[1-9]\d*)"
)
VALUE_PATTERN = re.compile(r"([+]?(?:\d+(?:\.\d*)?|\.\d+))(?:\s*(мм|см|дюйм|in))?", re.IGNORECASE)
UNIT_FACTORS = {"мм": 1.0, "см": 10.0, "дюйм": 25.4, "in": 25.4}


class DimensionError(ValueError):
    """Ошибка ввода, которую можно показать пользователю."""


@dataclass(frozen=True)
class Dimension:
    name: str
    value: float  # Всегда в миллиметрах.
    unit: str
    type: str
    tolerance: float = DEFAULT_TOLERANCE_MM

    def to_dict(self) -> dict:
        return asdict(self)


def _dimension_type(name: str) -> str:
    if name.startswith("габарит_"):
        return "LINEAR"
    if name.endswith("_диаметр"):
        return "DIAMETER"
    if name.endswith("_глубина"):
        return "DEPTH"
    return "CHAMFER"


def parse_dimensions(raw_text: str) -> list[Dimension]:
    if not raw_text or not raw_text.strip():
        raise DimensionError("Введи хотя бы один размер в формате название=значение.")
    if len(raw_text) > MAX_TEXT_LENGTH:
        raise DimensionError(f"Слишком длинное сообщение: максимум {MAX_TEXT_LENGTH} символов.")

    parts = re.split(r"[,\n]+", raw_text)
    dimensions: list[Dimension] = []
    names: set[str] = set()
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.count("=") != 1:
            raise DimensionError(f"Не удалось прочитать «{part}». Используй формат название=значение.")
        raw_name, raw_value = (piece.strip() for piece in part.split("=", 1))
        name = raw_name.lower()
        if not NAME_PATTERN.fullmatch(name):
            raise DimensionError(
                f"Неизвестное название «{raw_name}». Примеры: габарит_длина, "
                "отверстие_1_диаметр, отверстие_1_глубина, фаска_1."
            )
        if name in names:
            raise DimensionError(f"Размер «{name}» указан дважды. Укажи его один раз.")
        value_match = VALUE_PATTERN.fullmatch(raw_value)
        if not value_match:
            raise DimensionError(
                f"Неверное значение у «{name}». Введи положительное число, "
                "например 10, 10.5 или 2 см. Для дробной части используй точку."
            )
        number = float(value_match.group(1))
        if not math.isfinite(number) or number <= 0:
            raise DimensionError(f"Значение «{name}» должно быть больше нуля.")
        source_unit = (value_match.group(2) or "мм").lower()
        value_mm = number * UNIT_FACTORS[source_unit]
        if not math.isfinite(value_mm):
            raise DimensionError(f"Слишком большое значение у «{name}».")
        dimensions.append(
            Dimension(
                name=name,
                value=value_mm,
                unit="мм",
                type=_dimension_type(name),
            )
        )
        names.add(name)
        if len(dimensions) > MAX_DIMENSIONS:
            raise DimensionError(f"Слишком много размеров: максимум {MAX_DIMENSIONS}.")

    if not dimensions:
        raise DimensionError("Введи хотя бы один размер в формате название=значение.")
    return dimensions


def format_checklist(dimensions: list[Dimension]) -> str:
    lines = ["Чек-лист для построения:"]
    for index, dimension in enumerate(dimensions, start=1):
        if dimension.type == "LINEAR":
            label = f"Габарит {dimension.name.removeprefix('габарит_')}"
        elif dimension.type == "DIAMETER":
            label = f"Отверстие {dimension.name.split('_')[1]}: диаметр"
        elif dimension.type == "DEPTH":
            label = f"Отверстие {dimension.name.split('_')[1]}: глубина"
        else:
            label = f"Фаска {dimension.name.split('_')[1]}"
        lines.append(f"{index}. {label} — {dimension.value:g} мм")
    return "\n".join(lines)
