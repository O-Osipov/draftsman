"""Ограниченный анализ простых осевых отверстий и фасок в треугольной сетке."""

from dataclasses import dataclass

import numpy as np
import trimesh

from backend.bounds import measure_bounds
from backend.models import AxisBounds, Chamfer, Hole

AXES = "xyz"


@dataclass(frozen=True)
class Geometry:
    bounds: AxisBounds
    holes: list[Hole]
    chamfers: list[Chamfer]


def _groups(mesh: trimesh.Trimesh, face_ids: np.ndarray) -> list[list[int]]:
    """Связные группы выбранных граней по общим рёбрам."""
    selected = set(int(i) for i in face_ids)
    parent = {i: i for i in selected}

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for first, second in mesh.face_adjacency:
        a, b = int(first), int(second)
        if a in selected and b in selected:
            parent[root(a)] = root(b)
    grouped: dict[int, list[int]] = {}
    for face_id in selected:
        grouped.setdefault(root(face_id), []).append(face_id)
    return list(grouped.values())


def find_holes(mesh: trimesh.Trimesh) -> list[Hole]:
    """Ищет круговые внутренние стенки, параллельные X, Y или Z."""
    result: list[Hole] = []
    for axis in range(3):
        axial_span = np.ptp(mesh.vertices[mesh.faces][:, :, axis], axis=1)
        candidates = np.flatnonzero(
            (np.abs(mesh.face_normals[:, axis]) < 0.08)
            & (axial_span > max(1e-5, mesh.extents[axis] * 1e-5))
        )
        for faces in _groups(mesh, candidates):
            if len(faces) < 12:
                continue
            vertices = np.unique(mesh.vertices[mesh.faces[faces]].reshape(-1, 3), axis=0)
            points = np.delete(vertices, axis, axis=1)
            points = np.unique(np.round(points, decimals=7), axis=0)
            if len(points) < 8:
                continue
            # Линейная МНК-аппроксимация окружности: x²+y² = 2cx*x+2cy*y+k.
            matrix = np.column_stack((2 * points, np.ones(len(points))))
            if np.linalg.matrix_rank(matrix) != 3:
                continue
            cx, cy, offset = np.linalg.lstsq(matrix, np.sum(points * points, axis=1), rcond=None)[0]
            radius_sq = offset + cx * cx + cy * cy
            if radius_sq <= 0:
                continue
            radius = float(np.sqrt(radius_sq))
            radii = np.linalg.norm(points - (cx, cy), axis=1)
            if np.max(np.abs(radii - radius)) > max(0.05, 0.015 * radius):
                continue
            angles = np.sort(np.arctan2(points[:, 1] - cy, points[:, 0] - cx))
            gaps = np.diff(np.r_[angles, angles[0] + 2 * np.pi])
            if np.max(gaps) > np.pi / 3:
                continue
            centers = np.delete(mesh.triangles_center[faces], axis, axis=1)
            normals = np.delete(mesh.face_normals[faces], axis, axis=1)
            radial_dot = np.sum(normals * (centers - (cx, cy)), axis=1)
            # Внешняя стенка вала направлена наружу; стенка отверстия — внутрь.
            if np.mean(radial_dot < -0.7 * radius) < 0.9:
                continue
            depth = float(np.ptp(vertices[:, axis]))
            if depth <= 0:
                continue
            result.append(Hole(
                axis=AXES[axis], center=(float(cx), float(cy)),
                diameter=2 * radius, depth=depth,
            ))
    # Сначала ось Z, затем X/Y; внутри оси — положение центра.
    rank = {"z": 0, "x": 1, "y": 2}
    return sorted(result, key=lambda item: (rank[item.axis], item.center))


def find_chamfers(mesh: trimesh.Trimesh) -> list[Chamfer]:
    """Ищет 45° переходы между торцом и боковой поверхностью осевой детали."""
    result: list[Chamfer] = []
    normals = mesh.face_normals
    triangles = mesh.vertices[mesh.faces]
    for axis in range(3):
        axial = np.abs(normals[:, axis])
        span = np.ptp(triangles[:, :, axis], axis=1)
        candidates = np.flatnonzero(
            (axial > 0.62) & (axial < 0.79)
            & (span > max(1e-5, mesh.extents[axis] * 1e-5))
        )
        groups = _groups(mesh, candidates)
        owners = {face: index for index, group in enumerate(groups) for face in group}
        neighbours_by_group: list[set[int]] = [set() for _ in groups]
        for first, second in mesh.face_adjacency:
            a, b = int(first), int(second)
            owner_a, owner_b = owners.get(a), owners.get(b)
            if owner_a is not None and owner_b is None:
                neighbours_by_group[owner_a].add(b)
            elif owner_b is not None and owner_a is None:
                neighbours_by_group[owner_b].add(a)
        for faces, neighbours in zip(groups, neighbours_by_group):
            neighbour_ids = np.array(list(neighbours), dtype=int)
            adjacent = np.abs(normals[neighbour_ids, axis])
            flat_span = np.ptp(triangles[neighbour_ids, :, axis], axis=1)
            cap = (adjacent > 0.95) & (flat_span < max(1e-5, mesh.extents[axis] * 1e-5))
            if not (np.any(cap) and np.any(adjacent < 0.15)):
                continue
            size = float(np.ptp(triangles[faces, :, axis]))
            if size <= 1e-5:
                continue
            position = float(np.mean(triangles[faces, :, axis]))
            result.append(Chamfer(axis=AXES[axis], position=position, size=size))
    # Несколько сторон одной фаски дают одинаковый размер; сохраняем один замер.
    unique: list[Chamfer] = []
    for chamfer in sorted(result, key=lambda item: (item.axis, item.position, item.size)):
        if not any(
            item.axis == chamfer.axis and abs(item.position - chamfer.position) < 0.05
            and abs(item.size - chamfer.size) < 0.05 for item in unique
        ):
            unique.append(chamfer)
    return unique


def analyze_geometry(mesh: trimesh.Trimesh) -> Geometry:
    return Geometry(bounds=measure_bounds(mesh), holes=find_holes(mesh), chamfers=find_chamfers(mesh))
