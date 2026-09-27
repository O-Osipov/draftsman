"""Геометрические проверки сложных мест этапов 8–10."""

import unittest

import trimesh

from backend.comparison import compare_dimensions
from backend.geometry import analyze_geometry
from backend.models import Dimension, Report
from backend.reporting import format_report


class GeometryComparisonTests(unittest.TestCase):
    def test_shaft_outer_wall_is_not_a_hole(self):
        mesh = trimesh.creation.cylinder(radius=10, height=80, sections=32)
        geometry = analyze_geometry(mesh)
        self.assertEqual(geometry.holes, [])
        report = compare_dimensions(7, [
            Dimension(name="габарит_длина", value=80, type="LINEAR"),
            Dimension(name="габарит_диаметр", value=20, type="LINEAR"),
            Dimension(name="отверстие_1_диаметр", value=5, type="DIAMETER"),
        ], geometry)
        self.assertEqual(len(report.matches), 2)
        self.assertIsNone(report.mismatches[0].actual)
        self.assertIsNone(report.mismatches[0].delta)

    def test_chamfered_shaft_and_tolerance(self):
        mesh = trimesh.creation.revolve(
            [(0, 0), (10, 0), (10, 18), (8, 20), (0, 20)], sections=32
        )
        geometry = analyze_geometry(mesh)
        self.assertEqual(geometry.holes, [])
        self.assertEqual(len(geometry.chamfers), 1)
        self.assertAlmostEqual(geometry.chamfers[0].size, 2)
        report = compare_dimensions(7, [
            Dimension(name="фаска_1", value=2.5, type="CHAMFER"),
            Dimension(name="фаска_2", value=2, type="CHAMFER"),
            Dimension(name="габарит_длина", value=20.6, type="LINEAR"),
            Dimension(name="габарит_диаметр", value=20, type="LINEAR"),
        ], geometry)
        self.assertEqual(len(report.matches), 2)  # 2.5 отличается ровно на допуск 0.5.
        self.assertEqual(len(report.mismatches), 2)
        self.assertIsNone(report.mismatches[0].actual)
        self.assertAlmostEqual(report.mismatches[1].delta, -0.6)

    def test_telegram_report_respects_even_small_configured_limit(self):
        report = Report(session_id=7, summary="0 из 0 размеров совпали.")
        self.assertLessEqual(len(format_report(report, 10)), 10)
        self.assertIn("Отчёт о проверке:", format_report(report, 4000))

    def test_two_chamfers_at_opposite_ends_are_distinct(self):
        mesh = trimesh.creation.revolve(
            [(0, 0), (8, 0), (10, 2), (10, 18), (8, 20), (0, 20)], sections=32
        )
        geometry = analyze_geometry(mesh)
        self.assertEqual([round(item.size, 3) for item in geometry.chamfers], [2, 2])


if __name__ == "__main__":
    unittest.main()
