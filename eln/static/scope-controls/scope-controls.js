// scope-controls — shared layer and axis controls for microscopy viewers.
//
// Canonical copy: electronic_labbook/eln/static/scope-controls/. Viewers that
// use it (lab-book explorers, Cellpose Web) vendor this file and
// scope-controls.css unchanged; edit here and copy out.
//
// The module draws controls only. Each viewer supplies callbacks that talk to
// its own renderer, so a server-rendered PNG stack and a Luxar scene share the
// same widgets without sharing a backend.

export const VERSION = "1";

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

function digitsFor(span) {
  return span <= 2 ? 2 : span <= 20 ? 1 : 0;
}

// Format an elapsed quantity in the axis unit: 735 minute -> "12 h 15 min".
export function formatElapsed(value, unit, step = null) {
  if (!unit) return "";
  const u = unit.toLowerCase();
  const seconds = { second: 1, s: 1, sec: 1, minute: 60, min: 60, hour: 3600, h: 3600 }[u];
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
  const short = { micrometer: "µm", nanometer: "nm", millimeter: "mm" }[unit.toLowerCase()] || unit;
  return `${+value.toFixed(2)} ${short}`;
}

// A stepped axis (time or Z): −/+ buttons, slider, editable index, and an
// elapsed or physical readout. With `playable`, a play button loops the axis;
// it waits for a promise returned by onChange before scheduling the next step,
// so slow renderers are never outrun.
//
// options: { label, count, value, spacing, unit, playable, playDelay, onChange }
export function axisControl(container, options) {
  const opts = { value: 0, spacing: null, unit: null, playable: false, playDelay: 450, ...options };
  let count = opts.count, value = opts.value, playing = false, timer = null, token = 0;
  const isTime = /^t/i.test(opts.label);

  const slider = el("input", { class: "sc-slider", type: "range", min: 0, step: 1, "aria-label": opts.label });
  const index = el("input", { class: "sc-index", type: "number", min: 0, step: 1, inputmode: "numeric", "aria-label": `${opts.label} index` });
  const last = el("span", { class: "sc-last" });
  const physical = el("span", { class: "sc-physical" });
  const play = opts.playable
    ? el("button", { class: "sc-button sc-primary sc-play", type: "button", "aria-label": "Play", "aria-pressed": "false", text: "▶" })
    : null;
  const prev = el("button", { class: "sc-button", type: "button", "aria-label": `Previous ${opts.label}`, text: "−" });
  const next = el("button", { class: "sc-button", type: "button", "aria-label": `Next ${opts.label}`, text: "+" });

  const root = el("section", { class: `sc-axis${play ? " sc-axis-playable" : ""}`, "aria-label": opts.label },
    el("div", { class: "sc-axis-head" },
      el("strong", { text: opts.label }),
      el("span", { class: "sc-readout" }, index, last, physical)),
    el("div", { class: "sc-axis-row" }, prev, play, next, slider));
  container.append(root);

  function render() {
    slider.max = index.max = String(Math.max(0, count - 1));
    slider.value = index.value = String(value);
    last.textContent = ` / ${Math.max(0, count - 1)}`;
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
    if (!play) return;
    playing = on;
    token += 1;
    window.clearTimeout(timer);
    play.textContent = on ? "❚❚" : "▶";
    play.setAttribute("aria-label", on ? "Pause" : "Play");
    play.setAttribute("aria-pressed", String(on));
    if (on) step(token);
  }

  async function step(mine) {
    if (!playing || mine !== token) return;
    try { await set(value >= count - 1 ? 0 : value + 1); } catch { setPlaying(false); return; }
    if (playing && mine === token) timer = window.setTimeout(() => step(mine), opts.playDelay);
  }

  slider.addEventListener("input", () => set(slider.value));
  index.addEventListener("change", () => set(index.value));
  prev.addEventListener("click", () => set(value - 1));
  next.addEventListener("click", () => set(value + 1));
  play?.addEventListener("click", () => setPlaying(!playing));
  document.addEventListener("visibilitychange", () => { if (document.hidden) setPlaying(false); });
  render();

  return {
    get value() { return value; },
    get playing() { return playing; },
    set,
    setPlaying,
    configure(next) {
      Object.assign(opts, next);
      if (next.count !== undefined) count = next.count;
      if (next.value !== undefined) value = next.value;
      value = clamp(value, 0, Math.max(0, count - 1));
      render();
    },
    element: root,
  };
}

