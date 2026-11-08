"""Pure geometry + scale maths. No I/O, fully unit-tested.

Coordinate convention
---------------------
All measurement points are stored in *PDF points* (1 pt = 1/72 inch) in the
coordinate space of the page *as displayed* (i.e. after /Rotate is applied),
origin top-left. Storing in PDF space - not screen pixels - means a measurement
is independent of zoom level and render DPI, and can be re-checked later
against the original file.

Scale is stored as ``mm_per_pt``: real-world millimetres represented by one PDF
point on the sheet. For a drawing at 1:N printed at its true sheet size:

    mm_per_pt = (25.4 / 72) * N
"""
from __future__ import annotations

import math
import re
from typing import Iterable, Sequence

PT_TO_MM = 25.4 / 72.0  # paper millimetres per PDF point

Point = Sequence[float]

# ISO 216 A-series sheet sizes, portrait (width, height) in mm.
ISO_A_SIZES = {
    "A0": (841, 1189),
    "A1": (594, 841),
    "A2": (420, 594),
    "A3": (297, 420),
    "A4": (210, 297),
}


# ---------------------------------------------------------------- scale ----

def mm_per_pt_from_ratio(denominator: float) -> float:
    """1:denominator drawing printed at true sheet size."""
    if denominator <= 0:
        raise ValueError("scale denominator must be positive")
    return PT_TO_MM * denominator


def mm_per_pt_from_calibration(p1: Point, p2: Point, real_length_mm: float) -> float:
    """Calibrate from two picked points and a known real-world dimension."""
    d = distance(p1, p2)
    if d < 1.0:  # < 1 pt (~0.35 mm on paper) is too short to calibrate reliably
        raise ValueError("calibration points are too close together")
    if real_length_mm <= 0:
        raise ValueError("known length must be positive")
    return real_length_mm / d


def ratio_from_mm_per_pt(mm_per_pt: float) -> float:
    """Equivalent 1:N ratio (useful to sanity-check a calibration)."""
    return mm_per_pt / PT_TO_MM


_SCALE_RE = re.compile(
    r"(?<![\d.])1\s*:\s*(\d{1,5})(?:\s*(?:@|at)\s*(A[0-4]))?", re.IGNORECASE
)


def find_scale_statements(text: str) -> list[dict]:
    """Find '1:100', '1 : 50 @ A1', 'SCALE 1:200 AT A3' in sheet text.

    Returns unique candidates in order of appearance. These are *candidates
    only* - a sheet often carries several scales (plan + details), so the user
    must confirm which applies to the viewport being measured.
    """
    seen, out = set(), []
    for m in _SCALE_RE.finditer(text):
        denom = int(m.group(1))
        if denom < 1 or denom > 10000:
            continue
        sheet = m.group(2).upper() if m.group(2) else None
        key = (denom, sheet)
        if key in seen:
            continue
        seen.add(key)
        out.append({"ratio": denom, "stated_sheet": sheet, "match": m.group(0)})
    return out


def classify_sheet(width_pt: float, height_pt: float, tol_mm: float = 6.0) -> str | None:
    """Return ISO A size of the page, or None if non-standard."""
    w, h = sorted((width_pt * PT_TO_MM, height_pt * PT_TO_MM))
    for name, (sw, sh) in ISO_A_SIZES.items():
        if abs(w - sw) <= tol_mm and abs(h - sh) <= tol_mm:
            return name
    return None


def sheet_size_correction(stated_sheet: str | None, actual_sheet: str | None) -> float | None:
    """Factor to multiply mm_per_pt by when a sheet is printed at another size.

    e.g. '1:100 @ A1' issued as an A3 PDF -> the drawing is reduced by
    sqrt(2)^2 = 2x linearly, so each PDF point represents 2x more real length.
    Returns None when the sizes match or either is unknown.
    """
    if not stated_sheet or not actual_sheet or stated_sheet == actual_sheet:
        return None
    s = ISO_A_SIZES.get(stated_sheet)
    a = ISO_A_SIZES.get(actual_sheet)
    if not s or not a:
        return None
    return s[1] / a[1]


# ------------------------------------------------------------- geometry ----

def distance(p1: Point, p2: Point) -> float:
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def polyline_length(points: Sequence[Point]) -> float:
    return sum(distance(points[i], points[i + 1]) for i in range(len(points) - 1))


def polygon_area(points: Sequence[Point]) -> float:
    """Shoelace formula; absolute area, any winding. Polygon is auto-closed."""
    n = len(points)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def polygon_perimeter(points: Sequence[Point]) -> float:
    if len(points) < 2:
        return 0.0
    return polyline_length(list(points) + [points[0]])


