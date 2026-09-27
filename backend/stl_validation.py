"""Загрузка и структурная проверка STL."""

from pathlib import Path

import numpy as np
import trimesh

from backend.errors import ApiError


def validate_stl(path: Path) -> trimesh.Trimesh:
    try:
        mesh = trimesh.load_mesh(str(path), file_type="stl")
    except Exception as error:
        raise ApiError("INVALID_FILE", "Файл повреждён или не является STL.") from error
    if (
        not isinstance(mesh, trimesh.Trimesh)
        or mesh.is_empty
        or len(mesh.vertices) == 0
        or len(mesh.faces) == 0
        or not np.isfinite(mesh.vertices).all()
        or not mesh.is_watertight
    ):
        raise ApiError("INVALID_FILE", "STL должен содержать непустую замкнутую модель.")
    return mesh
