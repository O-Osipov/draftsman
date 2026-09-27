"""Форматирование отчёта в FastAPI для отправки через Telegram."""

from backend.models import Report
from backend.parsing import format_number


def format_report(report: Report, limit: int) -> str:
    total = len(report.matches) + len(report.mismatches)
    lines = ["Отчёт о проверке:", f"{len(report.matches)} из {total} размеров совпали.", "", "Совпало:"]
    if report.matches:
        for item in report.matches:
            lines.append(
                f"• {item.dimension_name}: {format_number(item.expected)} мм "
                f"(факт: {format_number(item.actual)} мм)"
            )
    else:
        lines.append("• Нет совпадений")
    lines.extend(["", "Расхождения:"])
    if report.mismatches:
        for item in report.mismatches:
            if item.actual is None:
                lines.append(
                    f"• {item.dimension_name}: ожидалось {format_number(item.expected)} мм, не найдено"
                )
            else:
                lines.append(
                    f"• {item.dimension_name}: ожидалось {format_number(item.expected)} мм, "
                    f"получено {format_number(item.actual)} мм"
                )
    else:
        lines.append("• Не обнаружены")
    lines.append("")
    if report.mismatches:
        if len(report.mismatches) == 1 and report.mismatches[0].dimension_name.startswith("отверстие_"):
            lines.append("Исправь отверстие и загрузи модель заново.")
        else:
            lines.append("Исправь расхождения и загрузи модель заново.")
    else:
        lines.append("Все указанные размеры совпали.")
    text = "\n".join(lines)
    if len(text) <= limit:
        return text
    # При длинном списке не обрезаем строку посреди размера и сообщаем о пропуске.
    suffix = "\nЧасть строк не показана из-за лимита Telegram. Полный отчёт доступен через API."
    if len(suffix) > limit:
        return "Отчёт сокращён."[:limit]
    kept: list[str] = []
    for line in lines:
        candidate = "\n".join(kept + [line]) + suffix
        if len(candidate) > limit:
            break
        kept.append(line)
    return "\n".join(kept) + suffix
