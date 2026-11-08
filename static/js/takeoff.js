// Takeoff workspace: drawing register, items, viewer, tools, editing, undo/redo.
import { $, S, api, esc, fmt, toast, guard, modal, confirmBox, emit, on,
         CATEGORY_LABEL, METRIC_LABEL, METRIC_UNIT, unitLabel } from "./core.js";

const SVGNS = "http://www.w3.org/2000/svg";
const INPUT_LABEL = { height_m: "Height (m)", depth_m: "Depth (m)", pitch_deg: "Pitch (°)" };
const TOOLS_FOR = { linear: ["linear", "rect"], area: ["area", "rect", "cutout"], count: ["count"] };
const DEFAULT_TOOL = { linear: "linear", area: "area", count: "count" };
const HINT = {
  select: "Click a shape to select it · drag its handles to edit · Delete removes · drag empty space to pan",
  linear: "Click points · double-click / Enter to finish · Shift = ortho · Backspace = undo point · Esc = cancel",
  area: "Click corners · double-click / Enter to close · Shift = ortho · Esc = cancel",
  rect: "Click two opposite corners",
  count: "Click each item to count it",
  cutout: "Draw a hole inside an area of the active item · Enter to finish",
  calibrate: "Click both ends of a known dimension",
};

// ================================================================ undo ====
const undoStack = [], redoStack = [];
const refs = new Map(); // shape id -> {id} shared by commands, so re-created shapes keep their history
const ref = (id) => { if (!refs.has(id)) refs.set(id, { id }); return refs.get(id); };
const rebind = (r, newId) => { refs.delete(r.id); r.id = newId; refs.set(newId, r); };
function pushCmd(cmd) { undoStack.push(cmd); if (undoStack.length > 200) undoStack.shift(); redoStack.length = 0; updUndo(); }
function updUndo() { $("undoBtn").disabled = !undoStack.length; $("redoBtn").disabled = !redoStack.length; }
const undo = guard(async () => { const c = undoStack.pop(); if (!c) return; await c.undo(); redoStack.push(c); updUndo(); await refresh(); toast(`Undo: ${c.label}`); });
const redo = guard(async () => { const c = redoStack.pop(); if (!c) return; await c.redo(); undoStack.push(c); updUndo(); await refresh(); toast(`Redo: ${c.label}`); });

const shapeBody = (s) => ({ item_id: s.item_id, drawing_id: s.drawing_id, page: s.page, points: s.points,
  holes: s.holes || [], deduction: s.sign < 0, inputs: s.inputs || {} });

async function createShape(body, label = "add shape") {
  const s = await api("/api/shapes", { method: "POST", body });
  const r = ref(s.id);
  pushCmd({ label,
    undo: async () => { await api(`/api/shapes/${r.id}`, { method: "DELETE" }); },
    redo: async () => { const n = await api("/api/shapes", { method: "POST", body }); rebind(r, n.id); } });
  return s;
}
async function deleteShape(s) {
  await api(`/api/shapes/${s.id}`, { method: "DELETE" });
  const r = ref(s.id), body = shapeBody(s);
  pushCmd({ label: "delete shape",
    undo: async () => { const n = await api("/api/shapes", { method: "POST", body }); rebind(r, n.id); },
    redo: async () => { await api(`/api/shapes/${r.id}`, { method: "DELETE" }); } });
}
async function patchShape(s, after, label = "edit shape") {
  const before = {};
  for (const k of Object.keys(after)) before[k] = k === "deduction" ? s.sign < 0 : s[k];
  await api(`/api/shapes/${s.id}`, { method: "PATCH", body: after });
  const r = ref(s.id);
  pushCmd({ label,
    undo: async () => { await api(`/api/shapes/${r.id}`, { method: "PATCH", body: before }); },
    redo: async () => { await api(`/api/shapes/${r.id}`, { method: "PATCH", body: after }); } });
}

// ============================================================ drawings ====
export async function loadDrawings() {
  S.drawings = await api("/api/drawings");
  renderTree();
  if (S.drawing && !S.drawings.find((d) => d.id === S.drawing.id)) { S.drawing = null; S.info = null; showEmpty(); }
  if (!S.drawing && S.drawings.length) await openPage(S.drawings[0].id, 0);
  if (!S.drawings.length) showEmpty();
  emit("drawings");
}
function showEmpty() { $("stage").hidden = true; $("empty").hidden = false; S.shapes = []; renderScale(); }

