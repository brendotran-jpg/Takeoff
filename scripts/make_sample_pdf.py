"""Generate a 3-page test drawing set with known dimensions.

  p1  A3 vector plan, 'SCALE 1:100 @ A3'          - true scale
  p2  same plan drawn at 1:50, titled '1:50 @ A1'  but issued on A3 (reduced
      print, so the effective scale is ~1:100) - tests the sheet-size check
  p3  p1 rasterised at 150 dpi (simulated scan)    - tests scanned detection

Building: 12.0 m x 8.0 m external, 230 mm walls, one internal wall,
2 doors, 4 windows.  Expected at 1:100 -> plan area 96.0 m2, perimeter 40.0 m.

usage: python scripts/make_sample_pdf.py [out.pdf] [--rev-b]
       --rev-b writes a one-page revision B of sheet 1 (internal wall moved 1 m)
"""
import sys

import pymupdf

MM = 72 / 25.4  # points per paper mm
A3_LAND = (420 * MM, 297 * MM)


def draw_plan(page, ratio, origin=(60 * MM, 50 * MM), internal_x=5000):
    s = MM / ratio  # points per real mm
    ox, oy = origin
    W, H, T = 12000, 8000, 230

    def R(x, y, w, h):
        return pymupdf.Rect(ox + x * s, oy + y * s, ox + (x + w) * s, oy + (y + h) * s)

    shape = page.new_shape()
    # external walls (outer + inner face)
    shape.draw_rect(R(0, 0, W, H))
    shape.draw_rect(R(T, T, W - 2 * T, H - 2 * T))
    # internal wall at x = 5000
    shape.draw_rect(R(internal_x, T, 90, H - 2 * T))
    shape.finish(color=(0, 0, 0), width=0.6)
    # doors: leaf line + swing arc
    for dx in (1500, 7000):
        y = H
        shape.draw_line(pymupdf.Point(ox + dx * s, oy + y * s), pymupdf.Point(ox + dx * s, oy + (y - 820) * s))
        shape.draw_curve(pymupdf.Point(ox + dx * s, oy + (y - 820) * s),
                         pymupdf.Point(ox + (dx + 600) * s, oy + (y - 700) * s),
                         pymupdf.Point(ox + (dx + 820) * s, oy + y * s))
    shape.finish(color=(0, 0, 0.6), width=0.4)
    # windows on north wall
    for wx in (1000, 3500, 6500, 9500):
        shape.draw_rect(R(wx, 0, 1200, T))
    shape.finish(color=(0, 0.4, 0.8), width=0.4)
    # dimension line under the plan
    dy = H + 1200
    shape.draw_line(pymupdf.Point(ox, oy + dy * s), pymupdf.Point(ox + W * s, oy + dy * s))
    for x in (0, W):
        shape.draw_line(pymupdf.Point(ox + x * s, oy + (dy - 200) * s), pymupdf.Point(ox + x * s, oy + (dy + 200) * s))
    shape.finish(color=(0.4, 0, 0), width=0.3)
    shape.commit()
    page.insert_text(pymupdf.Point(ox + W * s / 2 - 12, oy + (dy - 150) * s), "12000", fontsize=8)
    page.insert_text(pymupdf.Point(ox + 1000 * s, oy + 4000 * s), "LIVING", fontsize=9)
    page.insert_text(pymupdf.Point(ox + 7500 * s, oy + 4000 * s), "BED 1", fontsize=9)


def title_block(page, text):
    r = pymupdf.Rect(A3_LAND[0] - 150 * MM, A3_LAND[1] - 40 * MM, A3_LAND[0] - 10 * MM, A3_LAND[1] - 10 * MM)
    page.draw_rect(r, color=(0, 0, 0), width=0.8)
    page.insert_text(r.tl + (8, 20), "SAMPLE HOUSE - GROUND FLOOR PLAN", fontsize=10)
    page.insert_text(r.tl + (8, 40), text, fontsize=10)
    page.insert_text(r.tl + (8, 60), "TEST DRAWING - NOT FOR CONSTRUCTION", fontsize=7)


def main(out="sample_drawings.pdf", *flags):
    if "--rev-b" in flags:
        # Revision B of sheet 1: internal wall moved 1 m east, revision noted in title block.
        doc = pymupdf.open()
        p = doc.new_page(width=A3_LAND[0], height=A3_LAND[1])
        draw_plan(p, 100, internal_x=6000)
        title_block(p, "SCALE 1:100 @ A3   REV B")
        doc.save(out, garbage=3, deflate=True)
        print(f"wrote {out}")
        return
    doc = pymupdf.open()
    p1 = doc.new_page(width=A3_LAND[0], height=A3_LAND[1])
    draw_plan(p1, 100)
    title_block(p1, "SCALE 1:100 @ A3")

    # Drawn at 1:50 on A1, then the whole sheet reduced to A3 => factor 841/420.
    p2 = doc.new_page(width=A3_LAND[0], height=A3_LAND[1])
    draw_plan(p2, 50 * 841 / 420)
    title_block(p2, "SCALE 1:50 @ A1")

    pix = doc[0].get_pixmap(dpi=150)  # re-fetch: earlier page handles go stale
    p3 = doc.new_page(width=A3_LAND[0], height=A3_LAND[1])
    p3.insert_image(p3.rect, pixmap=pix)

    doc.save(out, garbage=3, deflate=True)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
