import shutil
import subprocess
import sys
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

ROOT = Path(__file__).resolve().parent.parent
MM = 72 / 25.4


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory):
    out = tmp_path_factory.mktemp("pdf") / "sample.pdf"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_sample_pdf.py"), str(out)], check=True)
    return out


def corners(ratio=100, ox=60 * MM, oy=50 * MM):
    s = MM / ratio
    return [(ox, oy), (ox + 12000 * s, oy), (ox + 12000 * s, oy + 8000 * s), (ox, oy + 8000 * s)]


def rect(x0, y0, w_mm, h_mm, ratio=100):
    s = MM / ratio
    return [(x0, y0), (x0 + w_mm * s, y0), (x0 + w_mm * s, y0 + h_mm * s), (x0, y0 + h_mm * s)]


@pytest.fixture
def client(tmp_path, sample_pdf):
    rules = tmp_path / "rules"
    shutil.copytree(ROOT / "rules", rules)
    app = create_app(tmp_path / "p.qto", rules_dir=rules, user_rules_dir=tmp_path / "urules", fs_root=tmp_path)
    c = TestClient(app)
    r = c.post("/api/drawings", files={"file": ("sample.pdf", sample_pdf.read_bytes(), "application/pdf")})
    assert r.status_code == 200, r.text
    c.did = r.json()["id"]
    c.tmp = tmp_path
    c.put(f"/api/drawings/{c.did}/pages/0/scale", json={"method": "stated", "ratio": 100})
    return c


