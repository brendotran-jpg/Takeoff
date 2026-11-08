"""Quantity engine: shapes -> metrics -> item totals.

Quantities are never stored; they are always derived from the stored geometry
and the page's current scale, so they can't drift out of date. Each shape can
yield several metrics (an area yields area + perimeter + volume), and the
item's rule picks which one is the *primary* quantity. That mirrors how
estimators link a single dimension group to several bill items (e.g. a slab
area drives concrete m3, mesh m2 and edge-form m).
"""
from __future__ import annotations

import math

from . import geometry as g

METRIC_KEYS = ("count", "length", "area", "perimeter", "face_area", "volume", "slope_area")
METRIC_UNITS = {"count": "no.", "length": "m", "area": "m2", "perimeter": "m",
                "face_area": "m2", "volume": "m3", "slope_area": "m2"}


def effective_inputs(item: dict, shape: dict | None = None) -> dict:
    eff = {k: v for k, v in (item.get("inputs") or {}).items() if v is not None}
    if shape:
        eff.update({k: v for k, v in (shape.get("inputs") or {}).items() if v is not None})
    return eff


def shape_metrics(kind: str, points, holes, mm_per_pt: float | None, inputs: dict) -> dict:
    """Unsigned metrics for one shape. Raises ValueError for bad geometry or a missing scale."""
    if kind == "count":
        return {"count": float(len(points))}
    if mm_per_pt is None:
        raise ValueError("page scale not set")
    m = mm_per_pt / 1000.0  # metres per pt
    if kind == "linear":
        length = g.polyline_length(points) * m
        out = {"length": length}
        if inputs.get("height_m"):
            out["face_area"] = length * inputs["height_m"]
        return out
    if kind == "area":
        if g.polygon_self_intersects(points):
            raise ValueError("outline crosses itself")
        area = g.polygon_area(points) * m * m
        for h in holes or []:
            area -= g.polygon_area(h) * m * m
        out = {"area": area, "perimeter": g.polygon_perimeter(points) * m}
        if inputs.get("depth_m"):
            out["volume"] = area * inputs["depth_m"]
        if inputs.get("pitch_deg") is not None:
            out["slope_area"] = area / math.cos(math.radians(inputs["pitch_deg"]))
        return out
    raise ValueError(f"unknown kind {kind}")


def primary_metric(kind: str, unit: str, required_inputs: list[str]) -> str:
    """Which metric is the item's main quantity, given its rule."""
    if unit == "no.":
        return "count"
    if kind == "linear":
        return "face_area" if unit == "m2" else "length"
    if kind == "area":
        if unit == "m3":
            return "volume"
        if unit == "m":
            return "perimeter"
        return "slope_area" if "pitch_deg" in required_inputs else "area"
    return "count"


def item_quantities(item: dict, shapes: list[dict], scales: dict[tuple[int, int], float | None]) -> dict:
    """Sum signed metrics over an item's shapes.

    scales: {(drawing_id, page): mm_per_pt or None}
    Returns totals per metric, the primary quantity, and any issues found.
    """
    rule = item["rule_snapshot"]
    req = rule.get("required_inputs", [])
    primary = primary_metric(item["kind"], item["unit"], req)
    totals = {k: 0.0 for k in METRIC_KEYS}
    issues, per_shape = [], {}
    for s in shapes:
        inputs = effective_inputs(item, s)
        try:
            met = shape_metrics(item["kind"], s["points"], s.get("holes"),
                                scales.get((s["drawing_id"], s["page"])), inputs)
        except ValueError as e:
            issues.append(f"shape {s['id']} (p{s['page'] + 1}): {e}")
            continue
        if primary not in met:
            missing = [k for k in req if k not in inputs]
            issues.append(f"shape {s['id']}: needs {', '.join(missing) or primary}")
        signed = {k: v * s["sign"] for k, v in met.items()}
        per_shape[s["id"]] = signed
        for k, v in signed.items():
            totals[k] += v
    return {
        "primary_metric": primary,
        "quantity": totals[primary],
        "unit": METRIC_UNITS[primary],
        "totals": {k: v for k, v in totals.items() if v or k == primary},
        "shape_count": len(shapes),
        "per_shape": per_shape,
        "issues": issues,
    }
