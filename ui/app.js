"use strict";
/* Prismatic interface. Talks to Python through pywebview.api (see prismatic.pyw: Api). */

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = () => window.pywebview.api;

let S = null;            // app state from Python
let LAYOUT = {};         // device id -> {name, kind, shape, frame, dots}
let LIB = [];            // effect library metadata
let route = { page: "devices", target: null };
let fxTab = "builtin";
let dragging = false;
let previews = [];       // [{canvas, ids}]
let lastSig = "";

const PRESETS = ["#ff1f3d", "#ff6a00", "#ffd000", "#00ff40", "#00ffd5", "#2f8cff", "#3a00ff", "#b000ff", "#ff00a0", "#ffffff"];
const SWATCH = { "Static": "sw-static", "Breathing": "sw-breathing", "Duo Pulse": "sw-duo", "Spectrum Cycle": "sw-spectrum",
  "Rainbow Wave": "sw-rainbow", "Gradient Wave": "sw-gradient", "Starlight": "sw-starlight", "Off": "sw-off" };
const LAYER_NAMES = { static: "Static", wave: "Wave", spectrum: "Spectrum", starlight: "Starlight", fire: "Fire",
  colorwheel: "Color wheel", reactive: "Key press", ripple: "Ripple", audiometer: "Audio meter" };
const KIND_ORDER = { mousepad: 0, keyboard: 1, other: 2, mouse: 3 };

/* ------------------------------------------------------------------ icons */
const I = {
  devices: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="14" height="10" rx="2"/><path d="M5 10h.01M8 10h.01M11 10h.01M5 13h6"/><rect x="17.5" y="8" width="4.5" height="9" rx="2.2"/></svg>',
  lighting: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/><circle cx="12" cy="12" r="4"/></svg>',
  library: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5a2 2 0 0 1 2-2h4l2 3h6a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><path d="M9 14l2-2 2 2 2-3"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
  about: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>',
  back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>',
  import: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg>',
  warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l9.5 17h-19z"/><path d="M12 10v4M12 17h.01"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  sparkle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l2 5.5L19.5 10 14 12l-2 5.5L10 12 4.5 10 10 8.5z"/><path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/></svg>',
  power: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v8M6.3 7.3a8 8 0 1 0 11.4 0"/></svg>',
  tray: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 15h5l1.5 2h5L16 15h5"/></svg>',
  keyboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/></svg>',
  chip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/></svg>',
  windows: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 5.5l7.5-1v7H3zM13 4.2L21 3v8.5h-8zM3 13h7.5v7l-7.5-1zM13 13h8v8l-8-1.2z"/></svg>',
  github: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a10 10 0 0 0-3.2 19.5c.5.1.7-.2.7-.5v-1.7c-2.8.6-3.4-1.3-3.4-1.3-.5-1.1-1.1-1.4-1.1-1.4-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.5 2.4 1.1 2.9.8.1-.6.4-1.1.7-1.3-2.2-.3-4.6-1.1-4.6-5a3.9 3.9 0 0 1 1-2.7 3.6 3.6 0 0 1 .1-2.7s.8-.3 2.8 1a9.6 9.6 0 0 1 5 0c1.9-1.3 2.8-1 2.8-1 .5 1.4.2 2.4.1 2.7a3.9 3.9 0 0 1 1 2.7c0 3.9-2.4 4.7-4.6 5 .4.3.7.9.7 1.9V21c0 .3.2.6.7.5A10 10 0 0 0 12 2z"/></svg>',
  mouse: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="3" width="12" height="18" rx="6"/><path d="M12 7v4"/></svg>',
  key: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 15h6"/></svg>',
  file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 14l2-2 2 2 2-3"/></svg>',
};
const LOGO = (id) => `<svg viewBox="0 0 48 48" class="logo"><defs><linearGradient id="pe${id}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ff3b5c"/><stop offset=".2" stop-color="#ffb000"/><stop offset=".4" stop-color="#3ddc6a"/><stop offset=".6" stop-color="#2fd2ff"/><stop offset=".8" stop-color="#2f8cff"/><stop offset="1" stop-color="#9b5cff"/></linearGradient><linearGradient id="pc${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5cb0ff"/><stop offset="1" stop-color="#2f8cff"/></linearGradient></defs><path d="M24 8.5 L38.5 34.5 L9.5 34.5 Z" fill="#121a28" stroke="url(#pe${id})" stroke-width="4.4" stroke-linejoin="round"/><path d="M24 18.6 L30.1 29.5 L17.9 29.5 Z" fill="url(#pc${id})"/></svg>`;

/* ------------------------------------------------------------------ helpers */
const device = (id) => S.devices.find((d) => d.id === id);
const isFile = (eff) => eff.startsWith(S.file_prefix);
const fileName = (eff) => eff.slice(S.file_prefix.length);
const effectLabel = (eff) => (isFile(eff) ? fileName(eff) : eff);
const builtinMeta = (eff) => S.builtin.find((b) => b.name === eff);
const libMeta = (name) => LIB.find((l) => l.name === name);
const profileOf = (target) => S.profiles[target] || S.profiles.all;

function toast(msg, err = false) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.innerHTML = (err ? I.warn : I.check) + `<div>${esc(msg)}</div>`;
  $("#toasts").appendChild(t);
  setTimeout(() => { t.style.transition = "opacity .3s"; t.style.opacity = "0"; setTimeout(() => t.remove(), 300); }, 3800);
}