def item(c, rule_id, name, **kw):
    r = c.post("/api/items", json={"rule_id": rule_id, "name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def shape(c, iid, points, page=0, expect=201, **kw):
    r = c.post("/api/shapes", json={"item_id": iid, "drawing_id": c.did, "page": page, "points": points, **kw})
    assert r.status_code == expect, r.text
    return r.json()


def q(c, iid):
    return next(i for i in c.get("/api/items").json() if i["id"] == iid)["q"]


def test_page_analysis_and_labels(client):
    p2 = client.get(f"/api/drawings/{client.did}/pages/1").json()
    assert p2["scale_candidates"][0]["stated_sheet"] == "A1" and p2["scale_candidates"][0]["warning"]
    assert client.get(f"/api/drawings/{client.did}/pages/2").json()["is_scanned"]
    r = client.patch(f"/api/drawings/{client.did}/pages/0", json={"label": "A-101", "revision": "B"}).json()
    assert r["label"] == "A-101" and r["revision"] == "B"


def test_item_with_cutouts_and_deductions(client):
    slab = item(client, "CONC-SLAB-001", "GF slab", inputs={"depth_m": 0.1, "height_m": 3})
    assert slab["inputs"] == {"depth_m": 0.1} and slab["kind"] == "area" and slab["unit"] == "m3"
    c = corners()
    hole = rect(c[0][0] + 50, c[0][1] + 50, 2000, 1000)          # 2 m2 void
    s = shape(client, slab["id"], c, holes=[hole])
    assert s["holes"]
    qq = q(client, slab["id"])
    assert qq["totals"]["area"] == pytest.approx(94.0, rel=1e-6)
    assert qq["quantity"] == pytest.approx(9.4) and qq["unit"] == "m3"
    assert qq["totals"]["perimeter"] == pytest.approx(40.0)
    # a separate deduction shape
    shape(client, slab["id"], rect(c[0][0] + 200, c[0][1] + 100, 1000, 1000), deduction=True)
    assert q(client, slab["id"])["totals"]["area"] == pytest.approx(93.0)
    # hole outside the outline is rejected
    shape(client, slab["id"], c, holes=[rect(10, 10, 1000, 1000)], expect=422)


def test_per_shape_height_override(client):
    wall = item(client, "MAS-WALL-001", "Brick walls", inputs={"height_m": 2.7})
    c = corners()
    shape(client, wall["id"], c[:2])                                   # 12 m x 2.7
    shape(client, wall["id"], c[1:3], inputs={"height_m": 3.0})        # 8 m x 3.0
    qq = q(client, wall["id"])
    assert qq["totals"]["length"] == pytest.approx(20.0)
    assert qq["quantity"] == pytest.approx(12 * 2.7 + 8 * 3.0)


def test_missing_input_is_flagged_not_hidden(client):
    wall = item(client, "MAS-WALL-001", "Walls, height TBC")
    shape(client, wall["id"], corners()[:2])
    qq = q(client, wall["id"])
    assert qq["quantity"] == 0 and qq["totals"]["length"] == pytest.approx(12.0)
    assert "height_m" in qq["issues"][0]


def test_scale_change_flows_through_live(client):
    sk = item(client, "FIN-SKIRT-001", "Skirting")
    shape(client, sk["id"], corners()[:2])
    assert q(client, sk["id"])["quantity"] == pytest.approx(12.0)
    r = client.put(f"/api/drawings/{client.did}/pages/0/scale", json={"method": "stated", "ratio": 200}).json()
    assert r["affected_shapes"] == 1
    assert q(client, sk["id"])["quantity"] == pytest.approx(24.0)


def test_unscaled_page_rejects_measure_but_allows_count(client):
    sk = item(client, "FIN-SKIRT-001", "Skirting")
    shape(client, sk["id"], corners()[:2], page=1, expect=422)
    doors = item(client, "WD-DOOR-001", "Doors")
    shape(client, doors["id"], [(10, 10)], page=1)
    shape(client, doors["id"], [(20, 10)], page=1)
    assert q(client, doors["id"])["quantity"] == 2


def test_shape_edit_and_validation(client):
    ceil = item(client, "FIN-PLB-CEIL-001", "Ceilings")
    s = shape(client, ceil["id"], corners())
    c = corners()
    r = client.patch(f"/api/shapes/{s['id']}", json={"points": [c[0], c[1], c[2], (c[3][0], c[3][1] - 4 * MM / 100 * 1000)]})
    assert r.status_code == 200
    bowtie = [c[0], c[2], c[1], c[3]]
    assert client.patch(f"/api/shapes/{s['id']}", json={"points": bowtie}).status_code == 422
    other = item(client, "WD-DOOR-001", "Doors")
    assert client.patch(f"/api/shapes/{s['id']}", json={"item_id": other["id"]}).status_code == 422
    deleted = client.delete(f"/api/shapes/{s['id']}").json()
    assert deleted["id"] == s["id"]                      # returned for client-side undo


def test_revision_transfer_and_compare(client, sample_pdf):
    r = client.post("/api/drawings", files={"file": ("rev-b.pdf", sample_pdf.read_bytes(), "application/pdf")})
    rev = r.json()["id"]
    sk = item(client, "FIN-SKIRT-001", "Skirting")
    shape(client, sk["id"], corners()[:2])
    t = client.post("/api/revisions/transfer", json={"from_drawing": client.did, "from_page": 0,
                                                    "to_drawing": rev, "to_page": 0, "mode": "move"}).json()
    assert t["shapes"] == 1 and "copied" in t["scale"]
    assert client.get("/api/shapes", params={"drawing_id": rev, "page": 0}).json()[0]["item_id"] == sk["id"]
    assert q(client, sk["id"])["quantity"] == pytest.approx(12.0)  # not double-counted
    img = client.get("/api/compare.png", params={"a": f"{client.did}:0", "b": f"{client.did}:1", "zoom": 0.5})
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    stats = dict(kv.split("=") for kv in img.headers["x-compare-stats"].split(","))
    assert int(stats["removed_px"]) > 0 and int(stats["added_px"]) > 0
    same = client.get("/api/compare.png", params={"a": f"{client.did}:0", "b": f"{rev}:0", "zoom": 0.5})
    stats = dict(kv.split("=") for kv in same.headers["x-compare-stats"].split(","))
    assert stats["removed_px"] == "0" and stats["added_px"] == "0"


def test_estimate_live_link_and_totals(client):
    slab = item(client, "CONC-SLAB-001", "GF slab", code="C01", inputs={"depth_m": 0.1})
    shape(client, slab["id"], corners())
    assert client.post("/api/estimate/from-items").json()["added"] == 1
    e = client.get("/api/estimate").json()
    row = e["sections"][0]["rows"][0]
    assert e["sections"][0]["name"] == "Concrete" and row["qty"] == pytest.approx(9.6)
    client.patch(f"/api/estimate/rows/{row['id']}", json={"material": 250, "labour": 50, "waste_pct": 5})
    # second row: same item, area metric (e.g. mesh), manual third row
    sec = e["sections"][0]["id"]
    client.post("/api/estimate/rows", json={"section_id": sec, "description": "SL82 mesh", "item_id": slab["id"],
                                            "item_metric": "area", "factor": 1.0, "material": 10})
    client.post("/api/estimate/rows", json={"section_id": sec, "description": "Pump hire", "manual_qty": 1,
                                            "unit": "item", "plant": 1200})
    client.patch("/api/project/meta", json={"margin_pct": 10, "contingency_pct": 5})
    s = client.get("/api/estimate").json()["summary"]
    sub = 9.6 * 1.05 * 300 + 96 * 10 + 1200
    assert s["subtotal"] == pytest.approx(sub)
    ex = sub * 1.05 * 1.10
    assert s["total_ex_gst"] == pytest.approx(ex) and s["total_inc_gst"] == pytest.approx(ex * 1.1)
    # live: change the slab depth -> estimate follows
    client.patch(f"/api/items/{slab['id']}", json={"inputs": {"depth_m": 0.2}})
    assert client.get("/api/estimate").json()["sections"][0]["rows"][0]["qty"] == pytest.approx(19.2)
    # deleting the item freezes linked rows at their last quantity
    client.delete(f"/api/items/{slab['id']}")
    rows = client.get("/api/estimate").json()["sections"][0]["rows"]
    assert rows[0]["item_id"] is None and rows[0]["qty"] == pytest.approx(19.2)


def test_excel_export_chain(client):
    slab = item(client, "CONC-SLAB-001", "GF slab", code="C01", inputs={"depth_m": 0.1})
    shape(client, slab["id"], corners())
    shape(client, slab["id"], rect(corners()[0][0] + 50, corners()[0][1] + 50, 1000, 1000), deduction=True)
    client.post("/api/estimate/from-items")
    row = client.get("/api/estimate").json()["sections"][0]["rows"][0]
    client.patch(f"/api/estimate/rows/{row['id']}", json={"material": 300})
    x = client.get("/api/export.xlsx")
    assert x.status_code == 200
    p = client.tmp / "out.xlsx"
    p.write_bytes(x.content)
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ["Read me", "Dimensions", "Items", "Estimate", "Rules cited", "Audit log"]
    assert wb["Items"]["F2"].value.startswith("=") and "SUMIFS(Dimensions!" in wb["Items"]["M2"].value
    est = wb["Estimate"]
    assert est["F3"].value.startswith("=Items!")
    assert client.get("/api/export.csv").content.decode("utf-8-sig").count("CONC-SLAB-001") == 1


def test_project_new_open_save_as_and_path_guard(client):
    base = client.tmp
    r = client.post("/api/project/save-as", json={"path": str(base / "copy")}).json()
    assert r["file"] == "copy.qto"
    assert len(client.get("/api/drawings").json()) == 1      # drawings travel inside the file
    r = client.post("/api/project/new", json={"path": str(base / "fresh.qto"), "name": "Fresh"}).json()
    assert r["meta"]["name"] == "Fresh" and client.get("/api/drawings").json() == []
    assert client.post("/api/project/open", json={"path": str(base / "copy.qto")}).status_code == 200
    assert client.post("/api/project/open", json={"path": "/etc/passwd"}).status_code in (403, 404)
    (base / "junk.qto").write_text("nope")
    assert client.post("/api/project/open", json={"path": str(base / "junk.qto")}).status_code == 422


def test_desktop_token_guard(tmp_path):
    app = create_app(tmp_path / "d.qto", token="s3cret", user_rules_dir=tmp_path / "u")
    c = TestClient(app, base_url="http://127.0.0.1:9999")
    assert c.get("/api/project").status_code == 401
    assert c.get("/api/project", headers={"x-takeoff-token": "s3cret"}).status_code == 200
    r = c.get("/?token=s3cret", follow_redirects=False)
    assert r.status_code == 303 and "takeoff_token" in r.headers["set-cookie"]
    assert c.get("/api/project").status_code == 200          # cookie now set
    evil = TestClient(app, base_url="http://evil.example:9999")
    assert evil.get("/api/project", headers={"x-takeoff-token": "s3cret"}).status_code == 403
