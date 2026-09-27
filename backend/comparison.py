"""Сопоставление контрольных размеров с измерениями STL."""

import re

from backend.geometry import Geometry
from backend.models import Dimension, Match, Mismatch, Report
from backend.parsing import format_number

NUMBERED = re.compile(r"^(?:отверстие_)?([1-9][0-9]*)_(?:диаметр|глубина)$|^(?:диаметр|глубина|фаска)_([1-9][0-9]*)$")


def _number(name: str) -> int | None:
    match = NUMBERED.fullmatch(name)
    return int(match.group(1) or match.group(2)) if match else None


def _actual(dimension: Dimension, geometry: Geometry, shaft: bool) -> float | None:
    name = dimension.name
    bounds = geometry.bounds
    if name == "габарит_длина":
        return max(bounds.x, bounds.y, bounds.z) if shaft else bounds.x
    if name == "габарит_ширина":
        return bounds.y
    if name == "габарит_высота":
        return bounds.z
    if name == "габарит_диаметр":
        values = sorted((bounds.x, bounds.y, bounds.z))
        if values[1] - values[0] <= dimension.tolerance:
            return (values[0] + values[1]) / 2
        return None
    number = _number(name)
    if number is None:
        return None
    if name.startswith("фаска_"):
        return geometry.chamfers[number - 1].size if number <= len(geometry.chamfers) else None
    if number > len(geometry.holes):
        return None
    hole = geometry.holes[number - 1]
    if name.endswith("_диаметр") or name.startswith("диаметр_"):
        return hole.diameter
    if name.endswith("_глубина") or name.startswith("глубина_"):
        return hole.depth
    return None


def compare_dimensions(user_id: int, dimensions: list[Dimension], geometry: Geometry) -> Report:
    shaft = any(item.name == "габарит_диаметр" for item in dimensions) and not any(
        item.name in {"габарит_ширина", "габарит_высота"} for item in dimensions
    )
    matches: list[Match] = []
    mismatches: list[Mismatch] = []
    for dimension in dimensions:
        actual = _actual(dimension, geometry, shaft)
        if actual is None:
            mismatches.append(Mismatch(dimension_name=dimension.name, expected=dimension.value, actual=None, delta=None))
            continue
        delta = actual - dimension.value
        fields = dict(dimension_name=dimension.name, expected=dimension.value, actual=actual, delta=delta)
        if abs(delta) <= dimension.tolerance + 1e-9:
            matches.append(Match(**fields))
        else:
            mismatches.append(Mismatch(**fields))
    summary = f"Совпало {len(matches)} из {len(dimensions)} размеров."
    if mismatches:
        details = []
        for item in mismatches:
            if item.actual is None:
                details.append(f"{item.dimension_name}: не найдено")
            else:
                details.append(
                    f"{item.dimension_name}: ожидалось {format_number(item.expected)} мм, "
                    f"получено {format_number(item.actual)} мм"
                )
        summary += " Расхождения: " + "; ".join(details) + "."
    return Report(session_id=user_id, matches=matches, mismatches=mismatches, summary=summary)
