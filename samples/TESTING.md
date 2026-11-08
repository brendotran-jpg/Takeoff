# Things to try (about 15 minutes)

Test drawing: a 12 m × 8 m house at 1:100 on A3, 230 mm walls, one internal wall, 2 doors, 4 windows.

## A. Explore the demo project ("Sample House", already loaded)

| Check | Expected |
|---|---|
| Item list | 7 items in 6 trades: slab 9.56 m³, ceiling 86.33 m², skirting 24.62 m, edge form 40.00 m, brick walls 102.24 m², roof 124.27 m², doors 2 no. |
| Click **Brick veneer** | 102.240 m² = 40 m × 2.7 m − 4 windows (1.2 × 1.2) shown as dashed deductions |
| Click **GF slab** | 9.564 m³ = (96 m² − 0.36 m² service void cut-out) × 0.1 m |
| Change the slab's **Depth** to 0.2 in the right panel | 19.128 m³, and the Estimate tab updates too |
| **Estimate** tab | 7 linked rows + mesh row (uses slab *area*) + pump hire (manual). Total incl. GST **$41,217.42** at depth 0.1 |
| Sheet **A-101 (A1 reduced)** → click the "1:50 @ A1" scale button | Warns that the sheet is A3 and corrects to about 1:100 |
| Sheet **A-101 (scan)** | Flagged as SCANNED: no snapping, calibrate instead |

## B. Measure something yourself

1. **+ New item** → rule `FIN-PLB-CEIL-001` → name it.
2. **Area** tool → click the 4 outer wall corners (they snap; the ring turns green) → `Enter` → **96.000 m²**.
3. **Cut-out** tool → draw a box inside → area drops by the box size.
4. **Select** → click the area → drag a corner handle → `Ctrl+Z` undoes it.
5. **+ New item** → `WD-DOOR-001` → **Count** → click each door → **2.000 no.**
6. **Calibrate** (`K`) on another sheet → click both ends of the "12000" dimension line → enter `12000`.

## C. Revisions

1. **Import PDF** → `sample_revB.pdf` (internal wall moved 1 m east).
2. **Revisions** tab → Old = A-101, New = sample_revB p1 → **Compare**: red line = old wall position, green = new.
3. **Transfer takeoff** (Move) → the takeoff now sits on Rev B and quantities are unchanged (nothing is counted twice).

## D. Export

File → **Export Excel workbook** → open it. The sheets are Dimensions → Items (SUMIFS) → Estimate (formulas).
Change a rate in Excel and the totals recalculate.

Found something wrong or awkward? Note the sheet, the item and what you clicked.
