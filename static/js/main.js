// App shell: project file menu, tabs, import/export, desktop bridge.
import { $, S, api, esc, toast, guard, modal, bridge, emit } from "./core.js";
import { initTakeoff, loadDrawings, refresh, render } from "./takeoff.js";
import { initEstimate, loadEstimate } from "./estimate.js";
import { initCompare, renderCompareSelectors } from "./compare.js";

async function loadProject() {
  S.project = await api("/api/project");
  S.categories = S.project.categories;
  $("projName").textContent = `${S.project.meta.name} — ${S.project.file}`;
  $("projName").title = S.project.path;
  document.title = `${S.project.meta.name} – Takeoff`;
  $("recentList").innerHTML = S.project.recent.length
    ? `<hr><div class="muted small">Recent</div>` + S.project.recent.slice(0, 6).map((p) =>
        `<button data-recent="${esc(p)}" title="${esc(p)}">${esc(p.split(/[\\/]/).pop())}</button>`).join("")
    : "";
  $("recentList").querySelectorAll("[data-recent]").forEach((b) => (b.onclick = () => openPath(b.dataset.recent)));
}
async function reloadAll() {
  emit("project");
  await loadProject();
  await loadDrawings();
  await refresh();
  renderCompareSelectors();
  if ($("tab-estimate").classList.contains("active")) await loadEstimate();
}

const openPath = guard(async (path) => {
  await api("/api/project/open", { method: "POST", body: { path } });
  await reloadAll(); toast("Project opened");
});

// ------------------------------------------------------------ file menu ---
const projDir = () => S.project.projects_dir;
const sep = () => (projDir().includes("\\") ? "\\" : "/");
const actions = {
  new: guard(async () => {
    let path, name;
    if (bridge.on) {
      path = await bridge.call("save_project_dialog", "New project.qto");
      if (!path) return;
      name = path.split(/[\\/]/).pop().replace(/\.qto$/i, "");
    } else {
      const v = await modal({ title: "New project", ok: "Create", note: `Saved in ${esc(projDir())}`,
        fields: [{ name: "name", label: "Project name", required: true }] });
      if (!v) return;
      name = v.name; path = projDir() + sep() + v.name.replace(/[^\w\- ]+/g, "") + ".qto";
    }
    await api("/api/project/new", { method: "POST", body: { path, name } });
    await reloadAll(); toast("New project created");
  }),
  open: guard(async () => {
    if (bridge.on) {
      const path = await bridge.call("open_project_dialog");
      if (path) await openPath(path);
      return;
    }
    const v = await modal({ title: "Open project", ok: "Open", note: `Path to a .qto file inside ${esc(projDir())}`,
      fields: [{ name: "path", label: "Project file", value: S.project.path, required: true }] });
    if (v) await openPath(v.path);
  }),
  saveas: guard(async () => {
    let path;
    if (bridge.on) path = await bridge.call("save_project_dialog", S.project.file);
    else {
      const v = await modal({ title: "Save project as", ok: "Save", fields: [{ name: "path", label: "New file path", value: projDir() + sep() + "copy of " + S.project.file, required: true }] });
      path = v?.path;
    }
    if (!path) return;
    await api("/api/project/save-as", { method: "POST", body: { path } });
    await reloadAll(); toast("Saved – now working in the new file");
  }),
  import: guard(async () => {
    if (bridge.on) {
      const paths = await bridge.call("open_pdf_dialog");
      if (!paths?.length) return;
      const r = await api("/api/drawings/import", { method: "POST", body: { paths } });
      toast(`Imported ${r.length} drawing(s)`);
      await loadDrawings();
    } else $("uploadInput").click();
  }),
  xlsx: guard(async () => exportFile("xlsx")),
  csv: guard(async () => exportFile("csv")),
  props: guard(async () => {
    const m = S.project.meta;
    const v = await modal({ title: "Project properties", ok: "Save", fields: [
      { name: "name", label: "Project name", value: m.name, required: true },
      { name: "client", label: "Client", value: m.client },
      { name: "contingency_pct", label: "Contingency %", type: "number", step: "0.01", value: m.contingency_pct, half: true },
      { name: "margin_pct", label: "Margin %", type: "number", step: "0.01", value: m.margin_pct, half: true },
      { name: "gst_pct", label: "GST %", type: "number", step: "0.01", value: m.gst_pct, half: true },
    ] });
    if (!v) return;
    await api("/api/project/meta", { method: "PATCH", body: v });
    await loadProject(); await loadEstimate();
  }),
};
async function exportFile(kind) {
  if (bridge.on) {
    const path = await bridge.call("save_export_dialog", kind);
    if (path) toast(`Exported to ${path}`);
    return;
  }
  const a = document.createElement("a");
  a.href = `/api/export.${kind}`; a.download = "";
  document.body.appendChild(a); a.click(); a.remove();
}

$("uploadInput").onchange = guard(async (ev) => {
  const files = [...ev.target.files];
  for (const f of files) {
    const fd = new FormData(); fd.append("file", f);
    toast(`Importing ${f.name}…`);
    await api("/api/drawings", { method: "POST", body: fd });
  }
  ev.target.value = "";
  toast(`Imported ${files.length} drawing(s)`);
  await loadDrawings();
});

// ------------------------------------------------------------ chrome -------
function initChrome() {
  const menu = $("fileMenu");
  $("fileMenuBtn").onclick = (ev) => { ev.stopPropagation(); menu.hidden = !menu.hidden; };
  document.addEventListener("click", () => (menu.hidden = true));
  menu.addEventListener("click", (ev) => {
    const act = ev.target.closest("button")?.dataset.act;
    if (act) { menu.hidden = true; actions[act](); }
  });
  $("importBtn").onclick = () => actions.import();
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
  document.addEventListener("keydown", (ev) => {
    const ctrl = ev.ctrlKey || ev.metaKey;
    if (!ctrl || $("modal").open) return;
    const k = ev.key.toLowerCase();
    if (k === "o") { ev.preventDefault(); actions.open(); }
    else if (k === "n") { ev.preventDefault(); actions.new(); }
    else if (k === "s" && ev.shiftKey) { ev.preventDefault(); actions.saveas(); }
    else if (k === "s") { ev.preventDefault(); toast("Changes are saved automatically"); }
    else if (k === "e") { ev.preventDefault(); actions.xlsx(); }
  });
}
function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "estimate") loadEstimate();
  if (name === "compare") renderCompareSelectors();
  if (name === "takeoff") requestAnimationFrame(render);
}

(async function init() {
  initChrome(); initTakeoff(); initEstimate(); initCompare();
  const { rules, errors } = await api("/api/rules");
  S.rules = rules;
  if (errors.length) toast(`Rules library: ${errors.length} invalid entr${errors.length > 1 ? "ies" : "y"} skipped`, true);
  await bridge.ready;
  await reloadAll();
})().catch((e) => toast(e.message, true));
