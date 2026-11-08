// Estimate workbook: sections, rows linked live to takeoff items, rate build-up, margins, GST.
import { $, S, api, esc, fmt, money, toast, guard, modal, confirmBox, on, METRIC_LABEL, unitLabel } from "./core.js";

let E = null;

export const loadEstimate = guard(async () => {
  E = await api("/api/estimate");
  renderEstimate();
});

const num = (v, d = 2) => (v == null || v === "" ? "" : Number(v).toFixed(d).replace(/\.?0+$/, "") || "0");
const inp = (key, value, type = "text", extra = "") =>
  `<input data-key="${key}" type="${type}" value="${esc(value ?? "")}" ${type === "number" ? 'step="any"' : ""} ${extra}>`;

function renderEstimate() {
  const t = $("estTable");
  if (!E) return;
  const focusKey = document.activeElement?.dataset?.key;
  const itemOpts = (sel) => `<option value="">— manual —</option>` + S.items.map((i) =>
    `<option value="${i.id}" ${i.id === sel ? "selected" : ""}>${esc((i.code ? i.code + " " : "") + i.name)} (${fmt(i.q.quantity)} ${unitLabel(i.q.unit)})</option>`).join("");
  const metricOpts = (r) => {
    const it = S.items.find((i) => i.id === r.item_id);
    if (!it) return "";
    const keys = Object.keys(it.q.totals);
    return `<option value="">Primary (${METRIC_LABEL[it.q.primary_metric]})</option>` + keys.filter((k) => k !== it.q.primary_metric)
      .map((k) => `<option value="${k}" ${r.item_metric === k ? "selected" : ""}>${METRIC_LABEL[k]}</option>`).join("");
  };
  let h = `<thead><tr><th style="width:70px">Code</th><th>Description</th><th style="width:220px">Linked takeoff item</th><th style="width:120px">Metric</th>
    <th style="width:60px">Factor</th><th style="width:90px">Qty</th><th style="width:50px">Unit</th><th style="width:60px">Waste %</th>
    <th style="width:85px">Labour</th><th style="width:85px">Material</th><th style="width:85px">Plant</th><th style="width:85px">Subcon.</th>
    <th style="width:85px">Rate</th><th style="width:110px">Total</th><th style="width:30px"></th></tr></thead><tbody>`;
  if (!E.sections.length) h += `<tr><td colspan="15" class="muted" style="padding:16px">No sections yet. Add a section, or use “Add rows from takeoff items” to build one per trade.</td></tr>`;
  for (const sec of E.sections) {
    h += `<tr class="sec"><td></td><td colspan="11">${inp(`s${sec.id}:name`, sec.name)}</td>
      <td colspan="2"><button class="small" data-addrow="${sec.id}">+ Row</button></td>
      <td><button class="iconbtn" data-delsec="${sec.id}" title="Delete section">✕</button></td></tr>`;
    for (const r of sec.rows) {
      const linked = r.item_id != null;
      h += `<tr data-row="${r.id}">
        <td>${inp(`r${r.id}:code`, r.code)}</td>
        <td>${inp(`r${r.id}:description`, r.description)}</td>
        <td><select data-key="r${r.id}:item_id">${itemOpts(r.item_id)}</select></td>
        <td>${linked ? `<select data-key="r${r.id}:item_metric">${metricOpts(r)}</select>` : ""}</td>
        <td>${linked ? inp(`r${r.id}:factor`, num(r.factor, 4), "number") : ""}</td>
        <td class="n">${linked ? `<span class="linked" title="Live from takeoff">${fmt(r.qty, 3)}</span>` : inp(`r${r.id}:manual_qty`, num(r.manual_qty, 3), "number")}
          ${r.issue ? `<div class="issue small">${esc(r.issue)}</div>` : ""}</td>
        <td>${inp(`r${r.id}:unit`, r.unit ? unitLabel(r.unit) : "", "text", `placeholder="${linked ? esc(unitLabel(r.unit || "")) : ""}"`)}</td>
        <td>${inp(`r${r.id}:waste_pct`, num(r.waste_pct), "number")}</td>
        <td>${inp(`r${r.id}:labour`, num(r.labour), "number")}</td>
        <td>${inp(`r${r.id}:material`, num(r.material), "number")}</td>
        <td>${inp(`r${r.id}:plant`, num(r.plant), "number")}</td>
        <td>${inp(`r${r.id}:subcontract`, num(r.subcontract), "number")}</td>
        <td class="n">${money(r.rate)}</td>
        <td class="n"><b>${money(r.total)}</b></td>
        <td><button class="iconbtn" data-delrow="${r.id}" title="Delete row">✕</button></td></tr>`;
    }
    h += `<tr class="sub"><td></td><td colspan="12">Subtotal – ${esc(sec.name)}</td><td class="n">${money(sec.subtotal)}</td><td></td></tr>`;
  }
  const s = E.summary;
  const pctRow = (label, key, val, amt) => `<tr class="sum"><td></td><td colspan="10">${label}</td>
    <td colspan="2"><div class="row" style="margin:0;justify-content:flex-end">${inp(`m:${key}`, num(val), "number", 'style="width:70px"')} %</div></td>
    <td class="n">${money(amt)}</td><td></td></tr>`;
  h += `</tbody><tfoot>
    <tr class="sum"><td></td><td colspan="12">Subtotal (all sections)</td><td class="n">${money(s.subtotal)}</td><td></td></tr>
    ${pctRow("Contingency (on subtotal)", "contingency_pct", s.contingency_pct, s.contingency)}
    ${pctRow("Margin (on subtotal + contingency)", "margin_pct", s.margin_pct, s.margin)}
    <tr class="sum"><td></td><td colspan="12">Total excl. GST</td><td class="n">${money(s.total_ex_gst)}</td><td></td></tr>
    ${pctRow("GST", "gst_pct", s.gst_pct, s.gst)}
    <tr class="grand"><td></td><td colspan="12">TOTAL incl. GST</td><td class="n">${money(s.total_inc_gst)}</td><td></td></tr></tfoot>`;
  t.innerHTML = h;
  if (focusKey) {
    const f = t.querySelector(`[data-key="${CSS.escape(focusKey)}"]`);
    if (f) { f.focus(); if (f.select) f.select(); }
  }
}

