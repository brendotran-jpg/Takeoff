"""HTTP API + UI.

Dev:      uvicorn app.main:app --reload          (project: data/default.qto)
Desktop:  python desktop.py                      (native window, see desktop.py)
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import estimate as est
from . import export, geometry as g, paths, pdf_service as pdf
from .project import PROJECT_EXT, Project, ProjectError
from .quantities import METRIC_KEYS, item_quantities
from .rules import RuleError, RulesLibrary, rule_hash

MAX_UPLOAD = 500 * 1024 * 1024
CATEGORIES = ["general", "substructure", "concrete", "formwork", "reinforcement", "masonry", "framing",
              "structural-steel", "roofing", "external-walls", "windows-doors", "internal-walls", "finishes",
              "wet-areas", "joinery", "services", "external-works"]
Pt = tuple[float, float]


# ------------------------------------------------------------------ models --
class ScaleIn(BaseModel):
    method: Literal["stated", "calibrated"]
    ratio: float | None = Field(None, gt=0)
    stated_sheet: str | None = None
    p1: Pt | None = None
    p2: Pt | None = None
    real_length_mm: float | None = Field(None, gt=0)


class Inputs(BaseModel):
    height_m: float | None = Field(None, gt=0, le=200)
    depth_m: float | None = Field(None, gt=0, le=50)
    pitch_deg: float | None = Field(None, ge=0, lt=80)


class PageIn(BaseModel):
    label: str | None = Field(None, max_length=60)
    title: str | None = Field(None, max_length=200)
    revision: str | None = Field(None, max_length=20)


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    rule_id: str
    code: str | None = Field(None, max_length=30)
    category: str | None = None
    inputs: Inputs = Inputs()
    colour: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    notes: str | None = None


class ItemPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    code: str | None = Field(None, max_length=30)
    category: str | None = None
    rule_id: str | None = None
    inputs: Inputs | None = None
    colour: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    notes: str | None = None


class ShapeIn(BaseModel):
    item_id: int
    drawing_id: int
    page: int = Field(ge=0)
    points: list[Pt] = Field(min_length=1, max_length=5000)
    holes: list[list[Pt]] = []
    deduction: bool = False
    inputs: Inputs = Inputs()


class ShapePatch(BaseModel):
    points: list[Pt] | None = Field(None, min_length=1, max_length=5000)
    holes: list[list[Pt]] | None = None
    deduction: bool | None = None
    inputs: Inputs | None = None
    item_id: int | None = None


class TransferIn(BaseModel):
    from_drawing: int
    from_page: int
    to_drawing: int
    to_page: int
    mode: Literal["move", "copy"] = "move"
    offset: Pt = (0.0, 0.0)
    copy_scale: bool = True
    item_ids: list[int] | None = None


class SectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class RowIn(BaseModel):
    section_id: int | None = None
    code: str | None = None
    description: str | None = Field(None, max_length=300)
    item_id: int | None = None
    item_metric: str | None = None
    factor: float | None = None
    manual_qty: float | None = None
    unit: str | None = None
    waste_pct: float | None = Field(None, ge=0, le=500)
    labour: float | None = None
    material: float | None = None
    plant: float | None = None
    subcontract: float | None = None
    notes: str | None = None
    unlink: bool = False


class MetaIn(BaseModel):
    name: str | None = Field(None, max_length=200)
    client: str | None = Field(None, max_length=200)
    margin_pct: float | None = Field(None, ge=0, le=500)
    contingency_pct: float | None = Field(None, ge=0, le=500)
    gst_pct: float | None = Field(None, ge=0, le=100)


class PathIn(BaseModel):
    path: str
    name: str | None = None


class ImportIn(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=200)


# --------------------------------------------------------------------- app --
def create_app(project_path: str | Path | None = None, *, rules_dir: str | Path | None = None,
               user_rules_dir: str | Path | None = None, token: str | None = None,
               fs_root: str | Path | None = None) -> FastAPI:
    """
    token:   when set (desktop mode) every request must carry it (cookie or header) and the
             Host header must be loopback. Prevents other local apps or web pages from
             driving the API.
    fs_root: when set, project/import paths must live under it. Desktop mode passes None
             (the user picks files with native dialogs), dev/server mode restricts to data/.
    """
    res = paths.resource_dir()
    lib = RulesLibrary(Path(rules_dir) if rules_dir else res / "rules",
                       Path(user_rules_dir) if user_rules_dir else None)
    fs_root = Path(fs_root).resolve() if fs_root else None

    app = FastAPI(title="Takeoff", version="0.2.0")
    st = app.state
    st.rules, st.desktop = lib, token is not None

    def open_project(path: Path, create: bool = False) -> Project:
        if getattr(st, "project", None):
            st.project.close()
        st.project = Project(path, create=create)
        if st.desktop:
            paths.add_recent(path)
        return st.project

    if project_path is None:
        project_path = Path(os.environ.get("TAKEOFF_DATA", res / "data")) / f"default{PROJECT_EXT}"
        Path(project_path).parent.mkdir(parents=True, exist_ok=True)
    open_project(Path(project_path), create=not Path(project_path).exists())

    def P() -> Project:
        return st.project

    # ------------------------------------------------------------ security --
    if token:
        @app.middleware("http")
        async def guard(request: Request, call_next):
            host = request.headers.get("host", "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                return JSONResponse({"detail": "forbidden host"}, status_code=403)
            if request.url.path == "/" and request.query_params.get("token"):
                if not hmac.compare_digest(request.query_params["token"], token):
                    return JSONResponse({"detail": "bad token"}, status_code=403)
                resp = RedirectResponse("/", status_code=303)
                resp.set_cookie("takeoff_token", token, httponly=True, samesite="strict")
                return resp
            supplied = request.cookies.get("takeoff_token") or request.headers.get("x-takeoff-token") or ""
            if not hmac.compare_digest(supplied, token):
                return JSONResponse({"detail": "unauthorised"}, status_code=401)
            return await call_next(request)

    def check_path(p: str, suffix: str | None = None, must_exist: bool = False) -> Path:
        path = Path(p).expanduser()
        if suffix and path.suffix.lower() != suffix:
            path = path.with_suffix(suffix)
        path = path.resolve()
        if fs_root and fs_root not in path.parents and path != fs_root:
            raise HTTPException(403, f"path must be inside {fs_root}")
        if must_exist and not path.is_file():
            raise HTTPException(404, f"file not found: {path}")
        return path

    # ------------------------------------------------------------- helpers --
    def drawing_or_404(did: int) -> dict:
        d = P().drawing(did)
        if not d:
            raise HTTPException(404, "drawing not found")
        return d

    def page_or_404(did: int, page: int) -> dict:
        d = drawing_or_404(did)
        if not 0 <= page < d["pages"]:
            raise HTTPException(404, "page out of range")
        return d

    def pdf_loader(did: int):
        return lambda: P().drawing_pdf(did)

    def all_quantities():
        prj = P()
        items = prj.items()
        scales = prj.scales()
        by_item: dict[int, list] = {}
        for s in prj.shapes():
            by_item.setdefault(s["item_id"], []).append(s)
        return items, {it["id"]: item_quantities(it, by_item.get(it["id"], []), scales) for it in items}

    def item_or_404(iid: int) -> dict:
        it = P().item(iid)
        if not it:
            raise HTTPException(404, "item not found")
        return it

    def measurable_rule(rule_id: str) -> dict:
        try:
            rule = lib.get(rule_id)
        except RuleError as e:
            raise HTTPException(422, str(e))
        if rule["measure_type"] == "reference":
            raise HTTPException(422, f"rule {rule_id} is a reference rule and cannot carry a quantity")
        return rule

    def rule_inputs(rule: dict, inputs: Inputs) -> dict:
        req = set(rule.get("required_inputs", []))
        return {k: v for k, v in inputs.model_dump().items() if k in req and v is not None}

    def validate_geometry(kind: str, did: int, page: int, points, holes) -> None:
        if kind == "linear" and len(points) < 2:
            raise HTTPException(422, "a linear measurement needs at least 2 points")
        if kind == "area":
            if len(points) < 3:
                raise HTTPException(422, "an area needs at least 3 points")
            if g.polygon_self_intersects(points):
                raise HTTPException(422, "area outline crosses itself - redraw the boundary")
            for h in holes:
                if len(h) < 3 or g.polygon_self_intersects(h):
                    raise HTTPException(422, "cut-out outline is invalid")
                if not g.polygon_inside(h, points):
                    raise HTTPException(422, "cut-out must lie wholly inside the area")
        elif holes:
            raise HTTPException(422, "only area shapes can have cut-outs")
        if kind != "count" and not (P().page(did, page) or {}).get("mm_per_pt"):
            raise HTTPException(422, "set or calibrate the page scale before measuring lengths or areas")

    # ------------------------------------------------------------- project --
    @app.get("/api/project")
    def project_info():
        prj = P()
        return {"path": str(prj.path), "file": prj.path.name, "meta": prj.meta(), "desktop": st.desktop,
                "recent": paths.recent_projects() if st.desktop else [],
                "projects_dir": str(fs_root or paths.default_projects_dir()), "categories": CATEGORIES}

    @app.patch("/api/project/meta")
    def project_meta(body: MetaIn):
        return P().set_meta(**body.model_dump(exclude_none=True))

    @app.post("/api/project/new")
    def project_new(body: PathIn):
        path = check_path(body.path, PROJECT_EXT)
        if path.exists():
            raise HTTPException(409, "a file with that name already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        prj = open_project(path, create=True)
        prj.set_meta(name=body.name or path.stem)
        return project_info()

    @app.post("/api/project/open")
    def project_open(body: PathIn):
        path = check_path(body.path, PROJECT_EXT, must_exist=True)
        try:
            open_project(path)
        except ProjectError as e:
            raise HTTPException(422, str(e))
        return project_info()

    @app.post("/api/project/save-as")
    def project_save_as(body: PathIn):
        path = check_path(body.path, PROJECT_EXT)
        P().save_as(path)
        open_project(path)
        return project_info()

    # ------------------------------------------------------------- drawings --
    def add_pdf(filename: str, blob: bytes) -> dict:
        if not blob.startswith(b"%PDF"):
            raise HTTPException(415, f"{filename}: not a PDF file")
        try:
            n = pdf.page_count(blob)
        except Exception as e:
            raise HTTPException(422, f"{filename}: could not open PDF ({e})")
        return P().add_drawing(Path(filename).name, hashlib.sha256(blob).hexdigest(), n, blob)

    @app.post("/api/drawings")
    async def upload(file: UploadFile = File(...)):
        blob = await file.read(MAX_UPLOAD + 1)
        if len(blob) > MAX_UPLOAD:
            raise HTTPException(413, "file too large")
        return add_pdf(file.filename or "drawing.pdf", blob)

    @app.post("/api/drawings/import")
    def import_paths(body: ImportIn):
        out = []
        for p in body.paths:
            path = check_path(p, must_exist=True)
            if path.stat().st_size > MAX_UPLOAD:
                raise HTTPException(413, f"{path.name}: file too large")
            out.append(add_pdf(path.name, path.read_bytes()))
        return out

    @app.get("/api/drawings")
    def drawings():
        return P().drawings()

    @app.delete("/api/drawings/{did}", status_code=204)
    def delete_drawing(did: int):
        drawing_or_404(did)
        P().delete_drawing(did)

    @app.get("/api/drawings/{did}/pages/{page}")
    def page_info(did: int, page: int):
        d = page_or_404(did, page)
        info = pdf.analyse_page(d["sha256"], pdf_loader(did), page)
        return {**info, "record": P().page(did, page)}

    @app.patch("/api/drawings/{did}/pages/{page}")
    def page_update(did: int, page: int, body: PageIn):
        page_or_404(did, page)
        return P().update_page(did, page, **body.model_dump(exclude_none=True))

    @app.get("/api/drawings/{did}/pages/{page}/image")
    def page_image(did: int, page: int, zoom: float = Query(1.5, gt=0, le=8)):
        d = page_or_404(did, page)
        return Response(pdf.render_png(d["sha256"], pdf_loader(did), page, zoom), media_type="image/png",
                        headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/api/drawings/{did}/pages/{page}/snap")
    def page_snap(did: int, page: int):
        d = page_or_404(did, page)
        return {"points": pdf.snap_points(d["sha256"], pdf_loader(did), page)}

    @app.put("/api/drawings/{did}/pages/{page}/scale")
    def set_scale(did: int, page: int, body: ScaleIn):
        d = page_or_404(did, page)
        info = pdf.analyse_page(d["sha256"], pdf_loader(did), page)
        detail: dict = {"sheet_size": info["sheet_size"], "is_scanned": info["is_scanned"]}
        if body.method == "stated":
            if not body.ratio:
                raise HTTPException(422, "ratio required for a stated scale")
            mm = g.mm_per_pt_from_ratio(body.ratio)
            corr = g.sheet_size_correction(body.stated_sheet, info["sheet_size"])
            if corr:
                mm *= corr
                detail["sheet_correction"] = corr
            detail.update(stated_ratio=body.ratio, stated_sheet=body.stated_sheet)
            if info["is_scanned"]:
                detail["warning"] = ("Scanned page: a stated scale is only valid if the scan was saved at true "
                                     "paper size. Check by calibrating against a known dimension.")
        else:
            if not (body.p1 and body.p2 and body.real_length_mm):
                raise HTTPException(422, "p1, p2 and real_length_mm required for calibration")
            try:
                mm = g.mm_per_pt_from_calibration(body.p1, body.p2, body.real_length_mm)
            except ValueError as e:
                raise HTTPException(422, str(e))
            detail.update(p1=body.p1, p2=body.p2, real_length_mm=body.real_length_mm)
            for c in info["scale_candidates"]:
                if abs(c["mm_per_pt"] - mm) / mm < 0.02:
                    detail["matches_stated"] = c["match"]
                    break
            else:
                if info["scale_candidates"]:
                    detail["warning"] = ("Calibrated scale does not match any scale stated on the sheet (within 2%). "
                                         "Check for a reduced print or a mis-picked dimension.")
        detail["effective_ratio"] = round(g.ratio_from_mm_per_pt(mm), 2)
        affected = len([s for s in P().shapes(did, page)])
        rec = P().set_scale(did, page, mm, body.method, detail)
        return {**rec, "affected_shapes": affected}

    # ------------------------------------------------------------ revisions --
    @app.get("/api/compare.png")
    def compare(a: str, b: str, zoom: float = 1.0, dx: float = 0.0, dy: float = 0.0):
        def parse(s):
            m = re.fullmatch(r"(\d+):(\d+)", s)
            if not m:
                raise HTTPException(422, "use drawing_id:page")
            did, page = int(m[1]), int(m[2])
            page_or_404(did, page)
            return P().drawing_pdf(did), page
        png, stats = pdf.compare_png(parse(a), parse(b), zoom, (dx, dy))
        return Response(png, media_type="image/png",
                        headers={"X-Compare-Stats": ",".join(f"{k}={v}" for k, v in stats.items())})

    @app.post("/api/revisions/transfer")
    def transfer(body: TransferIn):
        """Carry takeoff from a superseded sheet to its new revision."""
        page_or_404(body.from_drawing, body.from_page)
        page_or_404(body.to_drawing, body.to_page)
        if (body.from_drawing, body.from_page) == (body.to_drawing, body.to_page):
            raise HTTPException(422, "source and target are the same page")
        prj = P()
        src_page, dst_page = prj.page(body.from_drawing, body.from_page), prj.page(body.to_drawing, body.to_page)
        scale_note = None
        if body.copy_scale and src_page.get("mm_per_pt") and not dst_page.get("mm_per_pt"):
            prj.set_scale(body.to_drawing, body.to_page, src_page["mm_per_pt"], "copied",
                          {**(src_page.get("scale_detail") or {}),
                           "copied_from": [body.from_drawing, body.from_page],
                           "warning": "Scale copied from previous revision - confirm it on this sheet."})
            scale_note = "scale copied - confirm it on the new sheet"
        dx, dy = body.offset
        shift = lambda pts: [[x + dx, y + dy] for x, y in pts]  # noqa: E731
        moved = 0
        for s in prj.shapes(body.from_drawing, body.from_page):
            if body.item_ids and s["item_id"] not in body.item_ids:
                continue
            new_geom = {"drawing_id": body.to_drawing, "page": body.to_page, "points": shift(s["points"]),
                        "holes": [shift(h) for h in s["holes"]]}
            if body.mode == "move":
                prj.update_shape(s["id"], new_geom, reason=f"moved to revision {body.to_drawing}:{body.to_page}")
            else:
                prj.add_shape({**{k: s[k] for k in ("item_id", "sign", "inputs")}, **new_geom})
            moved += 1
        prj.log("revision.transfer", **body.model_dump(), shapes=moved)
        return {"shapes": moved, "mode": body.mode, "scale": scale_note}

    # ---------------------------------------------------------------- rules --
    @app.get("/api/rules")
    def list_rules():
        return {"rules": lib.list(), "errors": lib.errors}

    @app.post("/api/rules")
    def save_rule(rule: dict):
        try:
            return lib.save_user_rule({k: v for k, v in rule.items() if not k.startswith("_")})
        except RuleError as e:
            raise HTTPException(422, str(e))

    @app.post("/api/rules/reload")
    def reload_rules():
        lib.reload()
        return {"count": len(lib.rules), "errors": lib.errors}

    # ---------------------------------------------------------------- items --
    @app.get("/api/items")
    def list_items():
        items, q = all_quantities()
        return [{**it, "q": {k: v for k, v in q[it["id"]].items() if k != "per_shape"}} for it in items]

    @app.post("/api/items", status_code=201)
    def add_item(body: ItemIn):
        rule = measurable_rule(body.rule_id)
        if body.category and body.category not in CATEGORIES:
            raise HTTPException(422, "unknown category")
        return P().add_item({
            "code": body.code, "name": body.name, "category": body.category or rule["category"],
            "kind": rule["measure_type"], "unit": rule["unit"], "rule_id": rule["id"],
            "rule_hash": rule_hash(rule), "rule_snapshot": rule, "inputs": rule_inputs(rule, body.inputs),
            "colour": body.colour, "notes": body.notes,
        })

    @app.patch("/api/items/{iid}")
    def patch_item(iid: int, body: ItemPatch):
        it = item_or_404(iid)
        fields = body.model_dump(exclude_none=True, exclude={"inputs", "rule_id"})
        if body.category and body.category not in CATEGORIES:
            raise HTTPException(422, "unknown category")
        rule = it["rule_snapshot"]
        if body.rule_id:  # same id re-snapshots the latest version of that rule
            rule = measurable_rule(body.rule_id)
            if rule["measure_type"] != it["kind"]:
                raise HTTPException(422, f"rule {rule['id']} measures '{rule['measure_type']}', "
                                         f"this item is '{it['kind']}'")
            fields.update(rule_id=rule["id"], unit=rule["unit"], rule_hash=rule_hash(rule), rule_snapshot=rule)
        if body.inputs is not None or body.rule_id:
            fields["inputs"] = rule_inputs(rule, body.inputs or Inputs(**it["inputs"]))
        return P().update_item(iid, fields)

    @app.delete("/api/items/{iid}", status_code=204)
    def delete_item(iid: int):
        item_or_404(iid)
        items, q = all_quantities()
        last = {r["id"]: est.row_quantity(r, q)[0] for r in P().est_rows() if r["item_id"] == iid}
        P().delete_item(iid, last)

    # --------------------------------------------------------------- shapes --
    @app.get("/api/shapes")
    def list_shapes(drawing_id: int | None = None, page: int | None = None, item_id: int | None = None):
        _, q = all_quantities()
        out = []
        for s in P().shapes(drawing_id, page, item_id):
            out.append({**s, "metrics": q[s["item_id"]]["per_shape"].get(s["id"])})
        return out

    @app.post("/api/shapes", status_code=201)
    def add_shape(body: ShapeIn):
        it = item_or_404(body.item_id)
        page_or_404(body.drawing_id, body.page)
        validate_geometry(it["kind"], body.drawing_id, body.page, body.points, body.holes)
        return P().add_shape({
            "item_id": it["id"], "drawing_id": body.drawing_id, "page": body.page,
            "points": [list(p) for p in body.points], "holes": [[list(p) for p in h] for h in body.holes],
            "sign": -1 if body.deduction else 1,
            "inputs": rule_inputs(it["rule_snapshot"], body.inputs),
        })

    @app.patch("/api/shapes/{sid}")
    def patch_shape(sid: int, body: ShapePatch):
        s = P().shape(sid)
        if not s:
            raise HTTPException(404, "shape not found")
        it = item_or_404(body.item_id or s["item_id"])
        if body.item_id and it["kind"] != P().item(s["item_id"])["kind"]:
            raise HTTPException(422, "can only move a shape to an item of the same measure type")
        fields: dict = {}
        if body.points is not None:
            fields["points"] = [list(p) for p in body.points]
        if body.holes is not None:
            fields["holes"] = [[list(p) for p in h] for h in body.holes]
        if body.deduction is not None:
            fields["sign"] = -1 if body.deduction else 1
        if body.inputs is not None:
            fields["inputs"] = rule_inputs(it["rule_snapshot"], body.inputs)
        if body.item_id:
            fields["item_id"] = body.item_id
        if "points" in fields or "holes" in fields:
            validate_geometry(it["kind"], s["drawing_id"], s["page"], fields.get("points", s["points"]),
                              fields.get("holes", s["holes"]))
        return P().update_shape(sid, fields)

    @app.delete("/api/shapes/{sid}")
    def delete_shape(sid: int):
        s = P().delete_shape(sid)
        if not s:
            raise HTTPException(404, "shape not found")
        return s  # returned so the client can undo

    # ------------------------------------------------------------- estimate --
    def estimate_view():
        items, q = all_quantities()
        prj = P()
        return est.build(prj.sections(), prj.est_rows(), {i["id"]: i for i in items}, q, prj.meta())

    @app.get("/api/estimate")
    def get_estimate():
        return estimate_view()

    @app.post("/api/estimate/sections", status_code=201)
    def add_section(body: SectionIn):
        return P().add_section(body.name)

    @app.patch("/api/estimate/sections/{sid}")
    def rename_section(sid: int, body: SectionIn):
        P().update_section(sid, name=body.name)
        return estimate_view()

    @app.delete("/api/estimate/sections/{sid}", status_code=204)
    def delete_section(sid: int):
        P().delete_section(sid)

    def check_row_link(body: RowIn):
        if body.item_id is not None:
            item_or_404(body.item_id)
        if body.item_metric and body.item_metric not in METRIC_KEYS:  # "" = item's primary metric
            raise HTTPException(422, f"metric must be one of {METRIC_KEYS}")

    @app.post("/api/estimate/rows", status_code=201)
    def add_row(body: RowIn):
        check_row_link(body)
        if body.section_id is None or not any(s["id"] == body.section_id for s in P().sections()):
            raise HTTPException(422, "valid section_id required")
        vals = body.model_dump(exclude_none=True, exclude={"unlink"})
        if vals.get("item_metric") == "":
            vals["item_metric"] = None
        if "description" not in vals:
            vals["description"] = P().item(body.item_id)["name"] if body.item_id else "New row"
        return P().add_est_row(vals)

    @app.patch("/api/estimate/rows/{rid}")
    def patch_row(rid: int, body: RowIn):
        row = P().est_row(rid)
        if not row:
            raise HTTPException(404, "row not found")
        check_row_link(body)
        fields = body.model_dump(exclude_none=True, exclude={"unlink"})
        if body.item_metric == "":
            fields["item_metric"] = None
        if body.unlink and row["item_id"]:
            _, q = all_quantities()
            fields.update(item_id=None, item_metric=None, manual_qty=est.row_quantity(row, q)[0])
        return P().update_est_row(rid, fields)

    @app.delete("/api/estimate/rows/{rid}", status_code=204)
    def delete_row(rid: int):
        P().delete_est_row(rid)

    @app.post("/api/estimate/from-items")
    def rows_from_items():
        """Add a linked row for every item not yet in the estimate, one section per trade."""
        prj = P()
        linked = {r["item_id"] for r in prj.est_rows() if r["item_id"]}
        secs = {s["name"].lower(): s["id"] for s in prj.sections()}
        added = 0
        for it in prj.items():
            if it["id"] in linked:
                continue
            name = it["category"].replace("-", " ").title()
            if name.lower() not in secs:
                secs[name.lower()] = prj.add_section(name)["id"]
            prj.add_est_row({"section_id": secs[name.lower()], "code": it["code"], "description": it["name"],
                             "item_id": it["id"]})
            added += 1
        return {"added": added}

    # --------------------------------------------------------------- export --
    def _fname(ext):
        name = re.sub(r"[^\w\- ]+", "", P().meta().get("name") or "takeoff").strip() or "takeoff"
        return {"Content-Disposition": f'attachment; filename="{name}.{ext}"'}

    def export_bytes(kind: str) -> bytes:
        items, q = all_quantities()
        if kind == "csv":
            return export.to_csv(items, q)
        prj = P()
        shapes = prj.shapes()
        pages = {(p["drawing_id"], p["page"]): p for d in prj.drawings() for p in d["page_list"]}
        drawings = {d["id"]: d for d in prj.drawings()}
        used, seen = [], set()
        for it in items:
            if (it["rule_id"], it["rule_hash"]) not in seen:
                seen.add((it["rule_id"], it["rule_hash"]))
                used.append({**it["rule_snapshot"], "_hash": it["rule_hash"]})
        return export.to_xlsx(meta=prj.meta(), items=items, item_q=q, shapes=shapes, pages=pages,
                              drawings=drawings, est=estimate_view(), rules_used=used, audit=prj.audit())

    @app.get("/api/export.csv")
    def export_csv():
        return Response(export_bytes("csv"), media_type="text/csv", headers=_fname("csv"))

    @app.get("/api/export.xlsx")
    def export_xlsx():
        return Response(export_bytes("xlsx"), headers=_fname("xlsx"),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    app.state.export_bytes = export_bytes

    @app.get("/api/audit")
    def audit():
        return P().audit()

    # ------------------------------------------------------------------ UI --
    app.mount("/static", StaticFiles(directory=res / "static"), name="static")

    @app.get("/")
    def index():
        return FileResponse(res / "static" / "index.html", headers={"Cache-Control": "no-store"})

    return app


def _default_app() -> FastAPI:
    data = Path(os.environ.get("TAKEOFF_DATA", paths.resource_dir() / "data"))
    data.mkdir(parents=True, exist_ok=True)
    return create_app(data / f"default{PROJECT_EXT}", fs_root=data)


app = _default_app() if os.environ.get("TAKEOFF_NO_DEFAULT_APP") != "1" else None