function confirmModal(title, text, okLabel, onOk) {
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal"><h3>${esc(title)}</h3><p>${esc(text)}</p><div class="actions">
    <button class="btn ghost" data-m="cancel">Cancel</button><button class="btn red" data-m="ok">${esc(okLabel)}</button></div></div>`;
  bg.addEventListener("click", (e) => {
    const m = e.target.closest("[data-m]");
    if (e.target === bg || (m && m.dataset.m === "cancel")) bg.remove();
    else if (m && m.dataset.m === "ok") { bg.remove(); onOk(); }
  });
  document.body.appendChild(bg);
}

function sourceKind(src) { return src.ok ? "ok" : src.status === "Turned off" || src.standby ? "off" : "warn"; }
const source = (name) => S.sources.find((s) => s.name === name) || { name, ok: false, status: "" };

/* Thumbnail background for an effect file, from colors sampled out of the effect itself */
function paletteStyle(name) {
  const m = libMeta(name);
  const p = (m && m.palette || []).filter((c) => /^#[0-9a-f]{6}$/i.test(c));
  if (!p.length) return "";
  if (p.length === 1) return `background:${p[0]}`;
  return `background:linear-gradient(110deg,${p.join(",")})`;
}

function statusChip(d) {
  if (!d.enabled) return '<span class="chip off">Off</span>';
  if (!d.available) return '<span class="chip warn">Paused</span>';
  return '<span class="chip ok">Active</span>';
}

function signature() {
  return JSON.stringify([S.devices.map((d) => [d.id, d.available, d.enabled, d.own]), S.sources, S.library, S.errors, S.settings]);
}

/* ------------------------------------------------------------------ shell */
function renderShell() {
  $("#root").innerHTML = `<div class="app">
    <aside class="sidebar">
      <div class="brand">${LOGO("s")}<div class="word">PRISMATIC</div></div>
      <nav class="nav" id="nav"></nav>
      <div class="side-foot" id="sources"></div>
    </aside>
    <main id="main"></main>
  </div>`;
  $("#root").addEventListener("click", onClick);
  $("#root").addEventListener("contextmenu", onContext);
  $("#root").addEventListener("change", onChange);
  $("#root").addEventListener("input", onInput);
  $("#root").addEventListener("pointerdown", (e) => { if (e.target.type === "range") dragging = true; });
  window.addEventListener("pointerup", () => { if (dragging) { dragging = false; refresh(true); } });
}

function renderSidebar() {
  const items = [["devices", "Devices", I.devices, S.devices.length], ["lighting", "Lighting", I.lighting, ""],
    ["library", "Effect Library", I.library, S.library.length], ["buttons", "Buttons", I.mouse, ""],
    ["settings", "Settings", I.settings, ""], ["about", "About", I.about, ""]];
  const active = route.page === "lighting" && route.target !== "all" ? "devices" : route.page;
  $("#nav").innerHTML = items.map(([id, label, icon, count]) =>
    `<button class="${active === id ? "active" : ""}" data-act="nav" data-arg="${id}">${icon}<span>${label}</span>${count !== "" ? `<span class="count">${count}</span>` : ""}</button>`).join("");
  $("#sources").innerHTML = `<div class="label">Device sources</div>` + S.sources.map((s) =>
    `<div class="source" title="${esc(s.status)}"><span class="dot ${sourceKind(s)}"></span>${esc(s.name)}</div>`).join("");
}

/* ------------------------------------------------------------------ pages */
function renderPage() {
  previews = [];
  const main = $("#main");
  const scroll = main.scrollTop;
  const pages = { devices: pageDevices, lighting: pageLighting, library: pageLibrary, buttons: pageButtons, settings: pageSettings, about: pageAbout };
  main.innerHTML = `<div class="page">${(pages[route.page] || pageDevices)()}</div>`;
  main.scrollTop = scroll;
  document.querySelectorAll("canvas.preview").forEach((c) => previews.push({ canvas: c, ids: c.dataset.ids.split(",").filter(Boolean) }));
  renderSidebar();
  drawAll(null);
}

function pageDevices() {
  const all = profileOf("all");
  const own = S.devices.filter((d) => d.own);
  const ids = S.devices.map((d) => d.id).join(",");
  const hero = `<div class="panel hero">
    <div class="stage"><canvas class="preview" data-ids="${esc(ids)}"></canvas></div>
    <div class="side">
      <div class="k">All devices</div>
      <div class="v">${esc(effectLabel(all.effect))}</div>
      <div class="meta">${S.devices.length} device${S.devices.length === 1 ? "" : "s"} connected${own.length ? ` · ${own.length} with their own effect` : ""}</div>
      <div class="actions"><button class="btn primary" data-act="open" data-arg="all">${I.lighting}Customize lighting</button></div>
    </div></div>`;
  if (!S.devices.length) {
    return head("Overview", "Devices", "Everything Prismatic is lighting up") + `<div class="panel">${emptyDevices()}</div>`;
  }
  const cards = [...S.devices].sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind]).map((d) => {
    const p = profileOf(d.id);
    return `<div class="card" data-act="open" data-arg="${esc(d.id)}">
      <div class="thumb"><canvas class="preview" data-ids="${esc(d.id)}"></canvas></div>
      <div class="body">
        <div class="row"><div class="name" title="${esc(d.name)}">${esc(d.name)}</div>
          <label class="switch"><input type="checkbox" data-act="enabled" data-arg="${esc(d.id)}" ${d.enabled ? "checked" : ""}><span></span></label></div>
        <div class="meta">${esc(d.brand)} · ${esc(d.source)}</div>
        <div class="effect">${statusChip(d)}<span class="muted">${d.own ? esc(effectLabel(p.effect)) : "Following All devices"}</span></div>
      </div></div>`;
  }).join("");
  return head("Overview", "Devices", "Everything Prismatic is lighting up") + hero + `<h2>Your devices</h2><div class="grid">${cards}</div>`;
}

function emptyDevices() {
  return `<div class="empty">${I.devices}<div class="t">No lighting devices found yet</div>
    <p>Prismatic controls Razer devices through Razer Synapse, and devices from other brands through Windows Dynamic Lighting.
    Check that your devices are plugged in, and see Settings for each source's status.</p>
    <button class="btn" data-act="nav" data-arg="settings">${I.settings}Open settings</button></div>`;
}

function head(eyebrow, title, sub, actions = "", back = false) {
  return `${back ? `<button class="back" data-act="nav" data-arg="devices">${I.back}All devices</button>` : ""}
    <div class="page-head"><div class="titles"><div class="eyebrow">${eyebrow}</div><h1 title="${esc(title)}">${esc(title)}</h1>${sub ? `<div class="sub">${sub}</div>` : ""}</div>${actions}</div>`;
}

function pageLighting() {
  const target = route.target || "all";
  const d = target === "all" ? null : device(target);
  if (target !== "all" && !d) { route = { page: "devices" }; return pageDevices(); }
  const p = profileOf(target);
  const locked = d && !d.own;
  const ids = d ? d.id : S.devices.map((x) => x.id).join(",");
  let notices = "";
  for (const e of S.errors) notices += `<div class="notice">${I.warn}<div>${esc(e)}</div></div>`;
  if (d && d.enabled && !d.available) {
    notices += `<div class="notice">${I.info}<div><b>Paused while Prismatic is in the background.</b> Windows only lets the app in front control Dynamic Lighting devices, so this device follows Prismatic while its window is active.</div></div>`;
  }
  if (!d && S.devices.some((x) => x.source === "Windows Dynamic Lighting")) {
    notices += `<div class="notice info">${I.info}<div>Devices using Windows Dynamic Lighting follow Prismatic while its window is in front. Razer devices work in the background through Synapse.</div></div>`;
  }
  const title = d ? d.name : "All devices";
  const sub = d ? `${esc(d.brand)} · ${esc(d.source)} · ${d.leds} LEDs` : `Applies to every device that isn't using its own effect`;
  const fx = effectGrid(target, p, locked);
  return head(d ? "Device lighting" : "Lighting", title, sub, "", true) + notices + `<div class="lighting">
    <div>
      <div class="stage-lg"><canvas class="preview" data-ids="${esc(ids)}"></canvas></div>
      <div class="tabs"><button class="${fxTab === "builtin" ? "active" : ""}" data-act="fxtab" data-arg="builtin">Built-in effects</button>
        <button class="${fxTab === "library" ? "active" : ""}" data-act="fxtab" data-arg="library">Chroma Studio effects (${S.library.length})</button></div>
      ${fx}
    </div>
    ${customizePanel(target, d, p, locked)}
  </div>`;
}

