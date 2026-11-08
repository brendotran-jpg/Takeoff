"""A takeoff project is ONE portable SQLite file (*.qto).

The PDFs are embedded as blobs, so a project can be emailed, archived with a
tender, or reopened years later without broken links to drawing files.
SQLite writes each change as it happens (no separate "Save" step to forget),
and "Save As" uses SQLite's online backup.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 2
PROJECT_EXT = ".qto"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drawings (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    pages INTEGER NOT NULL,
    pdf BLOB NOT NULL,
    uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    drawing_id INTEGER NOT NULL REFERENCES drawings(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    label TEXT,                    -- sheet number, e.g. A-101
    title TEXT,
    revision TEXT,
    mm_per_pt REAL,
    scale_method TEXT CHECK (scale_method IN ('stated', 'calibrated', 'copied')),
    scale_detail TEXT,
    scale_set_at TEXT,
    PRIMARY KEY (drawing_id, page)
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    code TEXT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('linear', 'area', 'count')),
    unit TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    rule_hash TEXT NOT NULL,
    rule_snapshot TEXT NOT NULL,
    inputs TEXT NOT NULL DEFAULT '{}',
    colour TEXT NOT NULL,
    notes TEXT,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shapes (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    drawing_id INTEGER NOT NULL REFERENCES drawings(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    points TEXT NOT NULL,
    holes TEXT NOT NULL DEFAULT '[]',
    sign INTEGER NOT NULL DEFAULT 1 CHECK (sign IN (1, -1)),
    inputs TEXT NOT NULL DEFAULT '{}',   -- per-shape overrides, e.g. a different wall height
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS shapes_page ON shapes (drawing_id, page);
CREATE INDEX IF NOT EXISTS shapes_item ON shapes (item_id);
CREATE TABLE IF NOT EXISTS est_sections (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS est_rows (
    id INTEGER PRIMARY KEY,
    section_id INTEGER NOT NULL REFERENCES est_sections(id) ON DELETE CASCADE,
    sort INTEGER NOT NULL DEFAULT 0,
    code TEXT,
    description TEXT NOT NULL,
    item_id INTEGER REFERENCES items(id) ON DELETE SET NULL,
    item_metric TEXT,              -- which metric of the item; NULL = primary
    factor REAL NOT NULL DEFAULT 1,
    manual_qty REAL,
    unit TEXT,
    waste_pct REAL NOT NULL DEFAULT 0,
    labour REAL NOT NULL DEFAULT 0,
    material REAL NOT NULL DEFAULT 0,
    plant REAL NOT NULL DEFAULT 0,
    subcontract REAL NOT NULL DEFAULT 0,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""

DEFAULT_META = {
    "name": "Untitled project",
    "client": "",
    "margin_pct": "0",
    "contingency_pct": "0",
    "gst_pct": "10",
}

PALETTE = ["#0ea5e9", "#dc2626", "#16a34a", "#d97706", "#9333ea", "#0891b2", "#db2777",
           "#65a30d", "#2563eb", "#ea580c", "#7c3aed", "#be123c", "#14b8a6", "#a16207"]

_JSON = {"items": ("rule_snapshot", "inputs"), "shapes": ("points", "holes", "inputs"),
         "pages": ("scale_detail",)}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProjectError(ValueError):
    pass


class _Result:
    """Fully-fetched cursor result, so no cursor outlives the lock."""
    def __init__(self, cur):
        self.rows = cur.fetchall() if cur.description else []
        self.lastrowid = cur.lastrowid

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class _Conn:
    """sqlite3 connection where every statement runs under one re-entrant lock
    (API handlers run on a thread pool)."""
    def __init__(self, con: sqlite3.Connection, lock):
        self.con, self.lock = con, lock

    def execute(self, sql, args=()):
        with self.lock:
            return _Result(self.con.execute(sql, args))

    def executescript(self, sql):
        with self.lock:
            self.con.executescript(sql)

    def backup(self, target):
        with self.lock:
            self.con.backup(target)

    def close(self):
        with self.lock:
            self.con.close()


class Project:
    def __init__(self, path: str | Path, create: bool = False):
        self.path = Path(path)
        if not create and not self.path.exists():
            raise ProjectError(f"project not found: {self.path}")
        if not create:
            self._check_is_project()
        self.lock = threading.RLock()
        con = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        con.row_factory = sqlite3.Row
        self.db = _Conn(con, self.lock)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = DELETE")  # single file on disk, no -wal sidecar
        self.db.executescript(SCHEMA)
        for k, v in DEFAULT_META.items():
            self.db.execute("INSERT OR IGNORE INTO meta VALUES (?, ?)", (k, v))
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        if create:
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('created_at', ?)", (now(),))

    def _check_is_project(self):
        with open(self.path, "rb") as f:
            if f.read(16) != b"SQLite format 3\x00":
                raise ProjectError("not a takeoff project file")
        con = sqlite3.connect(str(self.path))
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
        if tables and not {"meta", "items", "shapes"} <= tables:
            raise ProjectError("this SQLite file is not a takeoff project (or is from an older version)")

    def close(self):
        self.db.close()

    def save_as(self, dest: str | Path) -> None:
        dest = Path(dest)
        if dest.resolve() == self.path.resolve():
            return
        with self.lock:
            target = sqlite3.connect(str(dest))
            try:
                self.db.backup(target)
            finally:
                target.close()
        self.log("project.save_as", dest=str(dest))

    # ---------------------------------------------------------------- utils --
    def _row(self, table: str, r) -> dict:
        d = dict(r)
        for c in _JSON.get(table, ()):
            if c in d and d[c] is not None:
                d[c] = json.loads(d[c])
        return d

    def _enc(self, table: str, vals: dict) -> dict:
        return {k: (json.dumps(v) if k in _JSON.get(table, ()) and v is not None else v) for k, v in vals.items()}

    def _insert(self, table: str, vals: dict) -> int:
        vals = self._enc(table, vals)
        cols = ", ".join(vals)
        with self.lock:
            cur = self.db.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(vals))})",
                                  tuple(vals.values()))
            return cur.lastrowid

    def _update(self, table: str, key: dict, vals: dict) -> None:
        vals = self._enc(table, vals)
        sets = ", ".join(f"{k}=?" for k in vals)
        where = " AND ".join(f"{k}=?" for k in key)
        with self.lock:
            self.db.execute(f"UPDATE {table} SET {sets} WHERE {where}", (*vals.values(), *key.values()))

    def log(self, action: str, **detail) -> None:
        with self.lock:
            self.db.execute("INSERT INTO audit_log (ts, action, detail) VALUES (?,?,?)",
                            (now(), action, json.dumps(detail, default=str)))

    def audit(self) -> list[dict]:
        return [{**dict(r), "detail": json.loads(r["detail"])}
                for r in self.db.execute("SELECT * FROM audit_log ORDER BY id")]

    # ----------------------------------------------------------------- meta --
    def meta(self) -> dict:
        return {r["key"]: r["value"] for r in self.db.execute("SELECT * FROM meta")}

    def set_meta(self, **kv) -> dict:
        with self.lock:
            for k, v in kv.items():
                self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (k, str(v)))
        self.log("project.meta", **kv)
        return self.meta()

    # ------------------------------------------------------------- drawings --
    def add_drawing(self, filename: str, sha: str, pages: int, pdf: bytes) -> dict:
        did = self._insert("drawings", dict(filename=filename, sha256=sha, pages=pages, pdf=pdf,
                                            uploaded_at=now()))
        for p in range(pages):
            self._insert("pages", dict(drawing_id=did, page=p, label=f"{Path(filename).stem} p{p + 1}"))
        self.log("drawing.add", id=did, filename=filename, sha256=sha, pages=pages)
        return self.drawing(did)

    def drawings(self) -> list[dict]:
        out = []
        for r in self.db.execute("SELECT id, filename, sha256, pages, uploaded_at FROM drawings ORDER BY id"):
            d = dict(r)
            d["page_list"] = self.pages(d["id"])
            out.append(d)
        return out

    def drawing(self, did: int) -> dict | None:
        r = self.db.execute("SELECT id, filename, sha256, pages, uploaded_at FROM drawings WHERE id=?",
                            (did,)).fetchone()
        return dict(r) if r else None

    def drawing_pdf(self, did: int) -> bytes:
        r = self.db.execute("SELECT pdf FROM drawings WHERE id=?", (did,)).fetchone()
        if not r:
            raise ProjectError("drawing not found")
        return r["pdf"]

    def delete_drawing(self, did: int) -> None:
        n = self.db.execute("SELECT COUNT(*) FROM shapes WHERE drawing_id=?", (did,)).fetchone()[0]
        with self.lock:
            self.db.execute("DELETE FROM drawings WHERE id=?", (did,))
        self.log("drawing.delete", id=did, shapes_deleted=n)

    # ---------------------------------------------------------------- pages --
    def pages(self, did: int) -> list[dict]:
        return [self._row("pages", r) for r in
                self.db.execute("SELECT * FROM pages WHERE drawing_id=? ORDER BY page", (did,))]

    def page(self, did: int, page: int) -> dict | None:
        r = self.db.execute("SELECT * FROM pages WHERE drawing_id=? AND page=?", (did, page)).fetchone()
        return self._row("pages", r) if r else None

    def update_page(self, did: int, page: int, **fields) -> dict:
        self._update("pages", {"drawing_id": did, "page": page}, fields)
        return self.page(did, page)

    def set_scale(self, did: int, page: int, mm_per_pt: float, method: str, detail: dict) -> dict:
        old = self.page(did, page)
        p = self.update_page(did, page, mm_per_pt=mm_per_pt, scale_method=method,
                             scale_detail=detail, scale_set_at=now())
        self.log("scale.set", drawing_id=did, page=page, mm_per_pt=mm_per_pt, method=method,
                 previous=old.get("mm_per_pt") if old else None, detail=detail)
        return p

    def scales(self) -> dict[tuple[int, int], float | None]:
        return {(r["drawing_id"], r["page"]): r["mm_per_pt"]
                for r in self.db.execute("SELECT drawing_id, page, mm_per_pt FROM pages")}

    # ---------------------------------------------------------------- items --
    def add_item(self, vals: dict) -> dict:
        if not vals.get("colour"):
            n = self.db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            vals["colour"] = PALETTE[n % len(PALETTE)]
        ts = now()
        sort = self.db.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM items").fetchone()[0]
        iid = self._insert("items", {**vals, "sort": sort, "created_at": ts, "updated_at": ts})
        self.log("item.add", id=iid, name=vals["name"], rule_id=vals["rule_id"], rule_hash=vals["rule_hash"])
        return self.item(iid)

    def item(self, iid: int) -> dict | None:
        r = self.db.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        return self._row("items", r) if r else None

    def items(self) -> list[dict]:
        return [self._row("items", r) for r in self.db.execute("SELECT * FROM items ORDER BY category, sort, id")]

    def update_item(self, iid: int, fields: dict) -> dict:
        self._update("items", {"id": iid}, {**fields, "updated_at": now()})
        self.log("item.update", id=iid, fields={k: v for k, v in fields.items() if k != "rule_snapshot"})
        return self.item(iid)

    def delete_item(self, iid: int, last_quantities: dict[int, float]) -> None:
        """Estimate rows linked to the item keep their last quantity as a manual value."""
        with self.lock:
            for r in self.db.execute("SELECT id FROM est_rows WHERE item_id=?", (iid,)).fetchall():
                self.db.execute("UPDATE est_rows SET manual_qty=?, item_id=NULL, notes=COALESCE(notes,'') || ? "
                                "WHERE id=?", (last_quantities.get(r["id"]),
                                               f" [linked item {iid} deleted {now()[:10]}]", r["id"]))
            item = self.item(iid)
            n = self.db.execute("SELECT COUNT(*) FROM shapes WHERE item_id=?", (iid,)).fetchone()[0]
            self.db.execute("DELETE FROM items WHERE id=?", (iid,))
        self.log("item.delete", id=iid, name=item and item["name"], shapes_deleted=n)

    # --------------------------------------------------------------- shapes --
    def add_shape(self, vals: dict) -> dict:
        ts = now()
        sid = self._insert("shapes", {**vals, "created_at": ts, "updated_at": ts})
        self.log("shape.add", id=sid, item_id=vals["item_id"], drawing_id=vals["drawing_id"], page=vals["page"])
        return self.shape(sid)

    def shape(self, sid: int) -> dict | None:
        r = self.db.execute("SELECT * FROM shapes WHERE id=?", (sid,)).fetchone()
        return self._row("shapes", r) if r else None

    def shapes(self, drawing_id: int | None = None, page: int | None = None,
               item_id: int | None = None) -> list[dict]:
        q, args = "SELECT * FROM shapes WHERE 1=1", []
        for col, v in (("drawing_id", drawing_id), ("page", page), ("item_id", item_id)):
            if v is not None:
                q += f" AND {col}=?"
                args.append(v)
        return [self._row("shapes", r) for r in self.db.execute(q + " ORDER BY id", args)]

    def update_shape(self, sid: int, fields: dict, reason: str = "edit") -> dict:
        self._update("shapes", {"id": sid}, {**fields, "updated_at": now()})
        self.log("shape.update", id=sid, reason=reason, fields=sorted(fields))
        return self.shape(sid)

    def delete_shape(self, sid: int) -> dict | None:
        s = self.shape(sid)
        with self.lock:
            self.db.execute("DELETE FROM shapes WHERE id=?", (sid,))
        self.log("shape.delete", id=sid, snapshot=s)
        return s

    # ------------------------------------------------------------- estimate --
    def sections(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM est_sections ORDER BY sort, id")]

    def add_section(self, name: str) -> dict:
        sort = self.db.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM est_sections").fetchone()[0]
        sid = self._insert("est_sections", dict(name=name, sort=sort))
        self.log("estimate.section.add", id=sid, name=name)
        return dict(self.db.execute("SELECT * FROM est_sections WHERE id=?", (sid,)).fetchone())

    def update_section(self, sid: int, **fields) -> None:
        self._update("est_sections", {"id": sid}, fields)

    def delete_section(self, sid: int) -> None:
        with self.lock:
            self.db.execute("DELETE FROM est_sections WHERE id=?", (sid,))
        self.log("estimate.section.delete", id=sid)

    def est_rows(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM est_rows ORDER BY section_id, sort, id")]

    def est_row(self, rid: int) -> dict | None:
        r = self.db.execute("SELECT * FROM est_rows WHERE id=?", (rid,)).fetchone()
        return dict(r) if r else None

    def add_est_row(self, vals: dict) -> dict:
        sort = self.db.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM est_rows WHERE section_id=?",
                               (vals["section_id"],)).fetchone()[0]
        rid = self._insert("est_rows", {**vals, "sort": sort})
        self.log("estimate.row.add", id=rid, **{k: vals.get(k) for k in ("description", "item_id")})
        return self.est_row(rid)

    def update_est_row(self, rid: int, fields: dict) -> dict:
        self._update("est_rows", {"id": rid}, fields)
        self.log("estimate.row.update", id=rid, fields=fields)
        return self.est_row(rid)

    def delete_est_row(self, rid: int) -> None:
        with self.lock:
            self.db.execute("DELETE FROM est_rows WHERE id=?", (rid,))
        self.log("estimate.row.delete", id=rid)
