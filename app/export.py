"""CSV / Excel export.

The workbook is a live, traceable chain:

    Dimensions (one row per shape, signed metrics)
        -> Items      (SUMIFS over Dimensions)
            -> Estimate (references Items x factor, rate build-up, margins, GST)

so a reviewer can follow any dollar figure back to the shapes measured, the
scale used, and the rule (with citation) the item was measured under.
"""
from __future__ import annotations

import csv
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

from .estimate import RATE_PARTS
from .quantities import METRIC_KEYS, METRIC_UNITS
from .rules import citation

HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
SEC_FILL = PatternFill("solid", fgColor="DDEBF7")
WARN_FILL = PatternFill("solid", fgColor="FCE4D6")
BOLD = Font(bold=True)
TOP = Border(top=Side(style="thin"))
QFMT = "#,##0.000"
MONEY = '"$"#,##0.00'

METRIC_LABELS = {"count": "Count (no.)", "length": "Length (m)", "area": "Area (m2)",
                 "perimeter": "Perimeter (m)", "face_area": "Face area (m2)",
                 "volume": "Volume (m3)", "slope_area": "Slope area (m2)"}


def _header(ws, headers, widths=None):
    ws.append(headers)
    for c in ws[1]:
        c.font, c.fill = HEAD, HEAD_FILL
        c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    for i, w in enumerate(widths or [], 1):
        ws.column_dimensions[L(i)].width = w


def _ratio(page: dict | None) -> str:
    if not page or not page.get("mm_per_pt"):
        return "not set"
    return f"1:{(page.get('scale_detail') or {}).get('effective_ratio', round(page['mm_per_pt'] / (25.4 / 72), 2))}"


def item_rows_for_csv(items, item_q):
    for it in items:
        q = item_q[it["id"]]
        rule = it["rule_snapshot"]
        yield {
            "code": it["code"] or "", "item": it["name"], "category": it["category"], "kind": it["kind"],
            "quantity": round(q["quantity"], 4), "unit": q["unit"],
            **{METRIC_LABELS[k]: round(q["totals"].get(k, 0), 4) for k in METRIC_KEYS},
            "shapes": q["shape_count"], "rule_id": it["rule_id"],
            "rule_version": f"v{rule.get('version', 1)}/{it['rule_hash']}",
            "citation": citation(rule), "verification": rule["verification"]["status"],
            "issues": "; ".join(q["issues"]),
        }


