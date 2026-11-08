// Shared state, API client and UI helpers.
export const $ = (id) => document.getElementById(id);
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const fmt = (n, d = 2) => Number(n ?? 0).toLocaleString("en-AU", { minimumFractionDigits: d, maximumFractionDigits: d });
export const money = (n) => "$" + fmt(n, 2);

export const S = {
  project: null, rules: [], categories: [],
  drawings: [], drawing: null, page: 0, info: null, zoom: 1, snapPts: [],
  items: [], activeItem: null, hidden: new Set(),
  shapes: [], selectedShape: null,
  tool: "select", pts: [], cursor: null,
};

// ----------------------------------------------------------------- api ---
export async function api(path, opts = {}) {
  const isForm = opts.body instanceof FormData;
  const r = await fetch(path, {
    ...opts,
    headers: opts.body && !isForm ? { "Content-Type": "application/json" } : {},
    body: opts.body && !isForm ? JSON.stringify(opts.body) : opts.body,
  });
  if (r.status === 204) return null;
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => `${(x.loc || []).slice(1).join(".")}: ${x.msg}`).join("; ") : `HTTP ${r.status}`);
  }
  return data;
}

// --------------------------------------------------------------- toast ---
export function toast(msg, err = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), err ? 6000 : 2600);
}
export const guard = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message, true); } };

// --------------------------------------------------------------- modal ---
/** Show a form. fields: [{name,label,type,value,options,step,required,placeholder,half}]
 *  Resolves to an object of values, or null if cancelled. */
export function modal({ title, fields = [], note = "", ok = "OK", cancel = "Cancel", danger = false }) {
  const dlg = $("modal"), form = $("modalForm");
  const fld = (f) => {
    const id = `m_${f.name}`;
    let ctl;
    if (f.type === "select") {
      ctl = `<select id="${id}" name="${f.name}">${f.options.map((o) => {
        const [v, l, grp] = Array.isArray(o) ? o : [o, o];
        return `<option value="${esc(v)}" ${String(v) === String(f.value ?? "") ? "selected" : ""}>${esc(l)}</option>`;
      }).join("")}</select>`;
    } else if (f.type === "textarea") {
      ctl = `<textarea id="${id}" name="${f.name}" rows="3">${esc(f.value ?? "")}</textarea>`;
    } else {
      ctl = `<input id="${id}" name="${f.name}" type="${f.type || "text"}" value="${esc(f.value ?? "")}" ${f.step ? `step="${f.step}"` : ""} ${f.required ? "required" : ""} placeholder="${esc(f.placeholder || "")}">`;
    }
    return `<label class="f">${esc(f.label)}${ctl}</label>`;
  };
  const halves = [], body = [];
  fields.forEach((f) => (f.half ? halves.push(fld(f)) : body.push(fld(f))));
  form.innerHTML = `<h2>${esc(title)}</h2>${note ? `<div class="note">${note}</div>` : ""}${body.join("")}
    ${halves.length ? `<div class="grid2">${halves.join("")}</div>` : ""}
    <div class="actions">${cancel ? `<button value="cancel" formnovalidate>${esc(cancel)}</button>` : ""}
    <button value="ok" class="${danger ? "danger" : "primary"}">${esc(ok)}</button></div>`;
  return new Promise((resolve) => {
    dlg.onclose = () => {
      if (dlg.returnValue !== "ok") return resolve(null);
      const out = {};
      fields.forEach((f) => {
        const v = form.elements[f.name].value;
        out[f.name] = f.type === "number" ? (v === "" ? null : Number(v)) : v;
      });
      resolve(out);
    };
    dlg.returnValue = "";
    dlg.showModal();
    const first = form.querySelector("input,select,textarea");
    if (first) first.focus();
  });
}
export const confirmBox = async (title, note, ok = "Delete") => (await modal({ title, note, ok, danger: true })) !== null;

// ------------------------------------------------------ desktop bridge ---
// In the desktop app pywebview injects window.pywebview.api (native dialogs).
export const bridge = {
  ready: new Promise((res) => {
    if (window.pywebview?.api) return res(true);
    window.addEventListener("pywebviewready", () => res(true));
    setTimeout(() => res(!!window.pywebview?.api), 1500);
  }),
  get on() { return !!window.pywebview?.api; },
  call: (name, ...args) => window.pywebview.api[name](...args),
};

// ------------------------------------------------------------ events ----
const listeners = {};
export const on = (ev, fn) => (listeners[ev] ||= []).push(fn);
export const emit = (ev, ...a) => (listeners[ev] || []).forEach((fn) => fn(...a));

export const CATEGORY_LABEL = (c) => c.replace(/-/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
export const METRIC_LABEL = { count: "Count", length: "Length", area: "Area", perimeter: "Perimeter", face_area: "Face area", volume: "Volume", slope_area: "Slope area" };
export const METRIC_UNIT = { count: "no.", length: "m", area: "m²", perimeter: "m", face_area: "m²", volume: "m³", slope_area: "m²" };
export const unitLabel = (u) => ({ m2: "m²", m3: "m³" }[u] || u);