function effectGrid(target, p, locked) {
  const vars = `--c1:${esc(p.color1)};--c2:${esc(p.color2)}`;
  if (fxTab === "builtin") {
    return `<div class="effects ${locked ? "" : ""}">${S.builtin.map((b) =>
      `<button class="fx ${p.effect === b.name ? "active" : ""} ${locked ? "disabled" : ""}" data-act="effect" data-arg="${esc(b.name)}">
        <div class="sw ${SWATCH[b.name]}" style="${vars}"></div><div class="lbl"><b>${esc(b.name)}</b><span>${esc(b.desc)}</span></div></button>`).join("")}</div>`;
  }
  if (!S.library.length) {
    return `<div class="panel"><div class="empty">${I.library}<div class="t">No Chroma Studio effects yet</div>
      <p>Import effects you exported from Synapse 3's Chroma Studio (.ChromaEffects). They're remapped to fit your devices.</p>
      <button class="btn primary" data-act="import">${I.import}Import effects</button></div></div>`;
  }
  return `<div class="effects">${S.library.map((name) => {
    const m = libMeta(name);
    const eff = S.file_prefix + name;
    const desc = m && m.layers.length ? m.layers.map((l) => LAYER_NAMES[l] || l).join(" · ") : "Chroma Studio effect";
    return `<button class="fx ${p.effect === eff ? "active" : ""} ${locked ? "disabled" : ""}" data-act="effect" data-arg="${esc(eff)}" title="${esc(name)}">
      <div class="sw sw-file" style="${paletteStyle(name)}">${I.file}</div><div class="lbl"><b>${esc(name)}</b><span>${esc(desc)}</span></div></button>`;
  }).join("")}</div>`;
}

function customizePanel(target, d, p, locked) {
  const meta = builtinMeta(p.effect);
  const file = isFile(p.effect);
  const ncolors = meta ? meta.colors : 0;
  const hasSpeed = file || (meta && meta.speed);
  let html = '<div class="panel custom">';
  if (d) {
    html += `<div class="sect"><div class="toggle-row"><div class="txt"><b>Lighting</b><span>${d.enabled ? "On" : "Off"} for this device</span></div>
        <label class="switch"><input type="checkbox" data-act="enabled" data-arg="${esc(d.id)}" ${d.enabled ? "checked" : ""}><span></span></label></div>
      <div class="toggle-row" style="margin-top:14px"><div class="txt"><b>Sync with All devices</b><span>${d.own ? "Using its own effect" : "Following the shared effect"}</span></div>
        <label class="switch"><input type="checkbox" data-act="sync" data-arg="${esc(d.id)}" ${d.own ? "" : "checked"}><span></span></label></div>
      ${locked ? `<div class="hint">Turn off sync to give this device its own effect, or <button class="linkish" data-act="open" data-arg="all">edit All devices</button>.</div>` : ""}</div>`;
  } else {
    const own = S.devices.filter((x) => x.own);
    if (own.length) {
      html += `<div class="sect"><div class="muted">Using their own effect: ${own.map((x) =>
        `<button class="linkish" data-act="open" data-arg="${esc(x.id)}">${esc(x.name)}</button>`).join(", ")}</div></div>`;
    }
  }
  const dim = locked ? " dim" : "";
  const m = file ? libMeta(fileName(p.effect)) : null;
  const desc = file ? (m && m.layers.length ? `Chroma Studio effect · ${m.layers.map((l) => LAYER_NAMES[l] || l).join(", ")}` : "Chroma Studio effect")
    : meta ? meta.desc : "";
  html += `<div class="sect${dim}"><div class="muted" style="margin-bottom:4px">Current effect</div><div class="current">${esc(effectLabel(p.effect))}</div>
    <div class="muted">${esc(desc)}</div>
    ${file && m && m.keys ? `<div class="hint">Lights up keys as you type${S.settings.keypress_effects ? "" : " — turned off in Settings"}.</div>` : ""}
    ${file && m && m.audio ? `<div class="hint">Reacts to the sound your PC is playing.</div>` : ""}</div>`;
  if (ncolors) {
    html += `<div class="sect${dim}"><h2>Colors</h2><div class="colors">
      ${colorSwatch("color1", ncolors === 1 ? "Color" : "Primary", p.color1)}${ncolors > 1 ? colorSwatch("color2", "Secondary", p.color2) : ""}</div>
      <div class="presets">${PRESETS.map((c) => `<button style="background:${c}" data-act="preset" data-arg="${c}" title="${c}"></button>`).join("")}</div>
      <div class="hint">${ncolors > 1 ? "Click a preset for the primary color, right-click for the secondary." : "Click a preset or the swatch to pick any color."}</div></div>`;
  }
  if (p.effect !== "Off") {
    html += `<div class="sect${dim}"><h2>Adjust</h2>${slider("brightness", "Brightness", p.brightness, 0, 100, "%")}
      ${hasSpeed ? slider("speed", "Speed", p.speed, 1, 10, "") : ""}</div>`;
  }
  return html + "</div>";
}