function renderTree() {
  const el = $("drawingTree");
  if (!S.drawings.length) { el.innerHTML = `<div class="muted small">No drawings yet.</div>`; return; }
  el.innerHTML = S.drawings.map((d) => `
    <div class="dw"><span title="${esc(d.filename)}">${esc(d.filename)}</span>
      <button class="iconbtn" data-deldw="${d.id}" title="Remove drawing and its takeoff">✕</button></div>
    ${d.page_list.map((p) => `
      <div class="pg ${S.drawing?.id === d.id && S.page === p.page ? "active" : ""}" data-d="${d.id}" data-p="${p.page}" title="Double-click to rename">
        <span class="dot ${p.mm_per_pt ? "ok" : ""}" title="${p.mm_per_pt ? "Scale set" : "Scale not set"}"></span>
        <span class="lbl">${esc(p.label || `Page ${p.page + 1}`)}${p.title ? ` – ${esc(p.title)}` : ""}</span>
        ${p.revision ? `<span class="cnt">Rev ${esc(p.revision)}</span>` : ""}
      </div>`).join("")}`).join("");
  el.querySelectorAll(".pg").forEach((row) => {
    row.onclick = () => openPage(+row.dataset.d, +row.dataset.p);
    row.ondblclick = () => renamePage(+row.dataset.d, +row.dataset.p);
  });
  el.querySelectorAll("[data-deldw]").forEach((b) => (b.onclick = guard(async (ev) => {
    ev.stopPropagation();
    const d = S.drawings.find((x) => x.id === +b.dataset.deldw);
    if (!(await confirmBox("Remove drawing?", `<b>${esc(d.filename)}</b> and every shape measured on it will be removed from the project. Items stay (with whatever quantity remains on other sheets).`, "Remove"))) return;
    await api(`/api/drawings/${d.id}`, { method: "DELETE" });
    await loadDrawings(); await refresh();
  })));
}

const renamePage = guard(async (did, page) => {
  const p = S.drawings.find((d) => d.id === did).page_list[page];
  const v = await modal({ title: "Sheet details", ok: "Save", fields: [
    { name: "label", label: "Sheet number", value: p.label, half: true },
    { name: "revision", label: "Revision", value: p.revision, half: true },
    { name: "title", label: "Sheet title", value: p.title }] });
  if (!v) return;
  await api(`/api/drawings/${did}/pages/${page}`, { method: "PATCH", body: v });
  await loadDrawings();
});

export const openPage = guard(async (did, page) => {
  S.drawing = S.drawings.find((d) => d.id === did);
  S.page = page; S.pts = []; S.selectedShape = null;
  S.info = await api(`/api/drawings/${did}/pages/${page}`);
  $("empty").hidden = true; $("stage").hidden = false;
  if (!openPage.zoomed) { fitWidth(); openPage.zoomed = true; } else layout();
  S.snapPts = [];
  api(`/api/drawings/${did}/pages/${page}/snap`).then((r) => { S.snapPts = r.points; }).catch(() => {});
  renderTree(); renderScale();
  await loadShapes();
});

// ======================================================== zoom / layout ===
function imgUrl() { return `/api/drawings/${S.drawing.id}/pages/${S.page}/image?zoom=${renderZoom()}`; }
// Render at a bucketed resolution (sharp enough, cache-friendly); CSS scales the rest.
function renderZoom() { const dpr = window.devicePixelRatio || 1; return Math.min(6, Math.max(0.5, Math.ceil(S.zoom * dpr * 2) / 2)); }
function layout() {
  if (!S.info) return;
  const { width_pt: w, height_pt: h } = S.info;
  const img = $("pageImg");
  img.style.width = `${w * S.zoom}px`; img.style.height = `${h * S.zoom}px`;
  const url = imgUrl();
  if (img.getAttribute("src") !== url) img.src = url;
  $("overlay").setAttribute("viewBox", `0 0 ${w} ${h}`);
  $("zoomLbl").textContent = `${Math.round(S.zoom * 100)}%`;
  render();
}
function setZoom(z, cx, cy) {
  if (!S.info) return;
  const v = $("viewer");
  const px = cx ?? v.clientWidth / 2, py = cy ?? v.clientHeight / 2;
  const ax = (v.scrollLeft + px - 16) / S.zoom, ay = (v.scrollTop + py - 16) / S.zoom;
  S.zoom = Math.min(5, Math.max(0.1, z));
  layout();
  v.scrollLeft = ax * S.zoom + 16 - px; v.scrollTop = ay * S.zoom + 16 - py;
}
function fitWidth() { if (S.info) { S.zoom = Math.max(0.1, ($("viewer").clientWidth - 40) / S.info.width_pt); layout(); } }

