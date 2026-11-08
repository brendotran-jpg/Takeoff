"""Estimate workbook calculations.

    row qty    = item metric x factor          (live-linked to the takeoff)
               | manual qty                    (unlinked rows)
    rate       = labour + material + plant + subcontract   ($/unit)
    row total  = qty x (1 + waste%) x rate
    subtotal   = sum of row totals
    contingency= subtotal x contingency%
    margin     = (subtotal + contingency) x margin%
    total ex   = subtotal + contingency + margin
    GST        = total ex x GST%   (10% in Australia - editable)

The Excel export rebuilds exactly this with formulas, so the workbook stays live.
"""
from __future__ import annotations

from .quantities import METRIC_UNITS

RATE_PARTS = ("labour", "material", "plant", "subcontract")


def row_quantity(row: dict, item_q: dict[int, dict]) -> tuple[float, str | None, str | None]:
    """-> (qty, unit, issue)"""
    if row["item_id"] is not None:
        q = item_q.get(row["item_id"])
        if q is None:
            return 0.0, row.get("unit"), "linked item missing"
        metric = row["item_metric"] or q["primary_metric"]
        if metric not in q["totals"] and metric != q["primary_metric"]:
            return 0.0, METRIC_UNITS.get(metric), f"item has no '{metric}' quantity"
        val = q["totals"].get(metric, 0.0)
        return val * (row["factor"] or 0), row.get("unit") or METRIC_UNITS.get(metric), None
    return float(row["manual_qty"] or 0), row.get("unit"), None


def build(sections: list[dict], rows: list[dict], items: dict[int, dict], item_q: dict[int, dict],
          meta: dict) -> dict:
    out_sections, subtotal = [], 0.0
    by_sec: dict[int, list] = {}
    for r in rows:
        by_sec.setdefault(r["section_id"], []).append(r)
    for sec in sections:
        srows, stotal = [], 0.0
        for r in by_sec.get(sec["id"], []):
            qty, unit, issue = row_quantity(r, item_q)
            rate = sum(float(r[k] or 0) for k in RATE_PARTS)
            total = qty * (1 + float(r["waste_pct"] or 0) / 100) * rate
            stotal += total
            it = items.get(r["item_id"]) if r["item_id"] else None
            srows.append({**r, "qty": qty, "unit": unit, "rate": rate, "total": total, "issue": issue,
                          "item_name": it["name"] if it else None,
                          "item_code": it["code"] if it else None})
        subtotal += stotal
        out_sections.append({**sec, "rows": srows, "subtotal": stotal})
    pct = lambda k: float(meta.get(k) or 0) / 100  # noqa: E731
    contingency = subtotal * pct("contingency_pct")
    margin = (subtotal + contingency) * pct("margin_pct")
    ex = subtotal + contingency + margin
    gst = ex * pct("gst_pct")
    return {"sections": out_sections, "summary": {
        "subtotal": subtotal, "contingency": contingency, "margin": margin,
        "total_ex_gst": ex, "gst": gst, "total_inc_gst": ex + gst,
        "contingency_pct": float(meta.get("contingency_pct") or 0),
        "margin_pct": float(meta.get("margin_pct") or 0),
        "gst_pct": float(meta.get("gst_pct") or 0),
    }}