function colorSwatch(key, label, value) {
  return `<button class="swatch" data-act="color" data-arg="${key}"><i style="background:${esc(value)};--glow:${esc(value)}"></i>
    <div><b>${label}</b><span>${esc(value.toUpperCase())}</span></div></button>`;
}

function slider(key, label, value, min, max, unit) {
  const pct = ((value - min) / (max - min)) * 100;
  return `<div class="slider"><div class="name">${label}</div>
    <input type="range" min="${min}" max="${max}" value="${value}" data-key="${key}" style="--p:${pct}%">
    <div class="val" data-val="${key}">${value}${unit}</div></div>`;
}

function pageLibrary() {
  const actions = `<button class="btn ghost" data-act="folder">${I.folder}Open folder</button>
    <button class="btn primary" data-act="import">${I.import}Import effects</button>`;
  const intro = "Effects exported from Synapse 3's Chroma Studio. Each one is remapped to fit whatever devices you have.";
  if (!LIB.length) {
    return head("Library", "Effect Library", intro, `<div style="display:flex;gap:8px">${actions}</div>`) +
      `<div class="panel"><div class="empty">${I.library}<div class="t">Your library is empty</div>
      <p>In Synapse 3, open Chroma Studio and export an effect, or download one shared online. Then import the .ChromaEffects file here.</p>
      <button class="btn primary" data-act="import">${I.import}Import effects</button></div></div>`;
  }
  const allEff = profileOf("all").effect;
  const items = LIB.map((m) => {
    const eff = S.file_prefix + m.name;
    const chips = (m.layers.length ? m.layers : ["unreadable"]).map((l) => `<span class="chip">${esc(LAYER_NAMES[l] || l)}</span>`).join("");
    return `<div class="item"><div class="sw sw-file" style="${paletteStyle(m.name)}">${I.file}</div><div class="body">
      <div class="name" title="${esc(m.name)}">${esc(m.name)}</div><div class="chips">${chips}</div>
      <div class="actions">${allEff === eff ? `<span class="chip accent">${I.check.replace("<svg", '<svg width="12" height="12"')} Playing on All devices</span>`
        : `<button class="btn small" data-act="apply" data-arg="${esc(eff)}">Apply to all devices</button>`}
        <button class="btn small ghost danger" data-act="delete" data-arg="${esc(m.name)}" title="Remove from library" style="margin-left:auto">${I.trash}</button></div>
    </div></div>`;
  }).join("");
  return head("Library", "Effect Library", intro, `<div style="display:flex;gap:8px">${actions}</div>`) + `<div class="lib">${items}</div>`;
}

function settingRow(icon, title, desc, key, on) {
  return `<div class="row"><div class="ico">${icon}</div><div class="txt"><b>${title}</b><span>${desc}</span></div>
    <label class="switch"><input type="checkbox" data-act="setting" data-arg="${key}" ${on ? "checked" : ""}><span></span></label></div>`;
}

/* ------------------------------------------------------------------ buttons */
let BTN = null;           // {triggers, config, media, last_pressed, status}
const MEDIA_NAMES = { play_pause: "Play / pause", next: "Next track", previous: "Previous track", stop: "Stop",
  volume_up: "Volume up", volume_down: "Volume down", mute: "Mute" };
const ACTION_TYPES = [["default", "Default (do what it normally does)"], ["disabled", "Disabled (do nothing)"],
  ["keys", "Press a key or shortcut"], ["media", "Media control"], ["launch", "Open an app, file or website"],
  ["text", "Type text"], ["sequence", "Sequence of steps"]];
const STEP_TYPES = [["keys", "Shortcut"], ["text", "Type text"], ["media", "Media"], ["launch", "Open"], ["delay", "Wait"]];

function describeAction(a) {
  if (!a || a.type === "default") return "Default";
  switch (a.type) {
    case "disabled": return "Disabled";
    case "keys": return "Press " + (a.label || "a shortcut");
    case "media": return MEDIA_NAMES[a.media] || "Media control";
    case "launch": return "Open " + a.target;
    case "text": return `Type "${a.text.length > 40 ? a.text.slice(0, 40) + "…" : a.text}"`;
    case "delay": return `Wait ${a.ms} ms`;
    case "sequence": return `${a.steps.length}-step sequence: ` + a.steps.map(describeAction).join(", ");
  }
  return "Default";
}

async function loadButtons() { try { BTN = await api().get_buttons(); } catch (e) { BTN = null; } }

