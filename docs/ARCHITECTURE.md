# Architecture (v0.2: desktop)

## Decisions

| Question | Decision | Why |
|---|---|---|
| Desktop technology | **pywebview** native window around the existing Python backend + HTML UI | Reuses the tested backend and UI unchanged. It uses the OS webview (WebView2 / WKWebView / Qt WebEngine), so Windows and macOS builds don't bundle a browser engine. The UI layer could later be replaced by Tauri or Qt without touching the backend. |
| Packaging | **PyInstaller** folder build, smoke-tested by `--self-test`; CI builds Windows + macOS | Standard for Python desktop apps; a folder build starts faster and trips antivirus less often than one-file. |
| Primary platform | **Windows**, with macOS and Linux supported | Australian QS teams overwhelmingly run Windows (as do Cubit and CostX). |
| Project storage | **One `.qto` file = SQLite with embedded PDFs** | Portable, email-able and archivable with a tender. SQLite is transactional, so a crash loses at most the last action. No separate "Save" to forget. |
| Quantities | **Computed live, never stored** | A scale correction, height change or vertex edit flows through to items, estimate and export immediately, so there are no stale numbers. |

## Components

```
┌───────────────────────── Takeoff.exe ───────────────────────────────────────┐
│  desktop.py                                                                  │
│   ├─ uvicorn on 127.0.0.1:<random>  ── token cookie + Host check             │
│   ├─ pywebview window ── loads http://127.0.0.1:<port>/?token=…              │
│   └─ Bridge (JS → Python): native open/save dialogs, PDF import, export      │
│                                                                              │
│  app/main.py (FastAPI)                                                       │
│   ├─ project.py      .qto file: drawings(pdf blob) pages items shapes        │
│   │                  est_sections est_rows meta audit_log                    │
│   ├─ quantities.py   shapes → metrics → item totals (live)                   │
│   ├─ estimate.py     rows → rate build-up → contingency/margin/GST           │
│   ├─ pdf_service.py  PyMuPDF render/analyse/snap + numpy revision overlay    │
│   ├─ rules.py        YAML rules + JSON Schema, user overrides                │
│   └─ export.py       Excel: Dimensions → Items → Estimate (live formulas)    │
│                                                                              │
│  static/js  core · takeoff (viewer, tools, undo) · estimate · compare · main │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Data model

```
drawing (pdf blob, sha256) 1─* page (label, title, revision, mm_per_pt, scale method/detail)
item (code, name, trade, kind, unit, rule_id + rule_snapshot + rule_hash, inputs, colour)
  1─* shape (drawing, page, points, holes[], sign ±1, per-shape input overrides)
est_section 1─* est_row (item_id? + metric + factor | manual_qty, waste %, labour/material/plant/subcontract)
audit_log (append-only: every scale, item, shape, revision and estimate change)
```

- **Item = dimension group.** One item, many shapes across many sheets. Each shape yields
  several *metrics* (area → area, perimeter, volume, slope area; line → length, face area;
  count). The rule picks the primary one, and estimate rows can link to any of them.
- **Cut-outs** are holes in an area shape (net area = outer − holes). They're validated to lie
  wholly inside the outline, concave outlines included. **Deductions** are whole shapes with
  sign −1, kept visible as negative lines in the export.
- **Revisions.** Shapes move or copy to the new sheet (with an optional offset). Scale is
  copied with a warning. *Move* is the default because *copy* double-counts unless the old
  sheet is meant to stay.
- **Deleting an item** turns linked estimate rows into fixed quantities, with a note, so
  estimate rows are never silently orphaned.

## Security of the local server

The backend listens on loopback only, on a random port, with a 256-bit per-launch token.
The window receives the token once in its URL and swaps it for an `HttpOnly; SameSite=Strict`
cookie. Requests without the token get 401, and a non-loopback `Host` header gets 403, which
blocks DNS-rebinding attempts from web pages. In desktop mode file paths come from native
dialogs. Dev mode restricts project and import paths to `data/`.

## Licensing (read before distributing)

| Component | Licence | Implication |
|---|---|---|
| **PyMuPDF** | **AGPL-3.0** or commercial (Artifex) | Distributing a closed-source app requires the commercial licence, or swap `pdf_service.py` to **pypdfium2** (Apache/BSD) + pdfplumber (MIT). PyMuPDF is used only in that module. |
| **PyQt6** (Linux build only) | **GPL-3.0** or commercial | Only bundled on Linux. For a closed-source Linux build, use **PySide6** (LGPL), which pywebview also supports. |
| pywebview, FastAPI, uvicorn, openpyxl, numpy, PyYAML, jsonschema | BSD/MIT-style | Fine. |
| WebView2 (Windows), WKWebView (macOS) | OS components | Not redistributed. |

Standards content: the library stores identifiers, paraphrases and links only, never clause
text (see the legal approach in RULES_SOURCES.md). Feature similarity to commercial tools is
fine. Their file formats and UI artwork are proprietary, so this project interoperates via
Excel and copies neither.

## Risks and limitations

| Risk | Mitigation now | Next |
|---|---|---|
| Wrong scale (reduced prints, mixed viewports, NTS details) | Sheet-size check, calibration cross-check, scale on every Dimensions row, green/orange dot per sheet, live re-measure | Per-viewport scale regions; require a check dimension per sheet before export |
| Scanned drawings | Detected and flagged; calibrate; no snapping | Deskew, separate X/Y calibration, OCR |
| Mouse precision at low zoom | Snap to vectors and existing takeoff; ortho lock | Typed lengths/angles, zoom-to-cursor loupe |
| Revision misalignment | Manual offset; overlay shows the mismatch | Auto-align by title block / grid-line registration |
| Unverified citations | `[UNVERIFIED]` everywhere; schema blocks unverified "verified" | Verification sign-off workflow, review dates |
| Large sets (hundreds of A0 sheets) | Render/snap caches; PDFs embedded once | Tiled rendering, background thumbnails, lazy page analysis |
| Single user | One file per project, auto-saved | File locking, then a shared server mode (Postgres) |
| Undo covers shapes only | Item/estimate deletes ask for confirmation | Server-side command log → full undo/history |
| Licences above | Isolated modules | Decide distribution model before release |

## Roadmap toward commercial-suite parity

**Next (takeoff depth)**
- Rate library: a firm-wide `.rates` file (resources, crews, composite rates) shared across
  projects, with rate history and an "update rates in this estimate" diff.
- Arc/curve tools, polygons from a fill click (closed linework detection), typed segment
  lengths, copy/paste and offset of shapes, multi-select.
- Per-viewport scales; layers / show-hide by trade; markups (clouds, text) that print.
- Reports: PDF trade summaries and BoQ layouts with company branding; marked-up drawing prints
  with takeoff colours and legend.
- Installer: Inno Setup / MSIX for Windows (with file association for `.qto`), signed and
  notarised macOS build.

**Then (automation)**
- Read the sheet number, title and revision from the title block; auto-pair revisions by
  sheet number.
- Auto-align revisions; flag takeoff shapes lying on changed linework.
- Symbol auto-count (vector signature match), room and wall detection from linework.
- ML element detection proposing items for QS review, with the audit trail as training data.

**Later**
- IFC/BIM quantity takeoff and cross-check against 2D; DWG/DXF import.
- Multi-user projects (server mode), comments and review/approval of takeoffs.