// =============================================================== scale ====
function renderScale() {
  const i = S.info, rec = i?.record;
  if (!i) { $("pageMeta").textContent = ""; $("scaleStatus").textContent = "No sheet open"; $("scaleCands").innerHTML = ""; $("stScale").textContent = "Scale: –"; return; }
  $("pageMeta").textContent = `${i.sheet_size || "Non-standard"} ${fmt(i.width_pt * 25.4 / 72, 0)}×${fmt(i.height_pt * 25.4 / 72, 0)} mm · ` +
    (i.is_scanned ? "SCANNED – no snapping" : `vector (${i.vector_paths} paths)`);
  const st = $("scaleStatus");
  if (rec?.mm_per_pt) {
    st.className = "status ok";
    st.textContent = `1:${rec.scale_detail?.effective_ratio} (${rec.scale_method})`;
    $("stScale").textContent = `Scale 1:${rec.scale_detail?.effective_ratio}`;
  } else {
    st.className = "status warn"; st.textContent = "Scale not set"; $("stScale").textContent = "Scale not set";
  }
  const warn = rec?.scale_detail?.warning;
  $("scaleWarn").hidden = !warn; $("scaleWarn").textContent = warn || "";
  $("scaleCands").innerHTML = i.scale_candidates.length
    ? `<div class="muted small">Found on sheet:</div>` + i.scale_candidates.map((c, k) =>
        `<button class="small" data-k="${k}" title="${esc(c.warning || "")}">${esc(c.match)}${c.warning ? " ⚠" : ""}</button>`).join("")
    : `<div class="muted small">No scale text found${i.has_text_layer ? "" : " (no text layer)"} – calibrate.</div>`;
  $("scaleCands").querySelectorAll("button").forEach((b) => (b.onclick = () => {
    const c = i.scale_candidates[b.dataset.k];
    setScale({ method: "stated", ratio: c.ratio, stated_sheet: c.stated_sheet });
  }));
}
const setScale = guard(async (body) => {
  const r = await api(`/api/drawings/${S.drawing.id}/pages/${S.page}/scale`, { method: "PUT", body });
  S.info.record = r;
  toast(`Scale 1:${r.scale_detail.effective_ratio}` + (r.affected_shapes ? ` – ${r.affected_shapes} shape(s) on this sheet re-measured` : ""));
  if (r.scale_detail.warning) setTimeout(() => toast(r.scale_detail.warning, true), 1200);
  renderScale();
  await loadDrawings(); await refresh();
});
const mmPerPt = () => S.info?.record?.mm_per_pt;

// =============================================================== items ====
export async function loadItems() {
  S.items = await api("/api/items");
  if (S.activeItem) S.activeItem = S.items.find((i) => i.id === S.activeItem.id) || null;
  renderItems(); renderItemPanel(); updateToolAvailability();
  emit("items");
}
function renderItems() {
  const f = $("itemFilter").value.trim().toLowerCase();
  const list = S.items.filter((i) => !f || `${i.code || ""} ${i.name} ${i.category} ${i.rule_id}`.toLowerCase().includes(f));
  if (!S.items.length) { $("itemList").innerHTML = `<div class="muted small">No items. Create one with “+ New item”, then measure.</div>`; return; }
  const groups = {};
  list.forEach((i) => (groups[i.category] ||= []).push(i));
  $("itemList").innerHTML = Object.entries(groups).map(([cat, its]) => `<div class="cat">${esc(CATEGORY_LABEL(cat))}</div>` +
    its.map((i) => `<div class="it ${S.activeItem?.id === i.id ? "active" : ""} ${S.hidden.has(i.id) ? "hid" : ""}" data-id="${i.id}"
        title="${esc(i.rule_id)} · ${i.q.shape_count} shape(s)">
      <button class="eye" data-eye="${i.id}" title="Show/hide">${S.hidden.has(i.id) ? "◌" : "●"}</button>
      <span class="sw" style="background:${i.colour}"></span>
      <span class="nm">${i.code ? `<small>${esc(i.code)}</small>` : ""}${esc(i.name)}${i.q.issues.length ? ` <span class="warnflag" title="${esc(i.q.issues.join("\n"))}">⚠</span>` : ""}</span>
      <span class="q">${fmt(i.q.quantity)} ${unitLabel(i.q.unit)}</span></div>`).join("")).join("");
  $("itemList").querySelectorAll(".it").forEach((row) => (row.onclick = (ev) => {
    if (ev.target.dataset.eye) return;
    setActiveItem(+row.dataset.id);
  }));
  $("itemList").querySelectorAll("[data-eye]").forEach((b) => (b.onclick = () => {
    const id = +b.dataset.eye;
    S.hidden.has(id) ? S.hidden.delete(id) : S.hidden.add(id);
    renderItems(); render();
  }));
}
export function setActiveItem(id) {
  S.activeItem = S.items.find((i) => i.id === id) || null;
  if (S.activeItem) S.hidden.delete(id);
  const valid = S.activeItem ? TOOLS_FOR[S.activeItem.kind] : [];
  if (!["select", "calibrate"].includes(S.tool) && !valid.includes(S.tool)) setTool(S.activeItem ? DEFAULT_TOOL[S.activeItem.kind] : "select");
  renderItems(); renderItemPanel(); updateToolAvailability(); render();
}
function inputsHTML(names, values, prefix) {
  return names.map((k) => `<label>${INPUT_LABEL[k]} <input type="number" data-${prefix}="${k}" step="0.01" min="0" value="${values?.[k] ?? ""}"></label>`).join("");
}
function renderItemPanel() {
  const it = S.activeItem;
  $("itemPanel").hidden = !it;
  $("stItem").innerHTML = it ? `<span class="sw" style="background:${it.colour}"></span> ${esc(it.name)}` : "No active item";
  if (!it) return;
  $("ipSwatch").style.background = it.colour;
  $("ipName").textContent = `${it.code ? it.code + " · " : ""}${it.name}`;
  const t = it.q.totals;
  $("ipQty").innerHTML = `<div class="main">${fmt(it.q.quantity, 3)} ${unitLabel(it.q.unit)}</div>
    <table>${Object.entries(t).filter(([k]) => k !== it.q.primary_metric).map(([k, v]) =>
      `<tr><td class="muted">${METRIC_LABEL[k]}</td><td>${fmt(v, 3)} ${METRIC_UNIT[k]}</td></tr>`).join("")}
      <tr><td class="muted">Shapes</td><td>${it.q.shape_count}</td></tr></table>`;
  $("ipIssues").hidden = !it.q.issues.length;
  $("ipIssues").textContent = it.q.issues.join(" · ");
  const req = it.rule_snapshot.required_inputs || [];
  $("ipInputs").innerHTML = inputsHTML(req, it.inputs, "ii");
  $("ipInputs").querySelectorAll("input").forEach((inp) => (inp.onchange = guard(async () => {
    const inputs = { ...it.inputs, [inp.dataset.ii]: inp.value === "" ? null : +inp.value };
    await api(`/api/items/${it.id}`, { method: "PATCH", body: { inputs } });
    await refresh();
  })));
  const r = it.rule_snapshot, src = r.source, unv = r.verification.status !== "user_verified";
  $("ipRule").innerHTML = `<b>${esc(r.id)}</b> v${r.version || 1} – ${esc(r.title)}<br>${esc(r.convention)}<br>
    ${unv ? `<span class="unv">UNVERIFIED</span> – ` : ""}${esc(src.document)}${src.edition ? ", " + esc(src.edition) : ""}${src.clause ? ", cl. " + esc(src.clause) : src.section_hint ? ", " + esc(src.section_hint) + " (clause TBC)" : ""}`;
}