function buttonRow(t) {
  const a = BTN.config[t.id];
  const custom = a && a.type !== "default";
  const name = t.id.startsWith("mouse") ? t.name.replace("Mouse: ", "") : t.name;
  return `<div class="btn-row ${custom ? "custom" : ""}" data-trigger="${esc(t.id)}">
    <div class="ico">${t.id.startsWith("mouse") ? I.mouse : I.key}</div>
    <div class="txt"><b>${esc(name)}</b><span>${esc(describeAction(a))}</span></div>
    <span class="just">Pressed</span>
    <button class="btn small" data-act="edit-button" data-arg="${esc(t.id)}">Edit</button></div>`;
}

function pageButtons() {
  if (!BTN) {
    loadButtons().then(renderPage);
    return head("Customize", "Buttons", "") + `<div class="panel"><div class="empty"><div class="spinner"></div></div></div>`;
  }
  const mouse = BTN.triggers.filter((t) => t.id.startsWith("mouse"));
  const keys = BTN.triggers.filter((t) => !t.id.startsWith("mouse"));
  return head("Customize", "Buttons", "Give your mouse side buttons and keyboard macro keys new jobs. Press a button and its row lights up.") +
    `<div class="settings">
      <div><h2>Mouse side buttons</h2><div class="panel btn-list">${mouse.map(buttonRow).join("")}</div></div>
      <div><h2>Keyboard macro keys</h2>
        <div class="notice info">${I.info}<div>Prismatic customizes macro keys through <b>F13–F24</b> — keys no keyboard actually has, so nothing else uses them.
        In Razer Synapse, set each macro key to a different one (for example M1 → F13, M2 → F14), then press it here to see which row lights up.</div></div>
        <div class="panel btn-list">${keys.map(buttonRow).join("")}</div></div>
    </div>`;
}

async function pollButtons() {
  if (route.page !== "buttons" || document.hidden || !BTN) return;
  try {
    const b = await api().get_buttons();
    BTN.last_pressed = b.last_pressed;
    document.querySelectorAll(".btn-row").forEach((row) => {
      const lp = b.last_pressed;
      row.classList.toggle("pressed", !!lp && lp.id === row.dataset.trigger && lp.ago < 1.5);
    });
  } catch (e) { /* ignore */ }
}

/* ---- editor ---- */
function keyLabel(e) {
  const names = { " ": "Space", ArrowLeft: "Left", ArrowRight: "Right", ArrowUp: "Up", ArrowDown: "Down", Escape: "Esc" };
  if (names[e.key]) return names[e.key];
  if (e.key && e.key.length === 1) return e.key.toUpperCase();
  return e.key || e.code;
}

function recordShortcut(el, onDone) {
  el.classList.add("listening");
  el.textContent = "Press a key or shortcut…";
  const handler = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (["Control", "Shift", "Alt", "Meta"].includes(e.key)) return; // wait for the main key
    const keys = [], parts = [];
    if (e.ctrlKey) { keys.push(17); parts.push("Ctrl"); }
    if (e.shiftKey) { keys.push(16); parts.push("Shift"); }
    if (e.altKey) { keys.push(18); parts.push("Alt"); }
    if (e.metaKey) { keys.push(91); parts.push("Win"); }
    keys.push(e.keyCode);
    parts.push(keyLabel(e));
    el.removeEventListener("keydown", handler, true);
    el.classList.remove("listening");
    onDone({ keys, label: parts.join(" + ") });
  };
  el.addEventListener("keydown", handler, true);
  el.focus();
}

function stepEditor(step, i) {
  // the input fields for one action (the whole action, or one step of a sequence)
  const t = step.type;
  if (t === "keys") {
    const shown = step.keys && step.keys.length
      ? step.label.split(" + ").map((k) => `<kbd>${esc(k)}</kbd>`).join("+") : "Click, then press a key or shortcut";
    return `<div class="recorder" tabindex="0" data-rec="${i}">${shown}</div>`;
  }
  if (t === "media") {
    return `<select data-f="media" data-i="${i}">${Object.entries(MEDIA_NAMES).map(([k, v]) =>
      `<option value="${k}" ${step.media === k ? "selected" : ""}>${v}</option>`).join("")}</select>`;
  }
  if (t === "launch") {
    return `<div class="row2"><input type="text" data-f="target" data-i="${i}" placeholder="App path, file or https:// link" value="${esc(step.target || "")}">
      <button class="btn small" data-browse="${i}">Browse…</button></div>`;
  }
  if (t === "text") return `<textarea data-f="text" data-i="${i}" placeholder="Text to type">${esc(step.text || "")}</textarea>`;
  if (t === "delay") {
    return `<input type="number" min="0" max="10000" step="50" data-f="ms" data-i="${i}" value="${Number(step.ms || 200)}"> <span class="hint">milliseconds</span>`;
  }
  return "";
}

function newStep(type) {
  return { keys: { type: "keys", keys: [], label: "" }, media: { type: "media", media: "play_pause" },
    launch: { type: "launch", target: "" }, text: { type: "text", text: "" }, delay: { type: "delay", ms: 200 } }[type] || { type };
}

