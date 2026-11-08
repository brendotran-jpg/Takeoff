"""PDF access via PyMuPDF, working from PDF bytes stored in the project.

PyMuPDF is not thread-safe, so every call into it is serialised behind one
lock. Rendering, page analysis and snap points are cached by the PDF's
SHA-256, so repeat views are instant.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Callable

import numpy as np
import pymupdf

from . import geometry as g

MAX_SNAP_POINTS = 40000
_LOCK = threading.RLock()


class _LRU(OrderedDict):
    def __init__(self, maxsize: int):
        super().__init__()
        self.maxsize = maxsize

    def get_or(self, key, make: Callable):
        with _LOCK:
            if key in self:
                self.move_to_end(key)
                return self[key]
            val = make()
            self[key] = val
            if len(self) > self.maxsize:
                self.popitem(last=False)
            return val


_renders = _LRU(96)
_analysis = _LRU(256)
_snaps = _LRU(32)


def open_bytes(data: bytes) -> pymupdf.Document:
    return pymupdf.open(stream=data, filetype="pdf")


def page_count(data: bytes) -> int:
    with _LOCK, open_bytes(data) as doc:
        if doc.needs_pass:
            raise ValueError("PDF is password-protected")
        return doc.page_count


def render_png(sha: str, data: Callable[[], bytes], page_no: int, zoom: float) -> bytes:
    zoom = round(max(0.1, min(zoom, 8.0)), 3)

    def make():
        with open_bytes(data()) as doc:
            pix = doc[page_no].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            return pix.tobytes("png")
    return _renders.get_or((sha, page_no, zoom), make)


def analyse_page(sha: str, data: Callable[[], bytes], page_no: int) -> dict:
    def make():
        with open_bytes(data()) as doc:
            page = doc[page_no]
            rect = page.rect
            text = page.get_text("text") or ""
            drawings = page.get_drawings()
            img_cover = 0.0
            for img in page.get_images(full=True):
                for r in page.get_image_rects(img[0]):
                    img_cover = max(img_cover, (r & rect).get_area() / max(rect.get_area(), 1))
            is_scanned = len(drawings) < 5 and img_cover > 0.6
            actual_sheet = g.classify_sheet(rect.width, rect.height)
            candidates = []
            for c in g.find_scale_statements(text):
                mm_per_pt = g.mm_per_pt_from_ratio(c["ratio"])
                corr = g.sheet_size_correction(c["stated_sheet"], actual_sheet)
                warn = None
                if corr:
                    warn = (f"Sheet states {c['match']!r} but this PDF page is {actual_sheet}. "
                            f"Scale adjusted by x{corr:.3f}. Verify by calibrating against a known dimension.")
                    mm_per_pt *= corr
                candidates.append({**c, "mm_per_pt": mm_per_pt, "warning": warn})
            return {
                "page": page_no, "width_pt": rect.width, "height_pt": rect.height,
                "rotation": page.rotation, "sheet_size": actual_sheet,
                "vector_paths": len(drawings), "is_scanned": is_scanned,
                "scale_candidates": candidates, "has_text_layer": bool(text.strip()),
            }
    return _analysis.get_or((sha, page_no), make)


def snap_points(sha: str, data: Callable[[], bytes], page_no: int) -> list[list[float]]:
    """Vertices of vector paths in displayed-page coordinates (rotation applied)."""
    def make():
        pts: set[tuple[float, float]] = set()
        with open_bytes(data()) as doc:
            page = doc[page_no]
            m = page.rotation_matrix
            for d in page.get_drawings():
                for item in d["items"]:
                    op = item[0]
                    if op == "l":
                        raw = [item[1], item[2]]
                    elif op == "re":
                        r = item[1]
                        raw = [r.tl, r.tr, r.br, r.bl]
                    elif op == "qu":
                        q = item[1]
                        raw = [q.ul, q.ur, q.lr, q.ll]
                    elif op == "c":
                        raw = [item[1], item[4]]
                    else:
                        continue
                    for p in raw:
                        tp = p * m
                        pts.add((round(tp.x, 3), round(tp.y, 3)))
                if len(pts) >= MAX_SNAP_POINTS:
                    break
        return [list(p) for p in pts]
    return _snaps.get_or((sha, page_no), make)


def _gray(data: bytes, page_no: int, zoom: float) -> np.ndarray:
    with open_bytes(data) as doc:
        pix = doc[page_no].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()


def compare_png(old: tuple[bytes, int], new: tuple[bytes, int], zoom: float,
                offset_pt: tuple[float, float] = (0.0, 0.0)) -> tuple[bytes, dict]:
    """Overlay two drawing revisions.

    Ink only in OLD -> red (removed), ink only in NEW -> green/blue (added),
    ink in both -> dark grey. `offset_pt` shifts the new sheet to align
    revisions whose title blocks or margins moved.
    """
    zoom = max(0.25, min(zoom, 3.0))
    with _LOCK:
        a = _gray(old[0], old[1], zoom)
        b = _gray(new[0], new[1], zoom)
    dx, dy = int(round(offset_pt[0] * zoom)), int(round(offset_pt[1] * zoom))
    h, w = max(a.shape[0], b.shape[0] + max(dy, 0)), max(a.shape[1], b.shape[1] + max(dx, 0))
    A = np.full((h, w), 255, np.uint8)
    B = np.full((h, w), 255, np.uint8)
    A[:a.shape[0], :a.shape[1]] = a
    by, bx = max(dy, 0), max(dx, 0)
    sy, sx = max(-dy, 0), max(-dx, 0)
    bh, bw = b.shape[0] - sy, b.shape[1] - sx
    B[by:by + bh, bx:bx + bw] = b[sy:sy + bh, sx:sx + bw]
    ink_a, ink_b = A < 160, B < 160
    out = np.full((h, w, 3), 255, np.uint8)
    both = ink_a & ink_b
    only_a, only_b = ink_a & ~ink_b, ink_b & ~ink_a
    out[both] = (90, 90, 90)
    out[only_a] = (220, 38, 38)
    out[only_b] = (22, 163, 74)
    stats = {"removed_px": int(only_a.sum()), "added_px": int(only_b.sum()), "common_px": int(both.sum()),
             "width": w, "height": h, "zoom": zoom}
    with _LOCK:
        pix = pymupdf.Pixmap(pymupdf.csRGB, w, h, out.tobytes(), False)
        return pix.tobytes("png"), stats