function ruleOptions(filterKind) {
  return S.rules.filter((r) => r.measure_type !== "reference" && (!filterKind || r.measure_type === filterKind))
    .sort((a, b) => a.category.localeCompare(b.category) || a.id.localeCompare(b.id))
    .map((r) => [r.id, `${CATEGORY_LABEL(r.category)} · ${r.id} – ${r.title} [${unitLabel(r.unit)}]${r.verification.status !== "user_verified" ? " *" : ""}`]);
}
export const newItem = guard(async () => {
  const step1 = await modal({ title: "New takeoff item – 1 of 2", ok: "Next",
    note: "The measurement rule fixes how the item is measured (line, area or count), its unit, and the standard it cites. * = citation not yet verified.",
    fields: [{ name: "rule_id", label: "Measurement rule", type: "select", options: ruleOptions(), value: S.activeItem?.rule_id }] });
  if (!step1) return;
  const rule = S.rules.find((r) => r.id === step1.rule_id);
  const req = rule.required_inputs || [];
  const v = await modal({ title: "New takeoff item – 2 of 2", ok: "Create item",
    note: `<b>${esc(rule.title)}</b> – measured as ${rule.measure_type}, unit ${unitLabel(rule.unit)}.`,
    fields: [
      { name: "name", label: "Description", value: rule.title, required: true },
      { name: "code", label: "Code", half: true, placeholder: "e.g. 03.010" },
      { name: "category", label: "Trade / category", type: "select", options: S.categories.map((c) => [c, CATEGORY_LABEL(c)]), value: rule.category, half: true },
      ...req.map((k) => ({ name: k, label: INPUT_LABEL[k], type: "number", step: "0.001", half: true })),
      { name: "colour", label: "Colour", type: "color", value: nextColour(), half: true },
    ] });
  if (!v) return;
  const inputs = Object.fromEntries(req.map((k) => [k, v[k]]));
  const it = await api("/api/items", { method: "POST", body: { rule_id: rule.id, name: v.name, code: v.code || null, category: v.category, colour: v.colour, inputs } });
  await loadItems();
  setActiveItem(it.id);
  setTool(DEFAULT_TOOL[it.kind]);
  if (req.some((k) => v[k] == null)) toast(`Enter ${req.map((k) => INPUT_LABEL[k]).join(", ")} in the item panel, or the quantity can't be calculated.`, true);
});
function nextColour() {
  const pal = ["#0ea5e9", "#dc2626", "#16a34a", "#d97706", "#9333ea", "#0891b2", "#db2777", "#65a30d", "#2563eb", "#ea580c", "#7c3aed", "#be123c"];
  return pal[S.items.length % pal.length];
}
const editItem = guard(async () => {
  const it = S.activeItem; if (!it) return;
  const v = await modal({ title: "Edit item", ok: "Save", fields: [
    { name: "name", label: "Description", value: it.name, required: true },
    { name: "code", label: "Code", value: it.code, half: true },
    { name: "category", label: "Trade / category", type: "select", options: S.categories.map((c) => [c, CATEGORY_LABEL(c)]), value: it.category, half: true },
    { name: "rule_id", label: "Measurement rule (same measure type; re-selecting the current rule picks up its latest version)", type: "select", options: ruleOptions(it.kind), value: it.rule_id },
    { name: "colour", label: "Colour", type: "color", value: it.colour, half: true },
    { name: "notes", label: "Notes", type: "textarea", value: it.notes },
  ] });
  if (!v) return;
  await api(`/api/items/${it.id}`, { method: "PATCH", body: { ...v, code: v.code || null, notes: v.notes || null } });
  await refresh();
});
const deleteItem = guard(async () => {
  const it = S.activeItem; if (!it) return;
  if (!(await confirmBox("Delete item?", `<b>${esc(it.name)}</b> and its ${it.q.shape_count} shape(s) will be deleted. Estimate rows linked to it keep their last quantity as a fixed value. This can't be undone.`))) return;
  await api(`/api/items/${it.id}`, { method: "DELETE" });
  S.activeItem = null;
  await refresh();
});