function openButtonEditor(triggerId) {
  const t = BTN.triggers.find((x) => x.id === triggerId);
  let draft = JSON.parse(JSON.stringify(BTN.config[triggerId] || { type: "default" }));
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  document.body.appendChild(bg);
  const steps = () => (draft.type === "sequence" ? draft.steps : [draft]);
  const fieldLabel = { keys: "Shortcut", media: "Media control", launch: "What to open", text: "Text to type" };

  const render = () => {
    let body = `<div class="field"><label>When I press it</label><select data-type="1">${ACTION_TYPES.map(([k, v]) =>
      `<option value="${k}" ${draft.type === k ? "selected" : ""}>${v}</option>`).join("")}</select></div>`;
    if (draft.type === "sequence") {
      body += `<div class="steps">${draft.steps.map((s, i) => `<div class="step"><div class="n">${i + 1}</div>
        <select data-steptype="${i}">${STEP_TYPES.map(([k, v]) => `<option value="${k}" ${s.type === k ? "selected" : ""}>${v}</option>`).join("")}</select>
        <div class="grow field">${stepEditor(s, i)}</div>
        <button class="btn small ghost danger" data-remove="${i}" title="Remove step">${I.trash}</button></div>`).join("")}</div>
        <button class="btn small" data-add="1">+ Add step</button>`;
    } else if (!["default", "disabled"].includes(draft.type)) {
      body += `<div class="field"><label>${fieldLabel[draft.type]}</label>${stepEditor(draft, 0)}</div>`;
    }
    const canTest = !["default", "disabled"].includes(draft.type);
    const intro = t.id.startsWith("mouse") ? "Choose what this side button does."
      : `Choose what happens when a key set to ${esc(t.name)} is pressed.`;
    bg.innerHTML = `<div class="modal wide"><h3>${esc(t.name)}</h3><p>${intro}</p>
      <div class="mbody">${body}</div>
      <div class="mfoot">${canTest ? `<button class="btn" data-test="1">Test</button>` : ""}<div class="spacer"></div>
        <button class="btn ghost" data-cancel="1">Cancel</button><button class="btn primary" data-save="1">Save</button></div></div>`;
  };

  const setField = (el) => {
    const s = steps()[+el.dataset.i];
    s[el.dataset.f] = el.dataset.f === "ms" ? Number(el.value) : el.value;
  };
  bg.addEventListener("change", (e) => {
    const el = e.target;
    if (el.dataset.type) {
      const type = el.value;
      draft = type === "sequence" ? { type, steps: draft.type === "sequence" ? draft.steps : [newStep("keys")] } : newStep(type);
      return render();
    }
    if (el.dataset.steptype !== undefined) { draft.steps[+el.dataset.steptype] = newStep(el.value); return render(); }
    if (el.dataset.f) setField(el);
  });
  bg.addEventListener("input", (e) => { if (e.target.dataset.f && e.target.tagName !== "SELECT") setField(e.target); });
  bg.addEventListener("click", async (e) => {
    if (e.target === bg) return bg.remove();
    const el = e.target.closest("[data-rec],[data-browse],[data-remove],[data-add],[data-test],[data-cancel],[data-save]");
    if (!el) return;
    if (el.dataset.rec !== undefined) {
      const i = +el.dataset.rec;
      return recordShortcut(el, (r) => { Object.assign(steps()[i], r); render(); });
    }
    if (el.dataset.browse !== undefined) {
      const path = await api().browse_for_app();
      if (path) { steps()[+el.dataset.browse].target = path; render(); }
      return;
    }
    if (el.dataset.remove !== undefined) {
      draft.steps.splice(+el.dataset.remove, 1);
      if (!draft.steps.length) draft = { type: "default" };
      return render();
    }
    if (el.dataset.add) { draft.steps.push(newStep("keys")); return render(); }
    if (el.dataset.test) {
      const r = await api().test_button_action(draft);
      toast(r === "default" ? "Nothing to test yet — finish setting it up first" : "Testing in a moment…", r === "default");
      return;
    }
    if (el.dataset.cancel) return bg.remove();
    if (el.dataset.save) {
      BTN = await api().set_button(triggerId, draft);
      bg.remove();
      toast(`${t.name}: ${describeAction(BTN.config[triggerId])}`);
      renderPage();
    }
  });
  render();
}

function pageSettings() {
  const st = S.settings;
  const razer = source("Razer Chroma"), usb = source("Razer direct USB"), dl = source("Windows Dynamic Lighting");
  return head("Preferences", "Settings", "") + `<div class="settings">
    <div><h2>General</h2><div class="panel">
      ${settingRow(I.power, "Start with Windows", "Launch Prismatic in the tray when you sign in.", "start_with_windows", st.start_with_windows)}
      ${settingRow(I.tray, "Keep running in the tray when closed", "Your lighting stays on after you close the window. Right-click the tray icon → Exit to quit.", "close_to_tray", st.close_to_tray)}
    </div></div>
    <div><h2>Lighting</h2><div class="panel">
      ${settingRow(I.keyboard, "Light up keys when pressed", "Lets Chroma Studio effects react to typing (key press and ripple layers).", "keypress_effects", st.keypress_effects)}
    </div></div>
    <div><h2>Device sources</h2><div class="panel">
      <div class="row"><div class="ico">${I.chip}</div><div class="txt"><b>Razer Chroma <span class="dot ${sourceKind(razer)}" style="display:inline-block;margin-left:6px"></span></b>
        <span>${esc(razer.status)}</span><span>Controls Razer devices through Razer Synapse, including while Prismatic is in the tray.</span></div></div>
      ${settingRow(I.chip, `Razer direct USB <span class="dot ${sourceKind(usb)}" style="display:inline-block;margin-left:6px"></span>`,
        `${esc(usb.status)}. When Synapse isn't installed or running, Prismatic controls supported Razer devices itself (BlackWidow V4 Pro, DeathAdder V2, Firefly V2) — in the background too. It steps aside while Synapse is running so the two don't fight.`,
        "usb_control", st.usb_control)}
      ${settingRow(I.windows, `Windows Dynamic Lighting <span class="dot ${sourceKind(dl)}" style="display:inline-block;margin-left:6px"></span>`,
        `${esc(dl.status)}. Controls devices from Logitech, Corsair, SteelSeries, HyperX, ASUS and more that support Windows 11 Dynamic Lighting. Windows only lets the app in front control these, so they follow Prismatic while its window is active.`,
        "dynamic_lighting", st.dynamic_lighting)}
    </div></div>
    <div><h2>Data</h2><div class="panel">
      <div class="row"><div class="ico">${I.folder}</div><div class="txt"><b>Effect library folder</b><span>${esc(S.effects_dir)}</span></div>
        <button class="btn small" data-act="folder">Open</button></div>
    </div></div>
  </div>`;
}