def polygon_self_intersects(points: Sequence[Point]) -> bool:
    """Self-intersecting polygons give meaningless shoelace areas - reject them."""
    n = len(points)
    if n < 4:
        return False

    def orient(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)

    def cross(a, b, c, d):
        return orient(a, b, c) * orient(a, b, d) < 0 and orient(c, d, a) * orient(c, d, b) < 0

    edges = [(points[i], points[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue  # adjacent edges share a vertex
            if cross(*edges[i], *edges[j]):
                return True
    return False


# --------------------------------------------------------- quantities ------

def compute_quantity(kind: str, points: Sequence[Point], mm_per_pt: float | None,
                     unit: str | None = None, height_m: float | None = None,
                     depth_m: float | None = None, pitch_deg: float | None = None) -> dict:
    """Convert picked geometry into a real-world quantity in the rule's unit.

    linear            -> m
    linear + height_m -> m2  (e.g. wall face = centreline length x height)
    area              -> m2  (plan area; with pitch_deg -> true slope area)
    area + depth_m    -> m3  (e.g. slab = area x thickness)
    count             -> no.
    The returned dict always includes the base (plan) geometry so the derivation
    can be shown in the audit trail.
    """
    if kind == "count":
        if not points:
            raise ValueError("count needs at least 1 point")
        return {"quantity": float(len(points)), "unit": "no.", "derivation": f"{len(points)} counted"}
    if mm_per_pt is None:
        raise ValueError("page scale not set - set or calibrate the scale first")

    if kind == "linear":
        if len(points) < 2:
            raise ValueError("linear measurement needs at least 2 points")
        length_m = polyline_length(points) * mm_per_pt / 1000.0
        if unit == "m2":
            if not height_m or height_m <= 0:
                raise ValueError("this rule measures face area - enter a height (m)")
            return {"quantity": length_m * height_m, "unit": "m2", "length_m": length_m,
                    "derivation": f"{length_m:.3f} m x {height_m:.3f} m high"}
        return {"quantity": length_m, "unit": "m", "length_m": length_m,
                "derivation": f"{length_m:.3f} m"}

    if kind == "area":
        if len(points) < 3:
            raise ValueError("area measurement needs at least 3 points")
        if polygon_self_intersects(points):
            raise ValueError("area outline crosses itself - redraw the boundary")
        plan_m2 = polygon_area(points) * (mm_per_pt / 1000.0) ** 2
        perim_m = polygon_perimeter(points) * mm_per_pt / 1000.0
        out = {"plan_area_m2": plan_m2, "perimeter_m": perim_m}
        if unit == "m3":
            if not depth_m or depth_m <= 0:
                raise ValueError("this rule measures volume - enter a depth/thickness (m)")
            return {**out, "quantity": plan_m2 * depth_m, "unit": "m3",
                    "derivation": f"{plan_m2:.3f} m2 plan x {depth_m:.3f} m deep"}
        if pitch_deg is not None:
            if not 0 <= pitch_deg < 80:
                raise ValueError("pitch must be between 0 and 80 degrees")
            slope = plan_m2 / math.cos(math.radians(pitch_deg))
            return {**out, "quantity": slope, "unit": "m2",
                    "derivation": f"{plan_m2:.3f} m2 plan / cos({pitch_deg:g} deg)"}
        return {**out, "quantity": plan_m2, "unit": "m2", "derivation": f"{plan_m2:.3f} m2"}

    raise ValueError(f"unknown measurement kind: {kind}")


def nearest_point(target: Point, candidates: Iterable[Point], max_dist: float) -> Point | None:
    best, best_d = None, max_dist
    for c in candidates:
        d = distance(target, c)
        if d <= best_d:
            best, best_d = c, d
    return best


def point_in_polygon(pt: Point, poly: Sequence[Point]) -> bool:
    """Ray-casting test. Points exactly on an edge may go either way."""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def _segments_cross(a, b, c, d) -> bool:
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
    return orient(a, b, c) * orient(a, b, d) < 0 and orient(c, d, a) * orient(c, d, b) < 0


def polygon_inside(inner: Sequence[Point], outer: Sequence[Point]) -> bool:
    """True when `inner` lies wholly within `outer`: every vertex inside and no
    edge of one crosses an edge of the other (handles concave outers)."""
    if not all(point_in_polygon(p, outer) for p in inner):
        return False
    n, m = len(inner), len(outer)
    for i in range(n):
        a, b = inner[i], inner[(i + 1) % n]
        for j in range(m):
            if _segments_cross(a, b, outer[j], outer[(j + 1) % m]):
                return False
    return True


def centroid(points: Sequence[Point]) -> tuple[float, float]:
    n = len(points)
    return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)
