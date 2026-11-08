"""Create test material: sample drawings + a ready-made demo project.

    python scripts/make_demo_project.py [out_dir]      (default: samples/)

Writes
  sample_drawings.pdf   3 sheets: A3 plan @1:100, reduced print "1:50 @ A1", simulated scan
  sample_revB.pdf       revision B of sheet 1 (internal wall moved 1 m east)
  Sample House.qto      project with scales, takeoff items, cut-outs, deductions and a priced estimate
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["TAKEOFF_NO_DEFAULT_APP"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402

MM = 72 / 25.4
S = MM / 100              # points per real mm at 1:100
OX, OY = 60 * MM, 50 * MM  # plan origin on the sheet


def P(x_mm, y_mm):
    return [OX + x_mm * S, OY + y_mm * S]


def rect(x, y, w, h):
    return [P(x, y), P(x + w, y), P(x + w, y + h), P(x, y + h)]


def main(out="samples"):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    gen = ROOT / "scripts" / "make_sample_pdf.py"
    subprocess.run([sys.executable, str(gen), str(out / "sample_drawings.pdf")], check=True)
    subprocess.run([sys.executable, str(gen), str(out / "sample_revB.pdf"), "--rev-b"], check=True)

    qto = out / "Sample House.qto"
    qto.unlink(missing_ok=True)
    c = TestClient(create_app(qto, fs_root=out, user_rules_dir=out / ".rules"))

    def ok(r):
        assert r.status_code < 300, r.text
        return r.json() if r.content else None

    ok(c.patch("/api/project/meta", json={"name": "Sample House", "client": "Demo client",
                                           "contingency_pct": 5, "margin_pct": 8}))
    d = ok(c.post("/api/drawings", files={"file": ("sample_drawings.pdf",
                                                    (out / "sample_drawings.pdf").read_bytes(), "application/pdf")}))
    did = d["id"]
    ok(c.patch(f"/api/drawings/{did}/pages/0", json={"label": "A-101", "title": "Ground floor plan", "revision": "A"}))
    ok(c.patch(f"/api/drawings/{did}/pages/1", json={"label": "A-101 (A1 reduced)", "title": "Reduced print test"}))
    ok(c.patch(f"/api/drawings/{did}/pages/2", json={"label": "A-101 (scan)", "title": "Scanned copy test"}))
    ok(c.put(f"/api/drawings/{did}/pages/0/scale", json={"method": "stated", "ratio": 100, "stated_sheet": "A3"}))

    def item(rule, name, code, **inputs):
        return ok(c.post("/api/items", json={"rule_id": rule, "name": name, "code": code, "inputs": inputs}))["id"]

    def shape(iid, pts, **kw):
        ok(c.post("/api/shapes", json={"item_id": iid, "drawing_id": did, "page": 0, "points": pts, **kw}))

    slab = item("CONC-SLAB-001", "GF slab 100 thk N25", "02.010", depth_m=0.1)
    shape(slab, rect(0, 0, 12000, 8000), holes=[rect(9000, 5000, 600, 600)])   # 0.36 m2 service void

    edge = item("FORM-EDGE-001", "Slab edge form, 100 high", "02.020")
    shape(edge, [P(0, 0), P(12000, 0), P(12000, 8000), P(0, 8000), P(0, 0)])

    wall = item("MAS-WALL-001", "Brick veneer external walls", "04.010", height_m=2.7)
    shape(wall, [P(0, 0), P(12000, 0), P(12000, 8000), P(0, 8000), P(0, 0)])
    for x in (1000, 3500, 6500, 9500):                                          # 4 windows 1200 x 1200
        shape(wall, [P(x, 0), P(x + 1200, 0)], deduction=True, inputs={"height_m": 1.2})

    ceil = item("FIN-PLB-CEIL-001", "Plasterboard ceiling 10 mm", "09.010")
    shape(ceil, rect(230, 230, 4770, 7540))
    shape(ceil, rect(5090, 230, 6680, 7540))

    sk = item("FIN-SKIRT-001", "Skirting 66 x 18 MDF", "09.020")
    shape(sk, [P(230, 230), P(5000, 230), P(5000, 7770), P(230, 7770), P(230, 230)])

    doors = item("WD-DOOR-001", "D1 820 x 2040 hinged door", "08.010")
    shape(doors, [P(1500, 8000)])
    shape(doors, [P(7000, 8000)])

    roof = item("ROOF-SHEET-001", "Metal roof sheeting 0.42 BMT", "06.010", pitch_deg=22.5)
    shape(roof, rect(-450, -450, 12900, 8900))                                   # incl. 450 eaves

    ok(c.post("/api/estimate/from-items"))
    rates = {"02.010": dict(material=265, labour=55, waste_pct=5), "02.020": dict(labour=28, material=6),
             "04.010": dict(subcontract=118, waste_pct=5), "09.010": dict(labour=24, material=16),
             "09.020": dict(labour=9, material=7, waste_pct=10), "08.010": dict(labour=150, material=380),
             "06.010": dict(subcontract=62, waste_pct=5)}
    est = ok(c.get("/api/estimate"))
    for sec in est["sections"]:
        for r in sec["rows"]:
            if r["code"] in rates:
                ok(c.patch(f"/api/estimate/rows/{r['id']}", json=rates[r["code"]]))
    conc = next(s["id"] for s in est["sections"] if s["name"] == "Concrete")
    ok(c.post("/api/estimate/rows", json={"section_id": conc, "code": "02.030", "description": "SL82 mesh (from slab area)",
                                          "item_id": slab, "item_metric": "area", "factor": 1.0, "material": 9.5,
                                          "labour": 3, "waste_pct": 10}))
    ok(c.post("/api/estimate/rows", json={"section_id": conc, "code": "02.040", "description": "Concrete pump hire",
                                          "manual_qty": 1, "unit": "item", "plant": 1450}))
    s = ok(c.get("/api/estimate"))["summary"]
    c.app.state.project.close()
    print(f"wrote {qto}  (estimate total incl. GST ${s['total_inc_gst']:,.2f})")


if __name__ == "__main__":
    main(*sys.argv[1:])