const UNIT_IN = { "m²": "m2", "m³": "m3" };
const onChange = guard(async (ev) => {
  const key = ev.target.dataset.key;
  if (!key) return;
  const [who, field] = key.split(":");
  const raw = ev.target.value;
  if (who === "m") {
    await api("/api/project/meta", { method: "PATCH", body: { [field]: raw === "" ? 0 : +raw } });
  } else if (who[0] === "s") {
    if (!raw.trim()) return loadEstimate();
    await api(`/api/estimate/sections/${who.slice(1)}`, { method: "PATCH", body: { name: raw } });
  } else {
    const id = who.slice(1);
    let body;
    if (field === "item_id") body = raw === "" ? { unlink: true } : { item_id: +raw, item_metric: "" };
    else if (["factor", "manual_qty", "waste_pct", "labour", "material", "plant", "subcontract"].includes(field)) body = { [field]: raw === "" ? 0 : +raw };
    else if (field === "unit") body = { unit: UNIT_IN[raw] || raw };
    else body = { [field]: raw };
    await api(`/api/estimate/rows/${id}`, { method: "PATCH", body });
  }
  await loadEstimate();
});

export function initEstimate() {
  const t = $("estTable");
  t.addEventListener("change", onChange);
  t.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && ev.target.tagName === "INPUT") ev.target.blur(); });
  t.addEventListener("click", guard(async (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    if (b.dataset.addrow) {
      await api("/api/estimate/rows", { method: "POST", body: { section_id: +b.dataset.addrow, description: "New row" } });
    } else if (b.dataset.delrow) {
      await api(`/api/estimate/rows/${b.dataset.delrow}`, { method: "DELETE" });
    } else if (b.dataset.delsec) {
      const sec = E.sections.find((s) => s.id === +b.dataset.delsec);
      if (sec.rows.length && !(await confirmBox("Delete section?", `“${esc(sec.name)}” and its ${sec.rows.length} row(s) will be deleted.`))) return;
      await api(`/api/estimate/sections/${sec.id}`, { method: "DELETE" });
    } else return;
    await loadEstimate();
  }));
  $("addSection").onclick = guard(async () => {
    const v = await modal({ title: "New section", ok: "Add", fields: [{ name: "name", label: "Section / trade name", required: true }] });
    if (!v) return;
    await api("/api/estimate/sections", { method: "POST", body: { name: v.name } });
    await loadEstimate();
  });
  $("fromItems").onclick = guard(async () => {
    const r = await api("/api/estimate/from-items", { method: "POST" });
    toast(r.added ? `Added ${r.added} linked row(s)` : "Every takeoff item is already in the estimate");
    await loadEstimate();
  });
  on("items", () => { if ($("tab-estimate").classList.contains("active")) loadEstimate(); });
}
