// scope-controls — shared layer and dims controls for microscopy viewers.
//
// Canonical copy: electronic_labbook/eln/static/scope-controls/. Viewers that
// use it (lab-book explorers, ITASC Web) vendor this file and
// scope-controls.css unchanged; edit here and copy out.
//
// The layout follows napari: a layer-controls form for the selected layer
// (opacity, blending, contrast limits, auto-contrast, gamma, colormap) above a
// layer list whose top row is the layer drawn last, and one slider row per
// non-displayed dimension below the canvas. The module draws controls only;
// each viewer supplies callbacks that talk to its own renderer, so a
// server-rendered PNG stack and a Luxar scene share widgets, not a backend.

export const VERSION = "4";

// napari's image-layer blending modes, in napari's menu order.
export const BLENDINGS = ["translucent", "translucent_no_depth", "additive", "minimum", "opaque"];

// Single-hue ramps first, as in napari's colormap menu.
export const COLORMAPS = {
  gray: ["#000", "#fff"], red: ["#000", "#f00"], green: ["#000", "#0f0"], blue: ["#000", "#00f"],
  cyan: ["#000", "#0ff"], magenta: ["#000", "#f0f"], yellow: ["#000", "#ff0"], orange: ["#000", "#ff8000"],
  bop_blue: ["#000", "#0082ff"], bop_orange: ["#000", "#ff8c00"], bop_purple: ["#000", "#b43cff"],
  viridis: ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
  inferno: ["#000004", "#57106e", "#bc3754", "#f98e09", "#fcffa4"],
  magma: ["#000004", "#51127c", "#b73779", "#fc8961", "#fcfdbf"],
  plasma: ["#0d0887", "#7e03a8", "#cc4778", "#f89540", "#f0f921"],
  turbo: ["#30123b", "#4686fb", "#1ae4b6", "#a2fc3c", "#fabe39", "#e3440a", "#7a0403"],
  fire: ["#000", "#b40000", "#ff8000", "#ffff80", "#fff"],
  ice: ["#000", "#00306e", "#0080c0", "#80e0ff", "#fff"],
  phase: ["#a8780d", "#6a8b12", "#0f8f8c", "#5b6fd5", "#b653a8", "#a8780d"],
  RdBu: ["#67001f", "#d6604d", "#f7f7f7", "#4393c3", "#053061"],
  coolwarm: ["#3b4cc0", "#aac7fd", "#dddddd", "#f7b89c", "#b40426"],
  seismic: ["#00004c", "#0000ff", "#ffffff", "#ff0000", "#800000"],
  white: ["#fff", "#fff"],
};

export function colormapGradient(name, direction = "to right") {
  const stops = COLORMAPS[name] || COLORMAPS.gray;
  return `linear-gradient(${direction}, ${stops.join(", ")})`;
}

// 256-entry RGB lookup table for a colormap, for renderers that tint on the CPU.
export function colormapLut(name) {
  const stops = (COLORMAPS[name] || COLORMAPS.gray).map((hex) => {
    const h = hex.length === 4 ? hex.slice(1).split("").map((c) => c + c).join("") : hex.slice(1);
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  });
  const lut = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i += 1) {
    const x = (i / 255) * (stops.length - 1), k = Math.min(stops.length - 2, Math.floor(x)), f = x - k;
    for (let c = 0; c < 3; c += 1) lut[i * 3 + c] = stops[k][c] + (stops[k + 1][c] - stops[k][c]) * f;
  }
  return lut;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  node.append(...children.filter(Boolean));
  return node;
}

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const digitsFor = (span) => (span <= 2 ? 2 : span <= 20 ? 1 : 0);
const EYE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5C6.5 5 2.7 9.3 1.5 12c1.2 2.7 5 7 10.5 7s9.3-4.3 10.5-7C21.3 9.3 17.5 5 12 5zm0 11.5a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9zm0-2.2a2.3 2.3 0 1 0 0-4.6 2.3 2.3 0 0 0 0 4.6z"/></svg>';

// Format an elapsed quantity in the axis unit: 735 minute -> "12 h 15 min".
// `step` is the axis spacing, so frame 0 of a 15-min series reads "0 min".
export function formatElapsed(value, unit, step = null) {
  if (!unit) return "";
  const seconds = { second: 1, s: 1, sec: 1, minute: 60, min: 60, hour: 3600, h: 3600 }[unit.toLowerCase()];
  if (seconds === undefined) return `${+value.toFixed(3)} ${unit}`;
  const total = Math.round(value * seconds);
  if (total === 0) return (step ?? 1) * seconds >= 60 ? "0 min" : "0 s";
  const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
  if (h) return `${h} h ${String(m).padStart(2, "0")} min`;
  if (m) return s ? `${m} min ${s} s` : `${m} min`;
  return `${s} s`;
}

