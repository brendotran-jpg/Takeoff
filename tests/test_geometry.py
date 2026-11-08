import math

import pytest

from app import geometry as g


def test_ratio_scale():
    # 1:100 -> 1 pt on paper (0.3528 mm) is 35.28 mm real
    assert g.mm_per_pt_from_ratio(100) == pytest.approx(35.2778, rel=1e-4)


def test_calibration_roundtrip():
    mm = g.mm_per_pt_from_calibration((0, 0), (340.157, 0), 12000)
    assert g.ratio_from_mm_per_pt(mm) == pytest.approx(100, rel=1e-4)
    with pytest.raises(ValueError):
        g.mm_per_pt_from_calibration((0, 0), (0.1, 0), 1000)


def test_find_scale_statements():
    text = "PLAN SCALE 1:100 @ A1\nDETAIL 1 : 5\nSECTION 1:100@A1\nREV 11:30"
    c = g.find_scale_statements(text)
    # duplicates collapse; '11:30' (a time) is not read as 1:30
    assert [(x["ratio"], x["stated_sheet"]) for x in c] == [(100, "A1"), (5, None)]


def test_scale_regex_ignores_times_inside_numbers():
    assert g.find_scale_statements("drawn 21:30") == []


def test_sheet_classification_and_correction():
    a3 = (420 * 72 / 25.4, 297 * 72 / 25.4)
    assert g.classify_sheet(*a3) == "A3"
    assert g.sheet_size_correction("A1", "A3") == pytest.approx(2.0, rel=0.01)
    assert g.sheet_size_correction("A3", "A3") is None


def test_polygon_area_and_self_intersection():
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert g.polygon_area(sq) == 100
    assert g.polygon_area(list(reversed(sq))) == 100
    assert g.polygon_perimeter(sq) == 40
    bowtie = [(0, 0), (10, 10), (10, 0), (0, 10)]
    assert g.polygon_self_intersects(bowtie)
    assert not g.polygon_self_intersects(sq)


def test_quantities_in_rule_units():
    k = 1000.0  # 1 pt = 1 m, keeps arithmetic obvious
    sq = [(0, 0), (12, 0), (12, 8), (0, 8)]
    assert g.compute_quantity("area", sq, k)["quantity"] == pytest.approx(96)
    assert g.compute_quantity("area", sq, k, unit="m3", depth_m=0.1)["quantity"] == pytest.approx(9.6)
    slope = g.compute_quantity("area", sq, k, unit="m2", pitch_deg=22.5)["quantity"]
    assert slope == pytest.approx(96 / math.cos(math.radians(22.5)))
    wall = g.compute_quantity("linear", [(0, 0), (12, 0)], k, unit="m2", height_m=2.7)
    assert wall["quantity"] == pytest.approx(32.4) and wall["unit"] == "m2"
    assert g.compute_quantity("count", [(1, 1), (2, 2)], None)["quantity"] == 2
    with pytest.raises(ValueError, match="scale not set"):
        g.compute_quantity("linear", [(0, 0), (1, 0)], None)
    with pytest.raises(ValueError, match="height"):
        g.compute_quantity("linear", [(0, 0), (1, 0)], k, unit="m2")


def test_polygon_inside_handles_concave_outer():
    # L-shaped outer; a hole spanning the notch has all vertices inside but crosses edges
    L = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]
    assert g.polygon_inside([(1, 1), (3, 1), (3, 3), (1, 3)], L)
    assert not g.polygon_inside([(3, 3), (9, 3), (9, 3.5), (3.5, 9), (3, 9)], L)
    assert not g.polygon_inside([(20, 20), (21, 20), (21, 21)], L)