function pageAbout() {
  return `<div class="about"><div class="panel hero-a">${LOGO("a")}<div>
      <div class="eyebrow">Version ${esc(S.version)}</div><h1>Prismatic</h1>
      <div class="sub">A lightweight lighting app for gaming keyboards, mice and mousepads.</div></div></div>
    <div class="panel pad" style="margin-top:16px">
      <p style="margin-top:0">Prismatic controls Razer devices through Razer Synapse's Chroma SDK, and devices from other brands through Windows Dynamic Lighting.
      It can also play effects exported from Synapse 3's Chroma Studio, remapped to fit whatever devices you own.</p>
      <div class="links">
        <button class="btn" data-act="link" data-arg="repo">${I.github}GitHub</button>
        <button class="btn" data-act="link" data-arg="issues">Report a problem</button>
        <button class="btn" data-act="link" data-arg="releases">Check for updates</button>
      </div>
      <div class="fine">Open source under the MIT License. Prismatic is an independent project and is not affiliated with, endorsed by, or supported by
      Razer Inc. or any other device maker. Razer, Chroma and Synapse are trademarks of Razer Inc.; other names are trademarks of their owners.</div>
    </div></div>`;
}

/* ------------------------------------------------------------------ events */
async function setState(next) { if (next) { S = next; lastSig = signature(); } }

async function act(promise, rerender = true) {
  try { await setState(await promise); } catch (e) { toast("Something went wrong: " + e, true); }
  if (rerender) renderPage();
}

function go(page, target = null) {
  route = { page, target };
  renderPage();
  $("#main").scrollTop = 0;
}

let colorTimer = null;
function onClick(e) {
  if (e.target.closest(".switch")) return; // switches are handled by onChange (and mustn't open the card)
  const el = e.target.closest("[data-act]");
  if (!el || el.tagName === "INPUT") return;
  const a = el.dataset.act, arg = el.dataset.arg;
  const target = route.target || "all";
  switch (a) {
    case "nav": return arg === "lighting" ? go("lighting", "all") : go(arg);
    case "open": return go("lighting", arg);
    case "fxtab": fxTab = arg; return renderPage();
    case "effect": return act(api().set_profile(target, { effect: arg }));
    case "preset": return act(api().set_profile(target, { color1: arg }));
    case "color": {
      const picker = $("#picker");
      picker.value = profileOf(target)[arg];
      picker.dataset.key = arg;
      picker.click();
      return;
    }
    case "import": return doImport();
    case "folder": return api().open_effects_folder();
    case "apply": return act(api().set_profile("all", { effect: arg })).then(() => toast(`Playing ${effectLabel(arg)} on all devices`));
    case "delete":
      return confirmModal("Remove effect?", `"${arg}" will be removed from your library. Devices using it switch to Rainbow Wave.`, "Remove",
        () => act(api().delete_effect(arg)).then(loadLibrary));
    case "link": return api().open_link(arg);
    case "edit-button": return openButtonEditor(arg);
  }
}

function onContext(e) {
  const el = e.target.closest('[data-act="preset"]');
  if (!el) return;
  e.preventDefault();
  act(api().set_profile(route.target || "all", { color2: el.dataset.arg }));
}

function onChange(e) {
  const el = e.target;
  if (el.type === "checkbox") {
    const a = el.dataset.act, arg = el.dataset.arg;
    if (a === "enabled") return act(api().set_enabled(arg, el.checked));
    if (a === "sync") return act(api().set_own(arg, !el.checked));
    if (a === "setting") return act(api().set_setting(arg, el.checked)).then(() => {
      if (arg === "start_with_windows") toast(el.checked ? "Prismatic will start with Windows" : "Prismatic won't start with Windows");
    });
  }
  if (el.type === "range") { dragging = false; refresh(true); }
}

let sliderTimer = null;
function onInput(e) {
  const el = e.target;
  if (el.type !== "range") return;
  const key = el.dataset.key, v = Number(el.value);
  el.style.setProperty("--p", ((v - el.min) / (el.max - el.min)) * 100 + "%");
  const out = document.querySelector(`[data-val="${key}"]`);
  if (out) out.textContent = v + (key === "brightness" ? "%" : "");
  clearTimeout(sliderTimer);
  sliderTimer = setTimeout(() => api().set_profile(route.target || "all", { [key]: v }).then(setState), 40);
}

function onPicker(e) {
  const key = e.target.dataset.key, v = e.target.value;
  const sw = document.querySelector(`[data-act="color"][data-arg="${key}"]`);
  if (sw) { sw.querySelector("i").style.background = v; sw.querySelector("span").textContent = v.toUpperCase(); }
  clearTimeout(colorTimer);
  colorTimer = setTimeout(() => act(api().set_profile(route.target || "all", { [key]: v }), e.type === "change"), 60);
}

async function doImport() {
  try {
    const r = await api().import_effects();
    await setState(r.state);
    await loadLibrary();
    if (r.imported.length) toast(`Imported ${r.imported.length} effect${r.imported.length === 1 ? "" : "s"}`);
    if (r.failed.length) toast(`Not valid Chroma Studio files: ${r.failed.join(", ")}`, true);
    if (r.imported.length && route.page === "lighting") fxTab = "library";
  } catch (e) { toast("Import failed: " + e, true); }
  renderPage();
}