// ============================================================== shapes ====
async function loadShapes() {
  if (!S.drawing) { S.shapes = []; return render(); }
  S.shapes = await api(`/api/shapes?drawing_id=${S.drawing.id}&page=${S.page}`);
  if (S.selectedShape) S.selectedShape = S.shapes.find((s) => s.id === S.selectedShape.id) || null;
  render(); renderShapePanel();
}
export async function refresh() { await Promise.all([loadItems(), loadShapes()]); }

function renderShapePanel() {
  const s = S.selectedShape;
  $("shapePanel").hidden = !s;
  if (!s) return;
  const it = S.items.find((i) => i.id === s.item_id);
  const m = s.metrics || {};
  $("spInfo").innerHTML = `<div><span class="sw" style="background:${it?.colour}"></span> ${esc(it?.name)}</div>` +
    (Object.keys(m).length ? Object.entries(m).map(([k, v]) => `<div>${METRIC_LABEL[k]}: <b>${fmt(v, 3)} ${METRIC_UNIT[k]}</b></div>`).join("")
      : `<div class="warnbox">No quantity – check the scale and item inputs.</div>`) +
    (s.holes?.length ? `<div class="muted">${s.holes.length} cut-out(s)</div>` : "");
  $("spDeduct").checked = s.sign < 0;
  const req = it?.rule_snapshot.required_inputs || [];
  $("spInputs").innerHTML = req.length ? `<div class="muted small" style="width:100%">Override for this shape only (blank = item value):</div>` + inputsHTML(req, s.inputs, "si") : "";
  $("spInputs").querySelectorAll("input").forEach((inp) => (inp.onchange = guard(async () => {
    const inputs = { ...s.inputs, [inp.dataset.si]: inp.value === "" ? null : +inp.value };
    await patchShape(s, { inputs }, "shape input");
    await refresh();
  })));
}

