# Sources for measurement rules: what's relevant and how sure I am

**No clause numbers are given anywhere in this project.** I have not checked
clause numbering against the official texts, and I won't present a guessed number
as a citation. Use the "where to look" hints, then record the clause from your
licensed copy.

Confidence key: **High** = confident the document exists and is relevant.
**Medium** = confident it exists; edition/status needs checking.
**Unsure** = verify before relying on it at all.

## 1. Which document governs what

| Question | Governing source | Notes |
|---|---|---|
| *How do I measure and describe a quantity?* (units, deductions, what's included) | **Method of measurement**: ANZSMM / ASMM | This is the main source for takeoff rules. |
| *How are dimensions and scales shown on the drawing?* | **AS 1100 series** | Drawing conventions, not measurement rules. |
| *What must be built?* (extents, required elements) | **NCC** + referenced Australian Standards | The NCC does **not** prescribe how to measure quantities. It affects what you measure, e.g. waterproofing extents or fire-rated elements. |
| *What area definition applies?* | NCC definitions (compliance) / PCA Method of Measurement (leasing) / QS GFA (cost planning) | Different definitions give different numbers for the same building. Label which one an area follows. |

## 2. Methods of measurement

| Document | Publisher | Confidence | What to verify |
|---|---|---|---|
| **Australian and New Zealand Standard Method of Measurement of Building Works (ANZSMM)** | AIQS with NZIQS | **High** that it exists and is the current trans-Tasman method. **Medium** on the edition: I believe a 1st edition was released around 2018. | Current edition and amendments; section/clause numbering for each trade; the minimum-size thresholds for deducting voids and openings (deliberately **not** stated in the rules). |
| **Australian Standard Method of Measurement of Building Works (ASMM)** | AIQS with Master Builders Australia | **High** that it exists. **Medium** that the 5th edition is the latest and that it has been superseded by the ANZSMM for new work. | Whether your client or contract still specifies ASMM. Some bills of quantities do. Note that despite its name it is **not** a Standards Australia "AS" document. |
| AIQS *Australian Cost Management Manual* | AIQS | Medium | Useful for elemental classification and GFA conventions in cost planning. Not a measurement method. |

## 3. Drawing standards (AS 1100, Technical drawing)

| Part | Confidence | Relevance |
|---|---|---|
| AS 1100.101 General principles | High (exists); **edition unsure** (1992 is the one I know, which may have been amended or reissued) | Dimensioning, scales, line types. |
| AS 1100.301 Architectural drawing | High (exists); edition unsure | Architectural symbols (doors, windows), scales, conventions used when reading plans. |
| AS 1100.501 Structural engineering drawing | High (exists); edition unsure | Reading structural drawings (members, reinforcement notation). |
| AS 1100.401 Engineering survey and survey design drawing | Medium | Civil/site drawings. |

## 4. National Construction Code

| Provision | Confidence | Relevance to takeoff |
|---|---|---|
| NCC Volume One (Class 2–9), Volume Two (Class 1 and 10), Volume Three (Plumbing Code) | High | Determine required elements: fire-resistance levels, energy-efficiency (insulation, glazing), wet areas. |
| **ABCB Housing Provisions Standard** (introduced with NCC 2022 for Class 1/10 deemed-to-satisfy content) | High that it exists. Unsure of exact Part numbers for roofing and wet areas, so none are given. | Sheet/tile roofing, wet-area waterproofing, framing provisions for houses. |
| NCC **Schedule 1 Definitions** ("floor area", "storey", "fire compartment", etc.) | Medium-high for NCC 2022 structure | Use when an area is measured for compliance (e.g. compartment limits). |
| **Current edition**: NCC 2022 vs NCC 2025 | **Unsure.** NCC 2025 was planned. Its publication and adoption dates, and any state/territory variations, must be checked at ncc.abcb.gov.au. | Record the edition on every NCC-cited rule. State variations can apply. |

## 5. Design and product standards referenced in the starter rules

These affect **specification and extents**, not measurement method. All exist
(high confidence). Editions change, so record yours.

AS 3600 Concrete structures · AS 2870 Residential slabs and footings · AS 3700
Masonry structures · AS 4773 Masonry in small buildings · AS 1684 Residential
timber-framed construction · NASH Standard (steel framing) · AS 4100 Steel
structures · AS/NZS 4600 Cold-formed steel structures · AS 1562.1 Metal sheet
roof and wall cladding · AS 3740 Waterproofing of domestic wet areas ·
AS 3958.1 Ceramic tiles (installation) · AS/NZS 2589 Gypsum linings ·
AS 1905.1 Fire-resistant doorsets · Property Council of Australia Method of
Measurement (lettable areas).

## 6. Where to obtain official copies

- Standards Australia publications: buy through its licensed distribution
  channels (check standards.org.au for the current distributor) or an
  institutional subscription.
- ANZSMM / ASMM: AIQS (aiqs.com.au).
- NCC: free to read with registration at ncc.abcb.gov.au. Check the terms of use
  before reproducing any text.

## 7. Verification workflow

1. Copy the entry from `starter_rules.yaml` (same `id`) into a YAML file in your user rules
   folder (desktop: `%APPDATA%\Takeoff\rules\` on Windows; dev mode: `rules/user/`).
2. Confirm the document edition you hold; update `source.edition`.
3. Find the governing clause; set `source.clause`, `clause_verified: true`.
4. Re-read the paraphrase against the clause and fix it **in your own words**.
5. Set `verification: {status: user_verified, verified_by: <name>, verified_on: <date>}`.
6. Restart the app (or `POST /api/rules/reload`). New items cite the new version.
   Existing items keep the snapshot they were measured under. To move an item to the
   new version, use **Edit item** and re-select the same rule; the change is logged.
