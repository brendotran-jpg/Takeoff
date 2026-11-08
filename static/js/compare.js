// Revisions: overlay two sheets and carry takeoff across to the new revision.
import { $, S, api, esc, toast, guard, confirmBox, on } from "./core.js";
import { loadDrawings, refresh } from "./takeoff.js";

function pageOptions(sel) {
  return S.drawings.flatMap((d) => d.page_list.map((p) => {
    const v = `${d.id}:${p.page}`;
    return `<option value="${v}" ${v === sel ? "selected" : ""}>${esc(p.label || `${d.filename} p${p.page + 1}`)}${p.revision ? ` (Rev ${esc(p.revision)})` : ""}</option>`;
  })).join("");
}
export function renderCompareSelectors() {
  const a = $("cmpA").value, b = $("cmpB").value;
  $("cmpA").innerHTML = pageOptions(a);
  $("cmpB").innerHTML = pageOptions(b || (S.drawings.length > 1 ? `${S.drawings[S.drawings.length - 1].id}:0` : ""));
}
const go = guard(async () => {
  const a = $("cmpA").value, b = $("cmpB").value;
  if (!a || !b) return toast("Import at least two sheets to compare", true);
  const url = `/api/compare.png?a=${a}&b=${b}&zoom=1&dx=${+$("cmpDx").value || 0}&dy=${+$("cmpDy").value || 0}`;
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.json()).detail || "compare failed");
  const st = Object.fromEntries((r.headers.get("x-compare-stats") || "").split(",").map((kv) => kv.split("=")));
  const img = $("cmpImg");
  if (img.src.startsWith("blob:")) URL.revokeObjectURL(img.src);
  img.src = URL.createObjectURL(await r.blob());
  const total = (+st.removed_px || 0) + (+st.added_px || 0) + (+st.common_px || 0);
  $("cmpStats").textContent = total ? `changed ink: ${(((+st.removed_px) + (+st.added_px)) / total * 100).toFixed(1)}%` : "";
});
const transfer = guard(async () => {
  const [fd, fp] = $("cmpA").value.split(":").map(Number), [td, tp] = $("cmpB").value.split(":").map(Number);
  const mode = $("cmpMode").value;
  if (!(await confirmBox(mode === "move" ? "Move takeoff to the new revision?" : "Copy takeoff to the new revision?",
    mode === "move" ? "All shapes on the old sheet move to the new sheet (same position plus the offset). Quantities don't change until you edit them, so review the red/green changes and adjust the affected shapes."
                    : "Shapes are duplicated onto the new sheet. <b>Both sheets will then count</b>: use this only when the old sheet should stay in the takeoff.",
    mode === "move" ? "Move" : "Copy"))) return;
  const r = await api("/api/revisions/transfer", { method: "POST", body: { from_drawing: fd, from_page: fp, to_drawing: td, to_page: tp, mode,
    offset: [+$("cmpDx").value || 0, +$("cmpDy").value || 0] } });
  toast(`${r.shapes} shape(s) ${mode === "move" ? "moved" : "copied"}${r.scale ? " – " + r.scale : ""}`);
  await loadDrawings(); await refresh();
});
export function initCompare() {
  $("cmpGo").onclick = go;
  $("cmpTransfer").onclick = transfer;
  on("drawings", renderCompareSelectors);
}
