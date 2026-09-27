"""Извлечение осевых габаритов STL без сравнения с чертежом."""

import numpy as np
import trimesh

from backend.errors import ApiError
from backend.models import AxisBounds


def measure_bounds(mesh: trimesh.Trimesh) -> AxisBounds:
    extents = np.asarray(mesh.bounding_box.extents, dtype=float)
    if extents.shape != (3,) or not np.isfinite(extents).all() or (extents <= 0).any():
        raise ApiError("INVALID_FILE", "Не удалось определить три положительных габарита STL.")
    return AxisBounds(x=float(extents[0]), y=float(extents[1]), z=float(extents[2]))