def to_csv(items, item_q) -> bytes:
    rows = list(item_rows_for_csv(items, item_q))
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def to_xlsx(*, meta, items, item_q, shapes, pages, drawings, est, rules_used, audit) -> bytes:
    wb = Workbook()

    # ---------------------------------------------------------- Read me --
    ws = wb.active
    ws.title = "Read me"
    unverified = sum(1 for it in items if it["rule_snapshot"]["verification"]["status"] != "user_verified")
    issues = sum(len(item_q[it["id"]]["issues"]) for it in items)
    for line in [
        meta.get("name", "Takeoff"), f"Client: {meta.get('client') or '-'}", "",
        "How this workbook is linked:",
        "  Dimensions: one row per measured shape (signed: deductions are negative, cut-outs already netted).",
        "  Items: SUMIFS over Dimensions. 'Quantity' is the metric the item's rule measures.",
        "  Estimate: quantities reference Items x factor; rate = labour + material + plant + subcontract;",
        "            total = qty x (1 + waste%) x rate; then contingency, margin and GST.",
        "",
        "Quantities are NET as measured; waste is applied only in the Estimate.",
        f"Items whose rule citation is UNVERIFIED: {unverified} of {len(items)}. Verify against your licensed",
        "copy of the standard / NCC before relying on this document.",
        f"Measurement issues flagged (missing scale, missing height/depth, bad geometry): {issues}.",
    ]:
        ws.append([line])
    ws["A1"].font = Font(bold=True, size=14)
    ws.column_dimensions["A"].width = 110

    # -------------------------------------------------------- Dimensions --
    wd = wb.create_sheet("Dimensions")
    dcols = ["Shape ID", "Item ID", "Item", "Drawing", "Sheet", "Page", "Scale", "Scale method",
             "Deduction", "Cut-outs", "Height (m)", "Depth (m)", "Pitch (deg)"] + \
            [METRIC_LABELS[k] for k in METRIC_KEYS] + ["Issue"]
    _header(wd, dcols, [9, 8, 28, 22, 14, 6, 9, 11, 9, 8, 9, 9, 9] + [12] * len(METRIC_KEYS) + [40])
    items_by_id = {it["id"]: it for it in items}
    first_metric_col = dcols.index(METRIC_LABELS[METRIC_KEYS[0]]) + 1
    for s in shapes:
        it = items_by_id[s["item_id"]]
        q = item_q[it["id"]]
        pg = pages.get((s["drawing_id"], s["page"]))
        met = q["per_shape"].get(s["id"], {})
        inp = {**(it["inputs"] or {}), **(s["inputs"] or {})}
        issue = next((x for x in q["issues"] if x.startswith(f"shape {s['id']}")), "")
        wd.append([s["id"], it["id"], it["name"], drawings[s["drawing_id"]]["filename"],
                   (pg or {}).get("label"), s["page"] + 1, _ratio(pg), (pg or {}).get("scale_method"),
                   "yes" if s["sign"] < 0 else "", len(s.get("holes") or []) or "",
                   inp.get("height_m"), inp.get("depth_m"), inp.get("pitch_deg")] +
                  [met.get(k) for k in METRIC_KEYS] + [issue])
        r = wd.max_row
        for j in range(len(METRIC_KEYS)):
            wd.cell(row=r, column=first_metric_col + j).number_format = QFMT
        if issue:
            wd.cell(row=r, column=len(dcols)).fill = WARN_FILL
    dlast = max(wd.max_row, 2)
    wd.auto_filter.ref = wd.dimensions

    # ------------------------------------------------------------- Items --
    wi = wb.create_sheet("Items")
    icols = ["Item ID", "Code", "Item", "Category", "Measure type", "Quantity", "Unit"] + \
            [METRIC_LABELS[k] for k in METRIC_KEYS] + \
            ["Shapes", "Rule ID", "Rule version/hash", "Measurement convention (paraphrase)",
             "Source citation", "Verification", "Issues"]
    _header(wi, icols, [8, 9, 30, 14, 10, 13, 6] + [12] * len(METRIC_KEYS) + [7, 16, 18, 60, 60, 20, 40])
    item_row: dict[int, int] = {}
    metric_col = {k: L(8 + j) for j, k in enumerate(METRIC_KEYS)}
    did_col = L(dcols.index("Item ID") + 1)
    for it in items:
        q, rule = item_q[it["id"]], it["rule_snapshot"]
        n = wi.max_row + 1
        item_row[it["id"]] = n
        sumifs = [f"=SUMIFS(Dimensions!${L(first_metric_col + j)}$2:${L(first_metric_col + j)}${dlast},"
                  f"Dimensions!${did_col}$2:${did_col}${dlast},$A{n})" for j in range(len(METRIC_KEYS))]
        wi.append([it["id"], it["code"], it["name"], it["category"], it["kind"],
                   f"={metric_col[q['primary_metric']]}{n}", q["unit"]] + sumifs +
                  [f'=COUNTIF(Dimensions!${did_col}$2:${did_col}${dlast},$A{n})', it["rule_id"],
                   f"v{rule.get('version', 1)} / {it['rule_hash']}", rule["convention"], citation(rule),
                   rule["verification"]["status"], "; ".join(q["issues"])])
        wi[f"F{n}"].font = BOLD
        for c in ["F"] + list(metric_col.values()):
            wi[f"{c}{n}"].number_format = QFMT
        if rule["verification"]["status"] != "user_verified":
            wi.cell(row=n, column=icols.index("Source citation") + 1).fill = WARN_FILL
        if q["issues"]:
            wi.cell(row=n, column=len(icols)).fill = WARN_FILL
    wi.auto_filter.ref = wi.dimensions

    # ---------------------------------------------------------- Estimate --
    we = wb.create_sheet("Estimate")
    ecols = ["Code", "Description", "Linked item", "Metric", "Factor", "Quantity", "Unit", "Waste %",
             "Labour $/u", "Material $/u", "Plant $/u", "Subcontract $/u", "Rate $/u", "Total $", "Notes"]
    _header(we, ecols, [9, 40, 26, 12, 7, 12, 6, 8, 11, 11, 11, 13, 11, 14, 30])
    subtotal_cells = []
    for sec in est["sections"]:
        we.append([None, sec["name"]])
        hr = we.max_row
        for c in we[hr]:
            c.fill, c.font = SEC_FILL, BOLD
        first = hr + 1
        for r in sec["rows"]:
            n = we.max_row + 1
            if r["item_id"] and r["item_id"] in item_row:
                metric = r["item_metric"] or item_q[r["item_id"]]["primary_metric"]
                qty = f"=Items!{metric_col[metric]}{item_row[r['item_id']]}*E{n}"
                linked = f"{r['item_code'] or ''} {r['item_name']}".strip()
            else:
                metric, qty, linked = None, r["qty"], None
            we.append([r["code"], r["description"], linked, metric, r["factor"] if r["item_id"] else None,
                       qty, r["unit"], r["waste_pct"]] + [r[k] for k in RATE_PARTS] +
                      [f"=SUM(I{n}:L{n})", f"=F{n}*(1+H{n}/100)*M{n}", r["notes"]])
            we[f"F{n}"].number_format = QFMT
            for c in "IJKLMN":
                we[f"{c}{n}"].number_format = MONEY
        last = we.max_row
        we.append([None, f"Subtotal - {sec['name']}"] + [None] * 11 +
                  [f"=SUM(N{first}:N{last})" if last >= first else 0])
        sr = we.max_row
        we[f"B{sr}"].font = we[f"N{sr}"].font = BOLD
        we[f"N{sr}"].number_format = MONEY
        we[f"N{sr}"].border = TOP
        subtotal_cells.append(f"N{sr}")
    we.append([])
    sm = est["summary"]

    def line(label, pct, formula):
        we.append([None, label] + [None] * 10 + [pct, formula])
        n = we.max_row
        we[f"B{n}"].font = we[f"N{n}"].font = BOLD
        we[f"N{n}"].number_format = MONEY
        if pct is not None:
            we[f"M{n}"].number_format = '0.00"%"'
        return n

    s = line("SUBTOTAL (all sections)", None, "=" + ("+".join(subtotal_cells) if subtotal_cells else "0"))
    c = line("Contingency", sm["contingency_pct"], f"=N{s}*M{s + 1}/100")
    m = line("Margin", sm["margin_pct"], f"=(N{s}+N{c})*M{c + 1}/100")
    ex = line("TOTAL excl. GST", None, f"=N{s}+N{c}+N{m}")
    g = line("GST", sm["gst_pct"], f"=N{ex}*M{ex + 1}/100")
    line("TOTAL incl. GST", None, f"=N{ex}+N{g}")

    # ------------------------------------------------------- Rules cited --
    wr = wb.create_sheet("Rules cited")
    _header(wr, ["Rule ID", "Version/hash", "Title", "Measure type", "Unit", "Convention",
                 "Source document", "Publisher", "Edition", "Clause", "Clause verified",
                 "Section hint", "Status", "Verified by", "Verified on", "URL", "Related standards"],
            [16, 18, 30, 10, 6, 60, 40, 22, 22, 16, 10, 22, 20, 14, 12, 26, 60])
    for rule in rules_used:
        src, v = rule["source"], rule["verification"]
        related = "; ".join(f"{x['document']} - {x['relevance']}" for x in rule.get("related_standards", []))
        wr.append([rule["id"], f"v{rule.get('version', 1)} / {rule['_hash']}", rule["title"],
                   rule["measure_type"], rule["unit"], rule["convention"], src["document"],
                   src.get("publisher"), src.get("edition"), src.get("clause") or "TBC - not verified",
                   "yes" if src.get("clause_verified") else "NO", src.get("section_hint"),
                   v["status"], v.get("verified_by"), v.get("verified_on"), src.get("url"), related])

    # --------------------------------------------------------- Audit log --
    wa = wb.create_sheet("Audit log")
    _header(wa, ["#", "Timestamp (UTC)", "Action", "Detail"], [6, 22, 22, 120])
    for a in audit:
        wa.append([a["id"], a["ts"], a["action"], str(a["detail"])[:2000]])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