// A napari-style layer list: one row per layer (visibility, optional colour,
// name, kind) and an editor for the selected layer (contrast limits, gamma,
// opacity). Fields a layer lacks are hidden, so renderers opt in per feature.
//
// layer: { id, name, kind, visible, color?, dataRange?, limits?, gamma?, opacity? }
// options: { layers, selected, contrastCommit: "input" | "change", onChange(id, patch) }
// With contrastCommit "change", contrast is committed on release, for
// renderers where every contrast change costs a server round trip.
export function layerList(container, options) {
  const opts = { contrastCommit: "input", ...options };
  let layers = (opts.layers || []).map((layer) => ({ ...layer }));
  let selected = opts.selected ?? layers[0]?.id ?? null;

  const list = el("div", { class: "sc-layers", role: "listbox", "aria-label": "Layers" });
  const lowSlider = el("input", { class: "sc-slider", type: "range", "aria-label": "Contrast minimum" });
  const highSlider = el("input", { class: "sc-slider", type: "range", "aria-label": "Contrast maximum" });
  const lowNumber = el("input", { type: "number", inputmode: "decimal", "aria-label": "Contrast minimum value" });
  const highNumber = el("input", { type: "number", inputmode: "decimal", "aria-label": "Contrast maximum value" });
  const gamma = el("input", { class: "sc-slider", type: "range", min: 0.1, max: 3, step: 0.05, "aria-label": "Gamma" });
  const opacity = el("input", { class: "sc-slider", type: "range", min: 0, max: 1, step: 0.01, "aria-label": "Opacity" });
  const contrastValue = el("span", { class: "sc-value" });
  const gammaValue = el("span", { class: "sc-value" });
  const opacityValue = el("span", { class: "sc-value" });

  const contrastBlock = el("div", { class: "sc-control" },
    el("div", { class: "sc-control-head" }, el("span", { text: "Contrast limits" }), contrastValue),
    el("div", { class: "sc-pair" },
      el("label", { class: "sc-number" }, "Min", lowNumber),
      el("label", { class: "sc-number" }, "Max", highNumber)),
    lowSlider, highSlider);
  const gammaBlock = el("label", { class: "sc-control" },
    el("span", { class: "sc-control-head" }, el("span", { text: "Gamma" }), gammaValue), gamma);
  const opacityBlock = el("label", { class: "sc-control" },
    el("span", { class: "sc-control-head" }, el("span", { text: "Opacity" }), opacityValue), opacity);
  const editor = el("div", { class: "sc-editor" }, contrastBlock, gammaBlock, opacityBlock);
  container.append(list, editor);

  const current = () => layers.find((layer) => layer.id === selected) || null;

  function emit(id, patch) {
    const layer = layers.find((item) => item.id === id);
    if (layer) Object.assign(layer, patch);
    opts.onChange?.(id, patch);
  }

  function renderList() {
    list.replaceChildren(...layers.map((layer) => {
      const isSelected = layer.id === selected;
      const visible = el("input", { type: "checkbox", "aria-label": `Show ${layer.name}` });
      visible.checked = layer.visible !== false;
      visible.addEventListener("change", () => emit(layer.id, { visible: visible.checked }));
      let swatch = null;
      if (layer.color) {
        swatch = el("input", { class: "sc-swatch", type: "color", value: layer.color, "aria-label": `${layer.name} colour` });
        swatch.addEventListener("input", () => emit(layer.id, { color: swatch.value }));
      }
      const pick = el("button", { class: "sc-layer-name", type: "button",
        onclick: () => { selected = layer.id; renderList(); renderEditor(); } },
        el("span", { class: "sc-name", text: layer.name }),
        layer.kind ? el("span", { class: "sc-kind", text: layer.kind }) : null);
      return el("div", { class: "sc-layer", role: "option", "aria-selected": String(isSelected), "data-selected": String(isSelected) },
        el("label", { class: "sc-visibility", title: `Show or hide ${layer.name}` }, visible), swatch, pick);
    }));
  }

  function renderEditor() {
    const layer = current();
    editor.toggleAttribute("data-empty", !layer);
    if (!layer) return;
    const hasContrast = Array.isArray(layer.dataRange) && Array.isArray(layer.limits);
    contrastBlock.hidden = !hasContrast;
    if (hasContrast) {
      const [low, high] = layer.dataRange, span = Math.max(high - low, Number.EPSILON);
      const step = layer.step ?? (Number.isInteger(low) && Number.isInteger(high) && span > 100 ? 1 : span / 500);
      for (const input of [lowSlider, highSlider, lowNumber, highNumber]) {
        input.min = String(low); input.max = String(high); input.step = String(step);
      }
      lowSlider.value = lowNumber.value = String(layer.limits[0]);
      highSlider.value = highNumber.value = String(layer.limits[1]);
      const digits = digitsFor(span);
      contrastValue.textContent = `${layer.limits[0].toFixed(digits)} – ${layer.limits[1].toFixed(digits)}`;
    }
    gammaBlock.hidden = layer.gamma === undefined;
    if (layer.gamma !== undefined) { gamma.value = String(layer.gamma); gammaValue.textContent = Number(layer.gamma).toFixed(2); }
    opacityBlock.hidden = layer.opacity === undefined;
    if (layer.opacity !== undefined) { opacity.value = String(layer.opacity); opacityValue.textContent = `${Math.round(layer.opacity * 100)}%`; }
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
    if (commit) emit(layer.id, { limits: [low, high] });
    else layer.limits = [low, high];
    renderEditor();
  }

  const live = opts.contrastCommit === "input";
  for (const slider of [lowSlider, highSlider]) {
    slider.addEventListener("input", () => readContrast("slider", live));
    if (!live) slider.addEventListener("change", () => readContrast("slider", true));
  }
  for (const number of [lowNumber, highNumber]) number.addEventListener("change", () => readContrast("number", true));
  gamma.addEventListener("input", () => { const layer = current(); if (layer) { emit(layer.id, { gamma: Number(gamma.value) }); renderEditor(); } });
  opacity.addEventListener("input", () => { const layer = current(); if (layer) { emit(layer.id, { opacity: Number(opacity.value) }); renderEditor(); } });

  renderList();
  renderEditor();

  return {
    get layers() { return layers.map((layer) => ({ ...layer })); },
    get selected() { return selected; },
    setLayers(next, keepSelection = true) {
      layers = next.map((layer) => ({ ...layer }));
      if (!keepSelection || !layers.some((layer) => layer.id === selected)) selected = layers[0]?.id ?? null;
      renderList();
      renderEditor();
    },
    update(id, patch) {
      const layer = layers.find((item) => item.id === id);
      if (!layer) return;
      Object.assign(layer, patch);
      renderList();
      renderEditor();
    },
    element: editor,
  };
}