function formatSpatial(value, unit) {
  if (!unit) return "";
  const short = { micrometer: "µm", nanometer: "nm", millimeter: "mm", um: "µm" }[unit.toLowerCase()] || unit;
  return `${+value.toFixed(2)} ${short}`;
}

// One napari dims row: play, axis name, slider (with step buttons for touch),
// and "index / last" with the elapsed or physical position. Playback waits for
// a promise returned by onChange before scheduling the next step, so slow
// renderers are never outrun. As in napari, right-clicking (or long-pressing)
// play opens the playback settings: frames per second and loop mode.
//
// options: { label, name, count, value, spacing, unit, playable, fps, loop, onChange }
// loop: "loop" | "back_and_forth" | "once"
export const LOOP_MODES = { loop: "Loop", back_and_forth: "Back and forth", once: "Once" };

export function axisControl(container, options) {
  const opts = { value: 0, spacing: null, unit: null, playable: true, fps: 10, loop: "loop", ...options };
  let count = opts.count, value = opts.value, playing = false, timer = null, token = 0, direction = 1;
  const isTime = /^t/i.test(opts.name || opts.label);

  const slider = el("input", { class: "sc-slider", type: "range", min: 0, step: 1, "aria-label": opts.label });
  const index = el("input", { class: "sc-index", type: "number", min: 0, step: 1, inputmode: "numeric", "aria-label": `${opts.label} index` });
  const last = el("span", { class: "sc-last" });
  const physical = el("span", { class: "sc-physical" });
  const play = opts.playable
    ? el("button", { class: "sc-icon sc-play", type: "button", "aria-label": `Play ${opts.label}`, "aria-pressed": "false", text: "▶" })
    : el("span", { class: "sc-icon-spacer" });
  const prev = el("button", { class: "sc-icon sc-step", type: "button", "aria-label": `Previous ${opts.label}`, text: "‹" });
  const next = el("button", { class: "sc-icon sc-step", type: "button", "aria-label": `Next ${opts.label}`, text: "›" });

  const root = el("div", { class: "sc-dim", role: "group", "aria-label": opts.label },
    play,
    el("span", { class: "sc-dim-name", title: opts.label, text: opts.name || opts.label }),
    prev, slider, next,
    el("span", { class: "sc-readout" }, index, last, physical));
  container.append(root);

  const fpsInput = el("input", { type: "number", min: 0.5, max: 60, step: 0.5, inputmode: "decimal", "aria-label": "Frames per second" });
  const loopSelect = el("select", { "aria-label": "Loop mode" }, ...Object.entries(LOOP_MODES).map(([key, text]) => new Option(text, key)));
  const settings = el("div", { class: "sc-play-settings", role: "dialog", "aria-label": `${opts.label} playback`, hidden: true },
    el("label", {}, "fps", fpsInput), el("label", {}, "loop", loopSelect));
  root.append(settings);
  const syncSettings = () => { fpsInput.value = String(opts.fps); loopSelect.value = opts.loop; };
  function openSettings(open) {
    settings.hidden = !open;
    if (open) { syncSettings(); fpsInput.focus(); }
  }
  fpsInput.addEventListener("change", () => { const fps = Number(fpsInput.value); if (fps > 0) opts.fps = clamp(fps, 0.5, 60); syncSettings(); });
  loopSelect.addEventListener("change", () => { opts.loop = loopSelect.value; direction = 1; });
  settings.addEventListener("keydown", (event) => { if (event.key === "Escape") openSettings(false); });
  document.addEventListener("pointerdown", (event) => { if (!settings.hidden && !settings.contains(event.target) && event.target !== play) openSettings(false); });

  function render() {
    slider.max = index.max = String(Math.max(0, count - 1));
    slider.value = index.value = String(value);
    last.textContent = `/ ${Math.max(0, count - 1)}`;
    const amount = opts.spacing ? value * opts.spacing : null;
    physical.textContent = amount === null ? "" : isTime ? formatElapsed(amount, opts.unit, opts.spacing) : formatSpatial(amount, opts.unit);
    root.toggleAttribute("data-single", count <= 1);
  }

  function set(target, { emit = true } = {}) {
    const clamped = clamp(Math.round(Number(target) || 0), 0, Math.max(0, count - 1));
    const changed = clamped !== value;
    value = clamped;
    render();
    return emit && changed ? Promise.resolve(opts.onChange?.(value)) : Promise.resolve();
  }

  function setPlaying(on) {
    if (!opts.playable) return;
    playing = on && count > 1;
    token += 1;
    window.clearTimeout(timer);
    play.textContent = playing ? "❚❚" : "▶";
    play.setAttribute("aria-label", `${playing ? "Pause" : "Play"} ${opts.label}`);
    play.setAttribute("aria-pressed", String(playing));
    if (playing) step(token);
  }

  function nextFrame() {
    if (opts.loop === "back_and_forth") {
      if (value + direction > count - 1 || value + direction < 0) direction = -direction;
      return value + direction;
    }
    if (value >= count - 1) return opts.loop === "once" ? null : 0;
    return value + 1;
  }

  // The frame interval counts from the start of each step, so a slow renderer
  // lowers the rate but never queues frames.
  async function step(mine) {
    if (!playing || mine !== token) return;
    const started = performance.now(), target = nextFrame();
    if (target === null) { setPlaying(false); return; }
    try { await set(target); } catch { setPlaying(false); return; }
    const wait = Math.max(0, 1000 / opts.fps - (performance.now() - started));
    if (playing && mine === token) timer = window.setTimeout(() => step(mine), wait);
  }

  slider.addEventListener("input", () => set(slider.value));
  index.addEventListener("change", () => set(index.value));
  prev.addEventListener("click", () => set(value - 1));
  next.addEventListener("click", () => set(value + 1));
  if (opts.playable) {
    let pressTimer = null, longPressed = false;
    play.title = "Play · right-click or long-press for frame rate";
    play.addEventListener("click", () => { if (longPressed) { longPressed = false; return; } setPlaying(!playing); });
    play.addEventListener("contextmenu", (event) => { event.preventDefault(); if (!longPressed) openSettings(settings.hidden); });
    play.addEventListener("pointerdown", (event) => {
      if (event.pointerType !== "touch") return;
      pressTimer = window.setTimeout(() => { longPressed = true; openSettings(true); }, 500);
    });
    for (const type of ["pointerup", "pointercancel", "pointerleave"]) play.addEventListener(type, () => window.clearTimeout(pressTimer));
  }
  document.addEventListener("visibilitychange", () => { if (document.hidden) setPlaying(false); });
  render();

  return {
    get value() { return value; },
    get playing() { return playing; },
    get fps() { return opts.fps; },
    set,
    setPlaying,
    configure(changes) {
      Object.assign(opts, changes);
      if (changes.count !== undefined) count = changes.count;
      if (changes.value !== undefined) value = changes.value;
      value = clamp(value, 0, Math.max(0, count - 1));
      render();
    },
    element: root,
  };
}