// ============================================================== render ====
const el = (tag, attrs, parent) => { const e = document.createElementNS(SVGNS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent?.appendChild(e); return e; };
const ptsStr = (pts) => pts.map((p) => `${p[0]},${p[1]}`).join(" ");
const pathD = (outer, holes = []) => [outer, ...holes].map((r) => "M" + r.map((p) => `${p[0]} ${p[1]}`).join("L") + "Z").join("");

export function render() {
  const svg = $("overlay");
  if (!svg) return;
  svg.innerHTML = "";
  if (!S.info) return;
  const k = 1 / S.zoom, sw = 1.6 * k;
  const items = new Map(S.items.map((i) => [i.id, i]));
  for (const s of S.shapes) {
    const it = items.get(s.item_id);
    if (!it || S.hidden.has(it.id)) continue;
    const sel = S.selectedShape?.id === s.id;
    const act = S.activeItem?.id === it.id;
    const dash = s.sign < 0 ? `${6 * k},${4 * k}` : "none";
    const common = { class: "shape", "data-sid": s.id, stroke: it.colour, "stroke-dasharray": dash };
    let node;
    if (it.kind === "area") {
      node = el("path", { ...common, d: pathD(s.points, s.holes), "fill-rule": "evenodd", fill: s.sign < 0 ? "none" : it.colour,
        "fill-opacity": sel ? 0.4 : act ? 0.25 : 0.15, "stroke-width": sel ? sw * 2 : sw }, svg);
      if (s.sign < 0) el("path", { d: pathD(s.points, s.holes), fill: `url(#hatch)`, "pointer-events": "none" }, svg);
    } else if (it.kind === "linear") {
      el("polyline", { points: ptsStr(s.points), fill: "none", stroke: "transparent", "stroke-width": 10 * k, class: "shape", "data-sid": s.id }, svg); // fat hit target
      node = el("polyline", { ...common, points: ptsStr(s.points), fill: "none", "stroke-width": sel ? sw * 3 : sw * (act ? 2 : 1.5), "pointer-events": "none" }, svg);
    } else {
      for (const [x, y] of s.points) {
        el("circle", { ...common, cx: x, cy: y, r: (sel ? 7 : 5.5) * k, fill: it.colour, "fill-opacity": 0.85, stroke: "#fff", "stroke-width": 1.2 * k }, svg);
        if (s.sign < 0) el("line", { x1: x - 4 * k, y1: y, x2: x + 4 * k, y2: y, stroke: "#fff", "stroke-width": 1.5 * k, "pointer-events": "none" }, svg);
      }
    }
    if (node) el("title", {}, node).textContent = `${it.name}${s.sign < 0 ? " (deduction)" : ""}`;
  }
  // deduction hatch pattern
  const defs = el("defs", {}, svg);
  const pat = el("pattern", { id: "hatch", width: 6 * k, height: 6 * k, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
  el("line", { x1: 0, y1: 0, x2: 0, y2: 6 * k, stroke: "#dc2626", "stroke-width": 1 * k, "stroke-opacity": 0.6 }, pat);

  // vertex handles for the selected shape
  const s = S.selectedShape;
  if (s && S.tool === "select" && !S.hidden.has(s.item_id)) {
    s.points.forEach(([x, y], i) => el("rect", { class: "handle", "data-vi": i, x: x - 4 * k, y: y - 4 * k, width: 8 * k, height: 8 * k,
      fill: "#fff", stroke: "#1f6feb", "stroke-width": 1.5 * k }, svg));
  }
  // in-progress geometry
  const live = "#e11d48";
  let cur = S.cursor && !["count", "select"].includes(S.tool) ? [...S.pts, S.cursor] : S.pts;
  if (S.tool === "rect" && S.pts.length === 1 && S.cursor) cur = rectPts(S.pts[0], S.cursor);
  if (cur.length) {
    const closed = ["area", "cutout", "rect"].includes(S.tool);
    if (closed && cur.length > 2) el("polygon", { points: ptsStr(cur), fill: live, "fill-opacity": 0.12, stroke: live, "stroke-width": sw, "pointer-events": "none" }, svg);
    else el("polyline", { points: ptsStr(cur), fill: "none", stroke: live, "stroke-width": sw, "pointer-events": "none" }, svg);
    S.pts.forEach(([x, y]) => el("circle", { cx: x, cy: y, r: 3 * k, fill: live, "pointer-events": "none" }, svg));
  }
  if (S.cursor && S.tool !== "select") {
    el("circle", { cx: S.cursor[0], cy: S.cursor[1], r: 6 * k, fill: "none", stroke: S.cursor.snapped ? "#16a34a" : live, "stroke-width": 1.2 * k, "pointer-events": "none" }, svg);
  }
  renderLive();
}

// ============================================================== tools =====
function updateToolAvailability() {
  const kind = S.activeItem?.kind;
  document.querySelectorAll("#tools button").forEach((b) => {
    const t = b.dataset.tool;
    b.disabled = !["select", "calibrate"].includes(t) && !(kind && TOOLS_FOR[kind].includes(t));
    b.classList.toggle("active", t === S.tool);
  });
}
export function setTool(t) {
  if (!["select", "calibrate"].includes(t) && !(S.activeItem && TOOLS_FOR[S.activeItem.kind].includes(t))) {
    if (!S.activeItem) toast("Select or create a takeoff item first", true);
    return;
  }
  S.tool = t; S.pts = [];
  $("viewer").classList.toggle("drawing", t !== "select");
  $("stHint").textContent = HINT[t];
  updateToolAvailability(); render();
}
function svgPoint(ev) {
  const svg = $("overlay"), p = svg.createSVGPoint();
  p.x = ev.clientX; p.y = ev.clientY;
  const q = p.matrixTransform(svg.getScreenCTM().inverse());
  return [q.x, q.y];
}
function resolvePoint(ev, exclude) {
  let p = svgPoint(ev);
  const last = S.pts[S.pts.length - 1];
  if (ev.shiftKey && last) {
    p = Math.abs(p[0] - last[0]) > Math.abs(p[1] - last[1]) ? [p[0], last[1]] : [last[0], p[1]];
  } else if ($("snapTgl").checked && !S.info.is_scanned) {
    const tol = 9 / S.zoom;
    let best = null, bd = tol;
    const test = (c) => { const d = Math.hypot(c[0] - p[0], c[1] - p[1]); if (d < bd) { bd = d; best = c; } };
    S.snapPts.forEach(test);
    S.shapes.forEach((s) => s !== exclude && s.points.forEach(test)); // snap to existing takeoff too
    if (best) { p = [best[0], best[1]]; p.snapped = true; }
  }
  return p;
}
const rectPts = (a, b) => [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]];
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const polyLen = (pts) => pts.slice(1).reduce((s, p, i) => s + dist(p, pts[i]), 0);
const polyArea = (pts) => Math.abs(pts.reduce((s, p, i) => { const q = pts[(i + 1) % pts.length]; return s + p[0] * q[1] - q[0] * p[1]; }, 0)) / 2;
const dedupe = (pts) => pts.filter((p, i) => i === 0 || dist(p, pts[i - 1]) > 0.01);
function pointInPoly([x, y], poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function renderLive() {
  const k = mmPerPt(), live = $("stLive");
  let pts = S.cursor && S.tool !== "count" ? [...S.pts, S.cursor] : S.pts;
  if (S.tool === "rect" && S.pts.length === 1 && S.cursor) pts = rectPts(S.pts[0], S.cursor);
  if (!pts.length || S.tool === "select" || S.tool === "count") { live.textContent = ""; return; }
  if (S.tool === "calibrate") { live.textContent = `${fmt(polyLen(pts), 1)} pt`; return; }
  if (!k) { live.textContent = "Set the scale first"; return; }
  const m = k / 1000;
  if (S.tool === "linear") live.textContent = `Length ${fmt(polyLen(pts) * m, 3)} m`;
  else if (pts.length > 2) live.textContent = `Area ${fmt(polyArea(pts) * m * m, 3)} m² · perimeter ${fmt((polyLen(pts) + dist(pts[0], pts[pts.length - 1])) * m, 3)} m`;
}

const finish = guard(async () => {
  const pts = dedupe(S.pts);
  const t = S.tool, it = S.activeItem;
  S.pts = []; render();
  if (!it) return;
  const base = { item_id: it.id, drawing_id: S.drawing.id, page: S.page, deduction: $("deductTgl").checked };
  if (t === "linear" && pts.length >= 2) await createShape({ ...base, points: pts });
  else if (t === "area" && pts.length >= 3) await createShape({ ...base, points: pts });
  else if (t === "cutout" && pts.length >= 3) {
    const target = [S.selectedShape, ...S.shapes].find((s) => s && s.item_id === it.id && pts.every((p) => pointInPoly(p, s.points)));
    if (!target) throw new Error("Draw the cut-out wholly inside an area shape of the active item");
    await patchShape(target, { holes: [...(target.holes || []), pts] }, "cut-out");
    toast("Cut-out added");
  } else return;
  await refresh();
});

const onCanvasClick = guard(async (ev) => {
  if (!S.info || S.tool === "select" || onCanvasClick.suppress) return;
  const needsScale = ["linear", "area", "rect", "cutout"].includes(S.tool);
  if (needsScale && !mmPerPt()) throw new Error("Set or calibrate this sheet's scale before measuring lengths or areas");
  const p = resolvePoint(ev);
  if (S.tool === "count") {
    await createShape({ item_id: S.activeItem.id, drawing_id: S.drawing.id, page: S.page, points: [p], deduction: $("deductTgl").checked }, "count");
    return refresh();
  }
  if (S.tool === "rect") {
    if (!S.pts.length) { S.pts = [p]; return render(); }
    const r = rectPts(S.pts[0], p); S.pts = []; render();
    if (polyArea(r) < 1) return;
    const pts = S.activeItem.kind === "linear" ? [...r, r[0]] : r;
    await createShape({ item_id: S.activeItem.id, drawing_id: S.drawing.id, page: S.page, points: pts, deduction: $("deductTgl").checked }, "rectangle");
    return refresh();
  }
  S.pts.push(p);
  if (S.tool === "calibrate" && S.pts.length === 2) {
    const [p1, p2] = S.pts;
    S.pts = []; render();
    const v = await modal({ title: "Calibrate scale", ok: "Set scale",
      note: `Picked ${fmt(dist(p1, p2), 1)} pt on the sheet. Enter the real length of that dimension. Use a long dimension for accuracy, ideally one that's written on the drawing.`,
      fields: [{ name: "mm", label: "Known length (mm)", type: "number", step: "any", required: true }] });
    if (v?.mm > 0) await setScale({ method: "calibrated", p1, p2, real_length_mm: v.mm });
    return;
  }
  render();
});

// ---------------------------------------------------- select / drag / pan --
function wireCanvas() {
  const svg = $("overlay"), viewer = $("viewer");
  let drag = null, pan = null;

  viewer.addEventListener("pointerdown", (ev) => {
    const handle = ev.target.closest?.(".handle");
    if (ev.button === 0 && handle && S.selectedShape) {
      drag = { s: S.selectedShape, i: +handle.dataset.vi, orig: S.selectedShape.points.map((p) => [...p]) };
      svg.setPointerCapture(ev.pointerId); ev.preventDefault(); return;
    }
    const onShape = ev.target.closest?.(".shape");
    if (ev.button === 1 || (ev.button === 0 && S.tool === "select" && !onShape) || (ev.button === 0 && ev.altKey)) {
      pan = { x: ev.clientX, y: ev.clientY, sl: viewer.scrollLeft, st: viewer.scrollTop, moved: false };
      viewer.classList.add("panning"); viewer.setPointerCapture(ev.pointerId); ev.preventDefault();
    }
  });
  viewer.addEventListener("pointermove", (ev) => {
    if (pan) {
      const dx = ev.clientX - pan.x, dy = ev.clientY - pan.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) pan.moved = true;
      viewer.scrollLeft = pan.sl - dx; viewer.scrollTop = pan.st - dy; return;
    }
    if (drag) {
      const p = resolvePoint(ev, drag.s);
      drag.s.points[drag.i] = [p[0], p[1]];
      const kind = S.items.find((i) => i.id === drag.s.item_id)?.kind;
      if (kind === "linear" && drag.s.points.length > 2 && dist(drag.orig[0], drag.orig[drag.orig.length - 1]) < 0.01) {
        // closed polyline (e.g. from Rect): keep first and last vertex together
        if (drag.i === 0) drag.s.points[drag.s.points.length - 1] = [p[0], p[1]];
        if (drag.i === drag.s.points.length - 1) drag.s.points[0] = [p[0], p[1]];
      }
      render(); return;
    }
    if (S.info && S.tool !== "select" && ev.target.closest?.("#stage")) { S.cursor = resolvePoint(ev); render(); }
  });
  viewer.addEventListener("pointerup", guard(async (ev) => {
    if (pan) {
      viewer.classList.remove("panning");
      const wasClick = !pan.moved; pan = null;
      if (wasClick && S.tool === "select" && ev.button === 0) { S.selectedShape = null; render(); renderShapePanel(); }
      onCanvasClick.suppress = !wasClick; setTimeout(() => (onCanvasClick.suppress = false), 0);
      return;
    }
    if (drag) {
      const d = drag; drag = null;
      const after = d.s.points.map((p) => [...p]);
      if (after.every((p, i) => dist(p, d.orig[i]) < 0.01)) return;
      d.s.points = d.orig; // keep local state = server state until the patch succeeds
      try { await patchShape(d.s, { points: after }, "move vertex"); } finally { await refresh(); }
    }
  }));
  svg.addEventListener("click", (ev) => {
    if (S.tool === "select") {
      const t = ev.target.closest(".shape");
      if (!t) return;
      S.selectedShape = S.shapes.find((s) => s.id === +t.dataset.sid) || null;
      if (S.selectedShape && S.activeItem?.id !== S.selectedShape.item_id) setActiveItem(S.selectedShape.item_id);
      render(); renderShapePanel(); return;
    }
    onCanvasClick(ev);
  });
  svg.addEventListener("dblclick", (ev) => { ev.preventDefault(); if (["linear", "area", "cutout"].includes(S.tool)) finish(); });
  viewer.addEventListener("pointerleave", () => { S.cursor = null; render(); });
  viewer.addEventListener("wheel", (ev) => {
    if (!S.info || !(ev.ctrlKey || ev.metaKey)) return;
    ev.preventDefault();
    const r = viewer.getBoundingClientRect();
    setZoom(S.zoom * (ev.deltaY < 0 ? 1.15 : 1 / 1.15), ev.clientX - r.left, ev.clientY - r.top);
  }, { passive: false });
}

function onKey(ev) {
  if (!document.getElementById("tab-takeoff").classList.contains("active")) return;
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName) || $("modal").open) return;
  const ctrl = ev.ctrlKey || ev.metaKey, key = ev.key.toLowerCase();
  if (ctrl && key === "z" && !ev.shiftKey) { ev.preventDefault(); return undo(); }
  if (ctrl && (key === "y" || (key === "z" && ev.shiftKey))) { ev.preventDefault(); return redo(); }
  if (ctrl) return;
  if (ev.key === "Escape") { if (S.pts.length) S.pts = []; else if (S.selectedShape) { S.selectedShape = null; renderShapePanel(); } else setTool("select"); render(); }
  else if (ev.key === "Enter") finish();
  else if (ev.key === "Backspace" && S.pts.length) { S.pts.pop(); render(); ev.preventDefault(); }
  else if ((ev.key === "Delete" || ev.key === "Backspace") && S.selectedShape) { ev.preventDefault(); removeSelected(); }
  else if (key === "+" || key === "=") setZoom(S.zoom * 1.25);
  else if (key === "-") setZoom(S.zoom / 1.25);
  else if (key === "f") fitWidth();
  else {
    const t = { s: "select", l: "linear", a: "area", r: "rect", c: "count", x: "cutout", k: "calibrate" }[key];
    if (t) setTool(t);
  }
}
const removeSelected = guard(async () => {
  const s = S.selectedShape; if (!s) return;
  await deleteShape(s); S.selectedShape = null; await refresh(); renderShapePanel();
});

