"""Одноразовый процесс анализа STL с ограниченным временем жизни."""

import json
from pathlib import Path
import sys

from backend.comparison import compare_dimensions
from backend.config import get_settings
from backend.errors import ApiError
from backend.geometry import analyze_geometry
from backend.models import Dimension
from backend.reporting import format_report
from backend.stl_validation import validate_stl


def main() -> None:
    path = Path(sys.argv[1])
    user_id = int(sys.argv[2])
    try:
        dimensions = [Dimension.model_validate(item) for item in json.load(sys.stdin)]
        mesh = validate_stl(path)
        geometry = analyze_geometry(mesh)
        report = compare_dimensions(user_id, dimensions, geometry)
        report.telegram_text = format_report(report, get_settings().report_max_chars)
        result = {"status": "ok", "report": report.model_dump(mode="json", by_alias=True)}
    except ApiError as error:
        result = {"status": "error", "code": error.code, "message": error.message}
    except Exception:
        result = {"status": "error", "code": "INTERNAL_ERROR", "message": "Внутренняя ошибка. Попробуйте позже."}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