// napari's layer dock: `controls` gets the form for the selected layer and
// `list` the layer list (top row = drawn last). Rows a layer does not define
// are hidden, so each renderer opts in per feature.
//
// layer: { id, name, kind, visible, group?, opacity?, blending?, blendings?, dataRange?,
//          limits?, exposure?, offset?, gamma?, colormap?, colormaps? }
// Layers sharing a `group` (keep a group's layers adjacent) are listed under one
// header that folds them away and shows or hides all of them at once; the
// header's eye is on while any member is visible. `groups` optionally names
// them and sets which start folded: [{ id, name?, collapsed? }].
// exposure (EV) and offset are a per-layer grade for renderers that window a
// layer themselves: the host maps them onto the layer (0 is neutral, and a
// double-click on either slider resets it).
// options: { controls, list, layers, groups, selected, colormaps, blendings, exposureRange,
//            contrastCommit: "input" | "change", autoContrast: "none" | "once" | "both",
//            onChange(id, patch), onSelect(id), onAutoContrast(id) -> [low, high] | Promise }
// With contrastCommit "change", contrast is committed on release, for
// renderers where every contrast change costs a server round trip. With
// autoContrast "both", the host re-runs onAutoContrast for layers where
// isContinuous(id) is true whenever the displayed slice changes.
export function layerPanel(options) {
  const opts = { contrastCommit: "input", autoContrast: "none", colormaps: Object.keys(COLORMAPS), blendings: BLENDINGS, ...options };
  let layers = (opts.layers || []).map((layer) => ({ ...layer }));
  let selected = opts.selected ?? layers.at(-1)?.id ?? null;
  const continuous = new Set();
  const groupInfo = new Map((opts.groups || []).map((group) => [group.id, group]));
  const collapsed = new Set((opts.groups || []).filter((group) => group.collapsed).map((group) => group.id));

  const opacity = el("input", { class: "sc-slider", type: "range", min: 0, max: 1, step: 0.01, "aria-label": "Opacity" });
  const opacityValue = el("span", { class: "sc-value" });
  const blending = el("select", { class: "sc-select", "aria-label": "Blending" });
  const lowSlider = el("input", { class: "sc-slider sc-range-low", type: "range", "aria-label": "Contrast minimum" });
  const highSlider = el("input", { class: "sc-slider sc-range-high", type: "range", "aria-label": "Contrast maximum" });
  const rangeFill = el("span", { class: "sc-range-fill" });
  const lowNumber = el("input", { type: "number", inputmode: "decimal", "aria-label": "Contrast minimum value" });
  const highNumber = el("input", { type: "number", inputmode: "decimal", "aria-label": "Contrast maximum value" });
  const limitsText = el("span", { class: "sc-value" });
  const more = el("button", { class: "sc-icon sc-more", type: "button", "aria-label": "Edit contrast limits", "aria-expanded": "false", text: "⋯" });
  const exact = el("div", { class: "sc-exact", hidden: true },
    el("label", {}, "min", lowNumber), el("label", {}, "max", highNumber));
  const once = el("button", { class: "sc-chip", type: "button", text: "once" });
  const cont = el("button", { class: "sc-chip", type: "button", "aria-pressed": "false", text: "continuous" });
  const [exposureMin, exposureMax] = opts.exposureRange || [-8, 8];
  const exposure = el("input", { class: "sc-slider", type: "range", min: exposureMin, max: exposureMax, step: 0.1, "aria-label": "Exposure", title: "Double-click to reset" });
  const exposureValue = el("span", { class: "sc-value" });
  const offset = el("input", { class: "sc-slider", type: "range", min: -1, max: 1, step: 0.01, "aria-label": "Offset", title: "Double-click to reset" });
  const offsetValue = el("span", { class: "sc-value" });
  const gamma = el("input", { class: "sc-slider", type: "range", min: 0.2, max: 2, step: 0.01, "aria-label": "Gamma" });
  const gammaValue = el("span", { class: "sc-value" });
  const colormap = el("select", { class: "sc-select", "aria-label": "Colormap" });
  const colormapSwatch = el("span", { class: "sc-colormap-swatch" });

  const row = (label, ...widgets) => el("div", { class: "sc-row" }, el("span", { class: "sc-row-label", text: label }), el("div", { class: "sc-row-widget" }, ...widgets));
  const rows = {
    opacity: row("opacity:", el("div", { class: "sc-inline" }, opacity, opacityValue)),
    blending: row("blending:", blending),
    limits: row("contrast limits:",
      el("div", { class: "sc-inline" }, el("div", { class: "sc-range" }, rangeFill, lowSlider, highSlider), more),
      el("div", { class: "sc-limits-text" }, limitsText), exact),
    auto: row("auto-contrast:", el("div", { class: "sc-chips" }, once, opts.autoContrast === "both" ? cont : null)),
    exposure: row("exposure:", el("div", { class: "sc-inline" }, exposure, exposureValue)),
    offset: row("offset:", el("div", { class: "sc-inline" }, offset, offsetValue)),
    gamma: row("gamma:", el("div", { class: "sc-inline" }, gamma, gammaValue)),
    colormap: row("colormap:", el("div", { class: "sc-inline" }, colormapSwatch, colormap)),
  };
  const title = el("div", { class: "sc-controls-title" });
  const form = el("div", { class: "sc-controls" }, title, ...Object.values(rows));
  const list = el("div", { class: "sc-layers", role: "listbox", "aria-label": "Layers" });
  opts.controls.append(form);
  opts.list.append(list);

  const current = () => layers.find((layer) => layer.id === selected) || null;

  function emit(id, patch) {
    const layer = layers.find((item) => item.id === id);
    if (layer) Object.assign(layer, patch);
    opts.onChange?.(id, patch);
  }

  function groupHeader(id, members) {
    const shown = members.filter((layer) => layer.visible !== false).length;
    const folded = collapsed.has(id), name = groupInfo.get(id)?.name ?? id;
    const eye = el("button", { class: "sc-eye", type: "button", "aria-pressed": String(shown > 0),
      "aria-label": `${shown ? "Hide" : "Show"} all of ${name}` });
    eye.innerHTML = EYE;
    eye.addEventListener("click", (event) => {
      event.stopPropagation();
      const visible = shown === 0;
      for (const layer of members) if ((layer.visible !== false) !== visible) emit(layer.id, { visible });
      renderList();
    });
    const toggle = () => { if (folded) collapsed.delete(id); else collapsed.add(id); renderList(); };
    const header = el("div", { class: "sc-group", role: "button", tabindex: 0, "aria-expanded": String(!folded),
      "data-hidden": String(shown === 0) },
      el("span", { class: "sc-caret", "aria-hidden": "true", text: folded ? "▸" : "▾" }), eye,
      el("span", { class: "sc-name", text: name }),
      el("span", { class: "sc-count", text: `${shown}/${members.length}` }));
    header.addEventListener("click", toggle);
    header.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggle(); } });
    return header;
  }

  // Top row first; a group's header goes where its first listed member would.
  function renderList() {
    const rows = [], headed = new Set();
    for (const layer of [...layers].reverse()) {
      const group = layer.group;
      if (group != null && !headed.has(group)) {
        headed.add(group);
        rows.push(groupHeader(group, layers.filter((item) => item.group === group)));
      }
      if (group != null && collapsed.has(group)) continue;
      rows.push(layerRow(layer));
    }
    list.replaceChildren(...rows);
  }

  function layerRow(layer) {
    {
      const isSelected = layer.id === selected;
      const eye = el("button", { class: "sc-eye", type: "button", "aria-pressed": String(layer.visible !== false),
        "aria-label": `${layer.visible !== false ? "Hide" : "Show"} ${layer.name}` });
      eye.innerHTML = EYE;
      eye.addEventListener("click", (event) => { event.stopPropagation(); emit(layer.id, { visible: layer.visible === false }); renderList(); });
      const thumb = el("span", { class: "sc-thumb" });
      thumb.style.background = layer.colormap ? colormapGradient(layer.colormap, "to top right") : "var(--sc-surface-2)";
      const item = el("div", { class: "sc-layer", role: "option", tabindex: 0, "aria-selected": String(isSelected), "data-selected": String(isSelected),
        "data-hidden": String(layer.visible === false) },
        eye, thumb,
        el("span", { class: "sc-layer-text" },
          el("span", { class: "sc-name", text: layer.name }),
          layer.kind ? el("span", { class: "sc-kind", text: layer.kind }) : null));
      const choose = () => { const changed = selected !== layer.id; selected = layer.id; renderList(); renderControls(); if (changed) opts.onSelect?.(selected); };
      item.addEventListener("click", choose);
      item.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(); } });
      if (layer.group != null) item.dataset.grouped = "true";
      return item;
    }
  }

  function fillSelect(select, values, currentValue, label = (v) => v) {
    const key = values.join("|");
    if (select.dataset.options !== key) {
      select.replaceChildren(...values.map((v) => new Option(label(v), v)));
      select.dataset.options = key;
    }
    select.value = currentValue;
  }

  function renderControls() {
    const layer = current();
    form.toggleAttribute("data-empty", !layer);
    title.textContent = layer ? layer.name : "No layer selected";
    if (!layer) return;
    rows.opacity.hidden = layer.opacity === undefined;
    if (layer.opacity !== undefined) { opacity.value = String(layer.opacity); opacityValue.textContent = Number(layer.opacity).toFixed(2); }
    const blendings = layer.blendings || opts.blendings;
    rows.blending.hidden = layer.blending === undefined || !blendings.length;
    if (!rows.blending.hidden) fillSelect(blending, blendings, layer.blending);
    const hasLimits = Array.isArray(layer.dataRange) && Array.isArray(layer.limits);
    rows.limits.hidden = !hasLimits;
    rows.auto.hidden = !hasLimits || opts.autoContrast === "none";
    if (hasLimits) {
      const [low, high] = layer.dataRange, span = Math.max(high - low, Number.EPSILON);
      const step = layer.step ?? (Number.isInteger(low) && Number.isInteger(high) && span > 100 ? 1 : span / 500);
      for (const input of [lowSlider, highSlider, lowNumber, highNumber]) {
        input.min = String(low); input.max = String(high); input.step = String(step);
      }
      lowSlider.value = lowNumber.value = String(layer.limits[0]);
      highSlider.value = highNumber.value = String(layer.limits[1]);
      rangeFill.style.left = `${((layer.limits[0] - low) / span) * 100}%`;
      rangeFill.style.right = `${100 - ((layer.limits[1] - low) / span) * 100}%`;
      const digits = digitsFor(span);
      limitsText.textContent = `${layer.limits[0].toFixed(digits)} – ${layer.limits[1].toFixed(digits)}  (range ${low.toFixed(digits)} – ${high.toFixed(digits)})`;
      cont.setAttribute("aria-pressed", String(continuous.has(layer.id)));
    }
    rows.exposure.hidden = layer.exposure === undefined;
    if (layer.exposure !== undefined) { exposure.value = String(layer.exposure); exposureValue.textContent = `${Number(layer.exposure).toFixed(1)} EV`; }
    rows.offset.hidden = layer.offset === undefined;
    if (layer.offset !== undefined) { offset.value = String(layer.offset); offsetValue.textContent = Number(layer.offset).toFixed(2); }
    rows.gamma.hidden = layer.gamma === undefined;
    if (layer.gamma !== undefined) { gamma.value = String(layer.gamma); gammaValue.textContent = Number(layer.gamma).toFixed(2); }
    const colormaps = layer.colormaps || opts.colormaps;
    rows.colormap.hidden = layer.colormap === undefined || !colormaps.length;
    if (!rows.colormap.hidden) {
      fillSelect(colormap, colormaps, layer.colormap);
      colormapSwatch.style.background = colormapGradient(layer.colormap);
    }
  }

  function readContrast(source, commit) {
    const layer = current();
    if (!layer?.dataRange) return;
    const [dataLow, dataHigh] = layer.dataRange;
    let low = Number(source === "number" ? lowNumber.value : lowSlider.value);
    let high = Number(source === "number" ? highNumber.value : highSlider.value);
    const gap = Math.max((dataHigh - dataLow) / 500, Number.EPSILON);
    if (low > high - gap) {
      if (document.activeElement === lowSlider || document.activeElement === lowNumber) low = high - gap;
      else high = low + gap;
    }
    low = clamp(low, dataLow, dataHigh);
    high = clamp(high, dataLow, dataHigh);
    continuous.delete(layer.id);
    if (commit) emit(layer.id, { limits: [low, high] });
    else layer.limits = [low, high];
    renderControls();
  }

  async function autoContrast(id) {
    const result = await opts.onAutoContrast?.(id);
    const layer = layers.find((item) => item.id === id);
    if (!layer || !Array.isArray(result)) return;
    let [low, high] = result;
    if (!(high > low)) high = low + 1;
    const range = layer.dataRange || [low, high];
    const patch = { limits: [low, high] };
    if (low < range[0] || high > range[1]) patch.dataRange = [Math.min(range[0], low), Math.max(range[1], high)];
    Object.assign(layer, patch);
    opts.onChange?.(id, { limits: patch.limits });
    if (id === selected) renderControls();
  }

  opacity.addEventListener("input", () => { const layer = current(); if (layer) { emit(layer.id, { opacity: Number(opacity.value) }); renderControls(); } });
  blending.addEventListener("change", () => { const layer = current(); if (layer) emit(layer.id, { blending: blending.value }); });
  const live = opts.contrastCommit === "input";
  for (const slider of [lowSlider, highSlider]) {
    slider.addEventListener("input", () => readContrast("slider", live));
    if (!live) slider.addEventListener("change", () => readContrast("slider", true));
  }
  for (const number of [lowNumber, highNumber]) number.addEventListener("change", () => readContrast("number", true));
  more.addEventListener("click", () => { exact.hidden = !exact.hidden; more.setAttribute("aria-expanded", String(!exact.hidden)); });
  once.addEventListener("click", () => { const layer = current(); if (layer) { continuous.delete(layer.id); autoContrast(layer.id); } });
  cont.addEventListener("click", () => {
    const layer = current(); if (!layer) return;
    if (continuous.has(layer.id)) continuous.delete(layer.id); else { continuous.add(layer.id); autoContrast(layer.id); }
    renderControls();
  });
  for (const [slider, key] of [[exposure, "exposure"], [offset, "offset"]]) {
    const commit = (value) => { const layer = current(); if (layer) { emit(layer.id, { [key]: value }); renderControls(); } };
    slider.addEventListener("input", () => commit(Number(slider.value)));
    slider.addEventListener("dblclick", () => commit(0));
  }
  gamma.addEventListener("input", () => { const layer = current(); if (layer) { emit(layer.id, { gamma: Number(gamma.value) }); renderControls(); } });
  colormap.addEventListener("change", () => { const layer = current(); if (layer) { emit(layer.id, { colormap: colormap.value }); renderControls(); renderList(); } });

  renderList();
  renderControls();

  return {
    get layers() { return layers.map((layer) => ({ ...layer })); },
    get selected() { return selected; },
    isContinuous: (id) => continuous.has(id),
    autoContrast,
    setLayers(next, keepSelection = true) {
      const previous = selected;
      layers = next.map((layer) => ({ ...layer }));
      for (const id of [...continuous]) if (!layers.some((layer) => layer.id === id)) continuous.delete(id);
      if (!keepSelection || !layers.some((layer) => layer.id === selected)) selected = layers.at(-1)?.id ?? null;
      renderList();
      renderControls();
      if (selected !== previous) opts.onSelect?.(selected);
    },
    select(id) {
      if (!layers.some((layer) => layer.id === id) || id === selected) return;
      selected = id;
      renderList();
      renderControls();
      opts.onSelect?.(selected);
    },
    update(id, patch) {
      const layer = layers.find((item) => item.id === id);
      if (!layer) return;
      Object.assign(layer, patch);
      renderList();
      renderControls();
    },
  };
}