export function initTakeoff() {
  wireCanvas();
  document.addEventListener("keydown", onKey);
  document.querySelectorAll("#tools button").forEach((b) => (b.onclick = () => setTool(b.dataset.tool)));
  $("undoBtn").onclick = undo; $("redoBtn").onclick = redo;
  $("zoomIn").onclick = () => setZoom(S.zoom * 1.25);
  $("zoomOut").onclick = () => setZoom(S.zoom / 1.25);
  $("zoomFit").onclick = fitWidth;
  $("newItemBtn").onclick = newItem;
  $("itemFilter").oninput = renderItems;
  $("ipEdit").onclick = editItem; $("ipDelete").onclick = deleteItem;
  $("spDelete").onclick = removeSelected;
  $("spDeduct").onchange = guard(async (ev) => { await patchShape(S.selectedShape, { deduction: ev.target.checked }, "toggle deduction"); await refresh(); });
  $("setRatio").onclick = () => {
    const n = parseFloat($("ratioIn").value);
    if (!(n > 0)) return toast("Enter the scale denominator, e.g. 100 for 1:100", true);
    if (S.drawing) setScale({ method: "stated", ratio: n, stated_sheet: $("sheetIn").value || null });
  };
  window.addEventListener("resize", () => render());
  on("project", () => { undoStack.length = redoStack.length = 0; refs.clear(); updUndo(); S.drawing = null; S.info = null; S.activeItem = null; S.selectedShape = null; S.hidden.clear(); openPage.zoomed = false; });
  setTool("select"); updUndo();
}