/* ------------------------------------------------------------------ preview drawing */
function hexAt(str, i) {
  const o = i * 6;
  return [parseInt(str.substr(o, 2), 16), parseInt(str.substr(o + 2, 2), 16), parseInt(str.substr(o + 4, 2), 16)];
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

let lastFrame = {};
function drawAll(frame) {
  if (frame) lastFrame = frame;
  for (const p of previews) drawPreview(p.canvas, p.ids, lastFrame);
}

function drawPreview(canvas, ids, frame) {
  const devs = ids.map((id) => [id, LAYOUT[id]]).filter((x) => x[1]).sort((a, b) => KIND_ORDER[a[1].kind] - KIND_ORDER[b[1].kind]);
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const W = Math.max(1, Math.round(rect.width * dpr)), H = Math.max(1, Math.round(rect.height * dpr));
  if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, W, H);
  if (!devs.length) return;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [, l] of devs) { const [x, y, w, h] = l.frame; x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x + w); y1 = Math.max(y1, y + h); }
  const pad = 2.2;
  const s = Math.min(W / (x1 - x0 + pad * 2), H / (y1 - y0 + pad * 2));
  const ox = (W - (x1 - x0) * s) / 2 - x0 * s, oy = (H - (y1 - y0) * s) / 2 - y0 * s;
  const X = (v) => ox + v * s, Y = (v) => oy + v * s;
  for (const [id, l] of devs) {
    const cols = frame[id] || "";
    const col = (n) => (cols ? hexAt(cols, n) : [0, 0, 0]);
    const [fx, fy, fw, fh] = l.frame;
    // soft glow behind the device
    ctx.globalCompositeOperation = "lighter";
    l.dots.forEach((d, n) => {
      if (d[1] !== "glow" && d[1] !== "seg" && d[1] !== "logo" && d[1] !== "dot") return;
      const [r, g, b] = col(n);
      if (r + g + b < 12) return;
      const rad = (d[1] === "glow" ? 1.9 : d[1] === "seg" ? 1.6 : 1.4) * s;
      const grd = ctx.createRadialGradient(X(d[2]), Y(d[3]), 0, X(d[2]), Y(d[3]), rad);
      grd.addColorStop(0, `rgba(${r},${g},${b},${d[1] === "glow" ? 0.55 : 0.45})`);
      grd.addColorStop(1, `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = grd;
      ctx.fillRect(X(d[2]) - rad, Y(d[3]) - rad, rad * 2, rad * 2);
    });
    ctx.globalCompositeOperation = "source-over";
    // body
    ctx.fillStyle = l.kind === "mousepad" ? "#0a0e14" : "#0d1118";
    ctx.strokeStyle = "#1f2733";
    ctx.lineWidth = Math.max(1, s * 0.06);
    if (l.kind === "mouse") {
      const cx = X(fx + fw / 2), w = fw * 0.72 * s, top = Y(fy), h = fh * s;
      ctx.beginPath();
      ctx.moveTo(cx, top);
      ctx.bezierCurveTo(cx + w / 2, top, cx + w / 2, top + h * 0.35, cx + w / 2, top + h * 0.6);
      ctx.bezierCurveTo(cx + w / 2, top + h, cx - w / 2, top + h, cx - w / 2, top + h * 0.6);
      ctx.bezierCurveTo(cx - w / 2, top + h * 0.35, cx - w / 2, top, cx, top);
      ctx.fill(); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(cx, top + h * 0.04); ctx.lineTo(cx, top + h * 0.36); ctx.stroke();
    } else {
      roundRect(ctx, X(fx), Y(fy), fw * s, fh * s, (l.kind === "mousepad" ? 0.7 : 0.45) * s);
      ctx.fill(); ctx.stroke();
    }
    // LEDs
    l.dots.forEach((d, n) => {
      const [r, g, b] = col(n);
      const lit = r + g + b > 24;
      const cx = X(d[2]), cy = Y(d[3]);
      if (d[1] === "key") {
        const k = 0.8 * s;
        roundRect(ctx, cx - k / 2, cy - k / 2, k, k, 0.14 * s);
        ctx.fillStyle = lit ? `rgb(${r},${g},${b})` : "#151b25";
        ctx.shadowColor = lit ? `rgba(${r},${g},${b},.8)` : "transparent";
        ctx.shadowBlur = lit ? 0.5 * s : 0;
        ctx.fill();
        ctx.shadowBlur = 0;
      } else if (d[1] === "wheel") {
        const w = 0.42 * s, h = 1.0 * s;
        roundRect(ctx, cx - w / 2, cy - h / 2, w, h, w / 2);
        ctx.fillStyle = lit ? `rgb(${r},${g},${b})` : "#1a212c";
        ctx.fill();
      } else if (d[1] === "glow") {
        // drawn as the halo above
      } else {
        const rad = (d[1] === "logo" ? 0.5 : d[1] === "seg" ? 0.22 : 0.3) * s;
        ctx.beginPath(); ctx.arc(cx, cy, rad, 0, Math.PI * 2);
        ctx.fillStyle = lit ? `rgb(${r},${g},${b})` : "#1a212c";
        ctx.shadowColor = lit ? `rgba(${r},${g},${b},.9)` : "transparent";
        ctx.shadowBlur = lit ? 0.6 * s : 0;
        ctx.fill();
        ctx.shadowBlur = 0;
      }
    });
  }
}

/* ------------------------------------------------------------------ data loops */
async function loadLibrary() { try { LIB = await api().get_library(); } catch (e) { LIB = []; } }
async function loadLayout() { try { LAYOUT = await api().get_layout(); } catch (e) { /* keep old */ } }

async function refresh(force = false) {
  try {
    const next = await api().get_state();
    const before = lastSig;
    const ids = (S ? S.devices.map((d) => d.id).join() : "");
    S = next;
    lastSig = signature();
    if (S.devices.map((d) => d.id).join() !== ids) await loadLayout();
    if (S.library.join() !== LIB.map((l) => l.name).join()) await loadLibrary();
    if (!dragging && (force || lastSig !== before)) renderPage();
  } catch (e) { /* window closing */ }
}

let frameBusy = false;
async function frameLoop() {
  if (!frameBusy && !document.hidden && previews.length) {
    frameBusy = true;
    try { drawAll(await api().get_frame()); } catch (e) { /* ignore */ }
    frameBusy = false;
  }
}

async function boot() {
  renderShell();
  S = await api().get_state();
  lastSig = signature();
  await loadLayout();
  await loadLibrary();
  renderPage();
  $("#picker").addEventListener("input", onPicker);
  $("#picker").addEventListener("change", onPicker);
  setInterval(frameLoop, 50);
  setInterval(() => refresh(false), 1500);
  setInterval(pollButtons, 300);
  window.addEventListener("resize", () => drawAll(null));
}

window.addEventListener("pywebviewready", boot);