// A draggable divider that sizes a panel through a CSS custom property on
// <html>, e.g. --sc-dock-width. `edge` is where the handle sits relative to the
// panel ("right", "left", "bottom"), which decides the drag direction.
// Double-click restores the default; arrow keys nudge. Sizes persist per
// viewer in localStorage when it is available.
//
// options: { panel, property, edge, min, max, storageKey, onResize }
export function splitter(handle, options) {
  const opts = { edge: "right", min: 160, max: 900, ...options };
  const vertical = opts.edge === "bottom";
  const root = document.documentElement;
  const read = () => { try { return window.localStorage.getItem(opts.storageKey); } catch { return null; } };
  const write = (v) => { try { if (v === null) window.localStorage.removeItem(opts.storageKey); else window.localStorage.setItem(opts.storageKey, v); } catch { /* storage unavailable */ } };
  const size = () => { const box = opts.panel.getBoundingClientRect(); return vertical ? box.height : box.width; };
  function apply(px, persist = true) {
    const limit = typeof opts.max === "function" ? opts.max() : opts.max;
    const value = `${Math.round(clamp(px, opts.min, Math.max(opts.min, limit)))}px`;
    root.style.setProperty(opts.property, value);
    if (persist && opts.storageKey) write(value);
    opts.onResize?.();
  }
  handle.classList.add("sc-splitter", vertical ? "sc-splitter-y" : "sc-splitter-x");
  handle.setAttribute("role", "separator");
  handle.setAttribute("tabindex", "0");
  handle.setAttribute("aria-orientation", vertical ? "horizontal" : "vertical");
  handle.title = "Drag to resize · double-click to reset";
  const saved = opts.storageKey && read();
  if (saved) root.style.setProperty(opts.property, saved);

  const sign = opts.edge === "left" ? -1 : 1;
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    const start = vertical ? event.clientY : event.clientX, from = size();
    handle.dataset.dragging = "true";
    document.body.style.cursor = vertical ? "row-resize" : "col-resize";
    const move = (e) => apply(from + sign * ((vertical ? e.clientY : e.clientX) - start), false);
    const end = (e) => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      delete handle.dataset.dragging;
      document.body.style.cursor = "";
      apply(size());
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  });
  handle.addEventListener("dblclick", () => { root.style.removeProperty(opts.property); write(null); opts.onResize?.(); });
  handle.addEventListener("keydown", (event) => {
    const grow = vertical ? "ArrowDown" : (opts.edge === "left" ? "ArrowLeft" : "ArrowRight");
    const shrink = vertical ? "ArrowUp" : (opts.edge === "left" ? "ArrowRight" : "ArrowLeft");
    if (event.key !== grow && event.key !== shrink) return;
    event.preventDefault();
    apply(size() + (event.key === grow ? 16 : -16));
  });
}
