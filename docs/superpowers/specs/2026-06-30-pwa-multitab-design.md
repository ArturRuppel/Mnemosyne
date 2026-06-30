# Design: Multitab support for the installed PWA

**Date:** 2026-06-30
**Status:** Approved (pending spec review)

## Summary

The catalog is an installable PWA (`display: "standalone"`) built from several
separate static HTML pages (`sdgl.html` / Data Explorer, `experiments.html`,
`reports.html`, `protocols.html`, `code.html`, `documents.html`,
`presentations.html`, `posters.html`). An installed standalone window has no
browser tab strip, so every cross-page link today does `window.location.href =
...`, replacing the whole window — there is no way to have the experiment tree
open in one place and a report open alongside it.

This design adds a custom, in-app tab strip to the **live server only**
(`eln admin` / `eln backup`). The static-export "share" bundle
(`eln/share.py`), which packages `sdgl.html` as a single self-contained
offline file, is untouched.

Chrome's native tabbed-window manifest feature (`display_override: ["tabbed"]`
+ `tab_strip`) was considered and rejected: it is ChromeOS-only at the
platform level, unavailable on desktop Chrome without manual flags, and
Firefox/WebKit have no plans to implement it.

## Goals

- Multiple catalog pages can be open at once in the installed PWA window, each
  in its own tab, switchable without losing state.
- Plain clicks behave like today (replace the active tab's content) — no
  surprise tab proliferation from browsing the nav bar.
- Middle-click / Ctrl-Cmd-click on any in-app link or tree row opens a new
  tab, mirroring normal browser conventions, instead of escaping the PWA to
  the default browser.
- Every generated page keeps working exactly as it does today when opened
  directly (bookmarked, shared, or inside the static-export bundle) — the tab
  shell is strictly additive.

## Non-goals

- No native browser/OS-level tabs.
- No drag-to-reorder tabs, no keyboard shortcuts (Ctrl+T/Ctrl+W), no tab
  overflow dropdown menu (the strip scrolls horizontally instead).
- No cross-tab state sync beyond what already exists.
- No change to `presentations.py`'s popup-window behavior or `posters.py`'s
  `target="_blank"` thumbnail links — those stay separate-window/asset
  behaviors, not part of the tab system.
- No change to the static-export/share bundle (`eln/share.py`) or to
  `sdgl.html`'s role as a self-contained single-file export.
- Tree scroll position / expansion state is not restored on shell reload —
  only which tabs were open.

## Architecture

- **New `catalog/shell.html`**: header + tab strip + a stack of `<iframe>`
  elements, one per open tab (only the active one visible; others are
  `display: none` so their state — scroll position, expanded tree nodes —
  survives a tab switch). This becomes the live-server's `/` route.
- **`eln/server/app.py`**: `serve_index()` serves `shell.html` instead of
  `sdgl.html` at `/`. `sdgl.html` remains reachable directly at `/sdgl.html`
  via the existing generic `/<page>.html` route, unchanged, and becomes the
  default/home tab's iframe content.
- **No other generated page is renamed, split, or moved.** Each keeps its own
  header/nav/content exactly as today, so it works standalone outside the
  shell (bookmark, share link, static-export bundle).
- **New `catalog/tabnav.js`**: a small shared script included by every
  generator alongside `forms.js`/`edit-overlay.js`. It detects whether the
  page is running inside the shell's iframe (e.g. `window.parent !==
  window.self` and a same-origin marker the shell sets) and exposes a
  `navigate(url, {newTab})` helper:
  - Inside the shell: `navigate()` posts a message to the parent shell, which
    either replaces the active tab's iframe `src` or opens/focuses a new tab.
  - Standalone (no shell): falls back to today's behavior
    (`window.location.href` / `window.open`).

## Click handling

- **Plain click** on a nav-bar link, a report-row click in the explorer tree,
  or an `xlink` cross-link: `navigate(url)` — replaces the active tab.
- **Middle-click or Ctrl/Cmd-click** on the same elements: `navigate(url,
  {newTab: true})` — opens a new tab and switches to it. This requires
  `tabnav.js` to intercept `auxclick` and modifier-clicks on both real `<a>`
  tags and the tree's clickable `<div>` rows, because a native middle-click
  on an anchor inside an iframe would otherwise try to pop a real top-level
  browser tab/window — the exact behavior that breaks out of the installed
  PWA today.
- `sdgl.html`'s existing report-row handler (currently `window.location.href
  = 'reports.html#${frag}'`) and the `xlink` anchors switch to calling
  `navigate()`.

## Tab lifecycle

- `+` button in the tab strip always opens a fresh Data Explorer tab
  (`/sdgl.html`) and focuses it.
- Each tab has a close button (×). Closing the last tab auto-opens a fresh
  Explorer tab — the shell is never left empty.
- Tab titles come from the loaded iframe's `<title>` (e.g. "Reports",
  "Protocols") — generic per page-type, since that's all generated pages
  currently expose; no per-item titles (e.g. a specific report's filename).
- The open tab list (URLs + titles only, not iframe-internal state)
  persists to `sessionStorage`, so an accidental shell reload doesn't lose
  the layout — each iframe reloads fresh on restore.
- No hard cap on tab count; the strip scrolls horizontally if it overflows.

## Files touched

- New: `catalog/shell.html`, `catalog/tabnav.js`.
- `eln/server/app.py`: `serve_index()` route change.
- `catalog/sdgl.html`: report-row click handler and `xlink` anchors switch to
  `navigate()`.
- Every generator calling `render_nav()` (`eln/generators/catalog.py`,
  `reports.py`, the protocols generator, `code.py`, `documents.py`,
  `presentations.py`, `posters.py`): add a `<script src="tabnav.js">` include.
- `catalog/manifest.webmanifest`: no change needed — `start_url`/`scope`
  stay `/`, which now resolves to the shell.

## Testing

- `tests/server/test_app.py`: update the `/` assertions to expect the shell
  (tab-strip markup, iframe pointing at `/sdgl.html`) instead of the
  Explorer content directly.
- `tests/test_share.py` and `tests/generators/test_nav.py`: expected
  unchanged, since `sdgl.html` and the shared nav block are untouched.
- No JS test framework exists in this repo; `tabnav.js`/`shell.html` behavior
  is verified manually (start the server, open multiple tabs, confirm
  plain-click vs. middle-click behavior, confirm standalone pages still work
  when opened directly).
