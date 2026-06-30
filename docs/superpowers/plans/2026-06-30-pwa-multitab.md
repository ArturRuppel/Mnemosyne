# PWA Multitab Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the installed catalog PWA a custom in-app tab strip so multiple pages can be open at once, without breaking any page's standalone behavior or the static-export share bundle.

**Architecture:** A new `catalog/shell.html` (tab strip + a stack of `<iframe>`s, one per open tab) becomes the live server's `/` route, replacing `sdgl.html` there. `sdgl.html` and every other generated page are untouched in content and keep working standalone at their own `/<page>.html` route — they just gain a `<script src="tabnav.js">` include. `tabnav.js` is a small shared script: inside the shell it turns clicks into `postMessage`s the shell uses to replace the active tab or open a new one; outside the shell it falls back to today's `window.location.href` / `window.open` behavior, so nothing changes for bookmarked pages or the share bundle.

**Tech Stack:** Flask (`eln/server/app.py`), Python generator modules (`eln/generators/`), vanilla JS (no framework, no JS test runner — this repo has neither).

**Verification note:** There is no JS test framework in this repo (confirmed in `docs/superpowers/specs/2026-06-30-pwa-multitab-design.md`, Testing section). Python-side changes (routing, nav href, tests) follow red/green TDD with `pytest`. `shell.html`/`tabnav.js` themselves are verified by hand at two checkpoints (Task 6 and Task 8) — start the real server and click through it in Chromium.

---

## Task 1: Create `catalog/tabnav.js`

**Files:**
- Create: `catalog/tabnav.js`

This is the shared script every generated/static page includes. It detects whether it's running inside the shell's iframe and exposes `navigate(url, {newTab})`; it also delegates click/middle-click/Ctrl-Cmd-click handling for every in-app link (real `<a href>` tags, plus any element marked with `data-nav-href` for the rare case — `sdgl.html`'s report-tree rows — where the clickable element isn't a real anchor).

- [ ] **Step 1: Write the file**

```javascript
// Shared by every generated/static catalog page. Provides navigate(url, opts)
// and intercepts clicks so that, inside the installed PWA's tab shell, plain
// clicks replace the active tab and middle-click/Ctrl-Cmd-click open a new
// tab — mirroring normal browser tab conventions instead of escaping the PWA.
// Outside the shell (bookmarked page, share bundle) it falls back to the
// page's pre-shell behavior: full-window navigation / a real new browser tab.
(function () {
    'use strict';

    var inShell = false;
    try {
        inShell = window.parent !== window.self && window.parent.__ELN_SHELL__ === true;
    } catch (e) {
        inShell = false;
    }

    window.navigate = function (url, opts) {
        opts = opts || {};
        if (inShell) {
            window.parent.postMessage(
                {type: 'tabnav:navigate', url: url, newTab: !!opts.newTab},
                window.location.origin
            );
        } else if (opts.newTab) {
            window.open(url, '_blank');
        } else {
            window.location.href = url;
        }
    };

    if (inShell) {
        // Tells the shell what to show as this tab's title. Sent once per
        // load since generated pages don't change <title> after load.
        window.addEventListener('load', function () {
            window.parent.postMessage(
                {type: 'tabnav:title', title: document.title},
                window.location.origin
            );
        });
    }

    // Find the in-app navigation target for a click, or null if this click
    // isn't ours to handle (external link, anchor-only "#" link, an <a>
    // with an explicit target other than _self/"").
    function resolveTarget(el) {
        var a = el.closest && el.closest('a[href]');
        if (a) {
            if (a.target && a.target !== '_self') return null;
            var href = a.getAttribute('href');
            if (!href || href.charAt(0) === '#') return null;
            if (/^(https?:)?\/\//i.test(href) || href.indexOf('mailto:') === 0
                || href.indexOf('tel:') === 0) return null;
            return href;
        }
        // Non-anchor clickable elements (e.g. the explorer tree's report
        // rows) expose their target via data-nav-href instead of a real
        // href, since a <div> has no native click-to-navigate behavior to
        // intercept in the first place.
        var marked = el.closest && el.closest('[data-nav-href]');
        if (marked) return marked.dataset.navHref;
        return null;
    }

    document.addEventListener('click', function (e) {
        if (e.defaultPrevented || e.button !== 0) return;
        var url = resolveTarget(e.target);
        if (!url) return;
        e.preventDefault();
        navigate(url, {newTab: e.ctrlKey || e.metaKey});
    });

    document.addEventListener('auxclick', function (e) {
        if (e.button !== 1) return; // middle button only
        var url = resolveTarget(e.target);
        if (!url) return;
        e.preventDefault();
        navigate(url, {newTab: true});
    });
})();
```

- [ ] **Step 2: Commit**

```bash
git add catalog/tabnav.js
git commit -m "feat(pwa): add tabnav.js navigation helper for the tab shell"
```

---

## Task 2: Create `catalog/shell.html`

**Files:**
- Create: `catalog/shell.html`

The tab strip + iframe stack itself. Owns tab state (`{id, url, title}` per tab), persists the open-tab list (URLs + titles only) to `sessionStorage`, and listens for the `postMessage`s `tabnav.js` sends from inside each iframe.

- [ ] **Step 1: Write the file**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lab Notebook</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body { height: 100%; }
        body {
            display: flex; flex-direction: column;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #eef1f4;
        }
        .tab-strip {
            display: flex; align-items: stretch; background: #263646;
            overflow-x: auto; flex: 0 0 auto;
        }
        .tab {
            display: flex; align-items: center; gap: 0.5rem;
            padding: 0.55rem 0.6rem 0.55rem 0.9rem;
            color: #d7e0e7; cursor: pointer; white-space: nowrap;
            border-right: 1px solid #1b2733; max-width: 16rem; flex: 0 0 auto;
        }
        .tab.active { background: #eef1f4; color: #27313a; }
        .tab-title { overflow: hidden; text-overflow: ellipsis; }
        .tab-close {
            border: none; background: transparent; color: inherit; font-size: 1rem;
            line-height: 1; cursor: pointer; padding: 0.1rem 0.3rem; border-radius: 4px;
        }
        .tab-close:hover { background: rgba(0, 0, 0, 0.15); }
        .tab-new {
            flex: 0 0 auto; border: none; background: transparent; color: #d7e0e7;
            font-size: 1.1rem; padding: 0.55rem 0.9rem; cursor: pointer;
        }
        .tab-new:hover { background: rgba(255, 255, 255, 0.08); }
        .iframe-stack { flex: 1 1 auto; position: relative; }
        .iframe-stack iframe {
            position: absolute; inset: 0; width: 100%; height: 100%; border: none;
        }
    </style>
</head>
<body>
    <div class="tab-strip" id="tab-strip"></div>
    <div class="iframe-stack" id="iframe-stack"></div>
    <script>
        // Same-origin marker tabnav.js checks via window.parent.__ELN_SHELL__
        // to tell whether it's running inside this shell or standalone.
        window.__ELN_SHELL__ = true;

        var STORAGE_KEY = 'eln-shell-tabs';
        var DEFAULT_URL = '/sdgl.html';
        var DEFAULT_TITLE = 'Data Explorer';

        var tabs = [];
        var activeId = null;
        var nextId = 1;

        function genId() { return 'tab-' + (nextId++); }

        function loadState() {
            var raw;
            try { raw = sessionStorage.getItem(STORAGE_KEY); } catch (e) { raw = null; }
            if (raw) {
                try {
                    var parsed = JSON.parse(raw);
                    if (parsed && Array.isArray(parsed.tabs) && parsed.tabs.length) {
                        tabs = parsed.tabs;
                        nextId = parsed.nextId || (tabs.length + 1);
                        activeId = parsed.activeId && tabs.some(function (t) { return t.id === parsed.activeId; })
                            ? parsed.activeId : tabs[0].id;
                        return;
                    }
                } catch (e) { /* malformed; fall through to a fresh default tab */ }
            }
            var id = genId();
            tabs = [{id: id, url: DEFAULT_URL, title: DEFAULT_TITLE}];
            activeId = id;
        }

        function saveState() {
            try {
                sessionStorage.setItem(STORAGE_KEY,
                    JSON.stringify({tabs: tabs, activeId: activeId, nextId: nextId}));
            } catch (e) { /* sessionStorage unavailable; tabs just won't persist */ }
        }

        function findTab(id) {
            for (var i = 0; i < tabs.length; i++) if (tabs[i].id === id) return tabs[i];
            return null;
        }

        function createTab(url) {
            var id = genId();
            tabs.push({id: id, url: url, title: url});
            activeId = id;
            saveState();
            render();
        }

        function closeTab(id) {
            var idx = tabs.findIndex(function (t) { return t.id === id; });
            if (idx === -1) return;
            tabs.splice(idx, 1);
            if (!tabs.length) {
                // The shell is never left empty.
                var freshId = genId();
                tabs = [{id: freshId, url: DEFAULT_URL, title: DEFAULT_TITLE}];
                activeId = freshId;
            } else if (activeId === id) {
                activeId = tabs[Math.max(0, idx - 1)].id;
            }
            saveState();
            render();
        }

        function setActiveTab(id) {
            if (!findTab(id)) return;
            activeId = id;
            saveState();
            render();
        }

        function setActiveTabUrl(url) {
            var tab = findTab(activeId);
            if (!tab) return;
            tab.url = url;
            tab.title = url; // placeholder until the loaded page posts its real <title>
            saveState();
            render();
        }

        function renderTabStrip() {
            var strip = document.getElementById('tab-strip');
            strip.innerHTML = '';
            tabs.forEach(function (tab) {
                var el = document.createElement('div');
                el.className = 'tab' + (tab.id === activeId ? ' active' : '');
                el.addEventListener('click', function () { setActiveTab(tab.id); });

                var title = document.createElement('span');
                title.className = 'tab-title';
                title.textContent = tab.title;
                el.appendChild(title);

                var close = document.createElement('button');
                close.className = 'tab-close';
                close.textContent = '×';
                close.title = 'Close tab';
                close.addEventListener('click', function (e) {
                    e.stopPropagation();
                    closeTab(tab.id);
                });
                el.appendChild(close);

                strip.appendChild(el);
            });

            var newBtn = document.createElement('button');
            newBtn.className = 'tab-new';
            newBtn.textContent = '+';
            newBtn.title = 'New Data Explorer tab';
            newBtn.addEventListener('click', function () { createTab(DEFAULT_URL); });
            strip.appendChild(newBtn);
        }

        function renderIframes() {
            var stack = document.getElementById('iframe-stack');
            var frames = {};
            Array.prototype.forEach.call(stack.querySelectorAll('iframe'), function (f) {
                frames[f.dataset.tabId] = f;
            });
            tabs.forEach(function (tab) {
                var frame = frames[tab.id];
                if (!frame) {
                    frame = document.createElement('iframe');
                    frame.dataset.tabId = tab.id;
                    stack.appendChild(frame);
                } else {
                    delete frames[tab.id];
                }
                // Re-assigning the same resolved URL is a no-op (no reload),
                // so it's safe to do this unconditionally on every render —
                // only an actual URL change navigates the iframe.
                frame.src = tab.url;
                frame.style.display = tab.id === activeId ? 'block' : 'none';
            });
            // Anything left in `frames` belonged to a tab that just closed.
            Object.keys(frames).forEach(function (id) { frames[id].remove(); });
        }

        function render() {
            renderTabStrip();
            renderIframes();
        }

        window.addEventListener('message', function (e) {
            if (e.origin !== window.location.origin) return;
            var data = e.data || {};
            if (data.type === 'tabnav:navigate') {
                if (data.newTab) {
                    createTab(data.url);
                } else {
                    setActiveTabUrl(data.url);
                }
            } else if (data.type === 'tabnav:title') {
                var stack = document.getElementById('iframe-stack');
                var frame = Array.prototype.find.call(stack.querySelectorAll('iframe'),
                    function (f) { return f.contentWindow === e.source; });
                if (!frame) return;
                var tab = findTab(frame.dataset.tabId);
                if (!tab) return;
                tab.title = data.title;
                saveState();
                renderTabStrip();
            }
        });

        loadState();
        render();
    </script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add catalog/shell.html
git commit -m "feat(pwa): add the tab-strip shell shell.html"
```

---

## Task 3: Serve the shell at `/`

**Files:**
- Modify: `eln/server/app.py:169-211` (`serve_html_with_overlay`, `serve_index`, and the static-asset routes)
- Test: `tests/server/test_app.py`

`serve_index()` switches from serving `sdgl.html` to serving `shell.html`. The shell is chrome, not a content page — it has no Export/Add forms of its own, and the overlay toolbar is `position: fixed`, so injecting it into the shell would float a second copy on top of whichever iframe's own (correct) copy is already showing. `serve_html_with_overlay` is changed to skip the overlay injection specifically for `shell.html`. A new `/tabnav.js` route serves the file from Task 1, alongside the existing `/forms.js` route.

- [ ] **Step 1: Write the failing tests**

In `tests/server/test_app.py`, replace the existing `test_index_serves_sdgl_with_overlay` (currently around line 507) with two tests — one for `/sdgl.html` keeping today's overlay behavior, one for `/` now serving the shell without it:

```python
def test_sdgl_page_served_with_overlay(client):
    resp = client.get("/sdgl.html")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "edit-overlay.js" in html          # overlay injected
    assert '<script src="auth.js">' not in html  # auth stripped

    assert client.get("/auth.js").get_data(as_text=True).startswith("// auth disabled")
    assert client.get("/edit-overlay.js").status_code == 200


def test_index_serves_shell_without_overlay(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="tab-strip"' in html
    assert 'id="iframe-stack"' in html
    assert "edit-overlay.js" not in html      # shell chrome has no per-page overlay


def test_tabnav_js_served(client):
    assert client.get("/tabnav.js").status_code == 200
```

Also update `test_sdgl_page_carries_inline_header_logo` (currently around line 398) to hit `/sdgl.html` instead of `/`, since that header markup lives in `sdgl.html` itself, not the shell:

```python
def test_sdgl_page_carries_inline_header_logo(client):
    # The header shows the inline notebook logo, the brand title, and the
    # page-specific name as a subtitle.
    html = client.get("/sdgl.html").get_data(as_text=True)
    assert 'viewBox="0 0 64 64"' in html
    assert "<h1>Electronic Lab Notebook</h1>" in html
    assert ">Data Explorer</p>" in html
```

`test_served_page_is_installable` and `test_served_page_links_brand_favicon` (both hit `/`) need no changes — the PWA head snippet is injected unconditionally, so they keep passing once `/` serves any HTML page with a `</head>`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/server/test_app.py -k "sdgl_page_served_with_overlay or index_serves_shell_without_overlay or tabnav_js_served or inline_header_logo" -v
```

Expected: `test_sdgl_page_served_with_overlay` passes already (no change needed there yet), but `test_index_serves_shell_without_overlay` FAILs (no `tab-strip` id in current `/` output), `test_tabnav_js_served` FAILs with 404, and `test_sdgl_page_carries_inline_header_logo` passes already since `/sdgl.html` already serves that content today. The two genuinely-new failures are the shell ones — that's expected at this point.

- [ ] **Step 3: Implement the route changes**

In `eln/server/app.py`, modify `serve_html_with_overlay` (around line 169-189):

```python
    def serve_html_with_overlay(filename):
        """Serve a generated page (from the data root) or a static frontend
        asset (from the code repo) with the edit overlay injected."""
        if filename in generated_pages:
            filepath = catalog_dir / filename
        else:
            filepath = assets / filename
        if not filepath.exists():
            return "Not found", 404
        html = filepath.read_text(encoding="utf-8")
        # Strip auth.js (no password prompt locally), make the page installable as
        # a PWA (head), and inject the edit overlay (body).
        html = _AUTH_SCRIPT_RE.sub("", html)
        html = html.replace("</head>", PWA_HEAD_SNIPPET + "</head>", 1)
        # The tab shell is chrome, not a content page — it has no Export/Add
        # forms of its own, and the overlay toolbar is fixed-position, so
        # injecting it here would float a second copy on top of whichever
        # iframe's own (correct) copy is already showing.
        if filename != "shell.html":
            html = html.replace("</body>", OVERLAY_SNIPPET + "</body>")
        # no-store so the installed PWA always re-fetches the page rather than
        # reusing a stale copy — generated pages carry inline scripts that change
        # on regenerate, and a PWA window won't hard-reload on its own.
        resp = Response(html, mimetype="text/html")
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp
```

Change `serve_index` (around line 193-195):

```python
    @app.route("/")
    def serve_index():
        return serve_html_with_overlay("shell.html")
```

Add a new route next to `serve_forms_js` (around line 209-211):

```python
    @app.route("/forms.js")
    def serve_forms_js():
        return send_from_directory(str(assets), "forms.js")

    @app.route("/tabnav.js")
    def serve_tabnav_js():
        return send_from_directory(str(assets), "tabnav.js")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/server/test_app.py -v
```

Expected: PASS, full file.

- [ ] **Step 5: Commit**

```bash
git add eln/server/app.py tests/server/test_app.py
git commit -m "feat(pwa): serve the tab shell at / instead of sdgl.html"
```

---

## Task 4: Fix the Data Explorer nav link so it doesn't point at the shell

**Files:**
- Modify: `eln/generators/nav.py:12-17` (`CORE_NAV`)
- Modify: `catalog/sdgl.html:129-138` (hand-coded nav block, must stay in sync — enforced by `test_sdgl_static_nav_matches_render_nav`)
- Test: `tests/generators/test_nav.py`

Every generated page's nav bar (and `sdgl.html`'s own hand-coded copy of it) links "Data Explorer" to `"/"`. That used to mean "load `sdgl.html`"; now `/` is the shell. If an iframe's `tabnav.js` ever called `navigate("/")`, the shell would load itself recursively inside one of its own tabs. The fix is to point that link at `/sdgl.html` directly — already a valid route via the generic `/<page>.html` handler, and already what `sdgl.html` resolves to today, so this is a relabeling with no behavior change outside the shell.

- [ ] **Step 1: Write the failing tests**

In `tests/generators/test_nav.py`, update `EXPECTED` (line 6-17) and the assertion in `test_render_nav_appends_plugin_links` (line 29):

```python
EXPECTED = (
    '<div class="nav">\n'
    '        <a href="sdgl.html">Data Explorer</a>\n'
    '        <a href="experiments.html">Experiment Catalog</a>\n'
    '        <a href="reports.html">Reports</a>\n'
    '        <a href="protocols.html">Protocols</a>\n'
    '        <a href="code.html">Code</a>\n'
    '        <a href="documents.html">Documents</a>\n'
    '        <a href="presentations.html">Presentations</a>\n'
    '        <a href="posters.html">Posters</a>\n'
    '    </div>'
)


def test_render_nav_matches_expected_block():
    # Core + plugin links reordered by NAV_ORDER (Posters last). Byte-exact so
    # regeneration stays stable.
    assert render_nav() == EXPECTED


def test_render_nav_appends_plugin_links():
    extra = Plugin(name="widgets", nav=NavLink("Widgets", "widgets.html"))
    out = render_nav([extra])
    assert '<a href="sdgl.html">Data Explorer</a>' in out  # core preserved
    assert '<a href="widgets.html">Widgets</a>' in out     # plugin appended
```

Leave `test_sdgl_static_nav_matches_render_nav` (line 33-45) as-is — it will start failing once `render_nav()`'s href changes, until `sdgl.html`'s own nav block is updated to match in Step 3.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/generators/test_nav.py -v
```

Expected: `test_render_nav_matches_expected_block` and `test_render_nav_appends_plugin_links` FAIL (source still emits `href="/"`); `test_sdgl_static_nav_matches_render_nav` still passes at this point (both sides still say `/`).

- [ ] **Step 3: Implement the href fix**

In `eln/generators/nav.py`, change `CORE_NAV` (line 12-17):

```python
CORE_NAV = [
    NavLink("Data Explorer", "sdgl.html"),
    NavLink("Experiment Catalog", "experiments.html"),
    NavLink("Reports", "reports.html"),
    NavLink("Protocols", "protocols.html"),
]
```

In `catalog/sdgl.html`, update the hand-coded nav block (line 129-138) to match:

```html
    <nav class="nav">
        <a href="sdgl.html">Data Explorer</a>
        <a href="experiments.html">Experiment Catalog</a>
        <a href="reports.html">Reports</a>
        <a href="protocols.html">Protocols</a>
        <a href="code.html">Code</a>
        <a href="documents.html">Documents</a>
        <a href="presentations.html">Presentations</a>
        <a href="posters.html">Posters</a>
    </nav>
```

(Only line 130's `href="/"` → `href="sdgl.html"` actually changes; the rest is unchanged context.)

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/generators/test_nav.py -v
```

Expected: PASS, full file (all three tests).

- [ ] **Step 5: Run the full Python suite to confirm nothing else depended on the old href**

```bash
pytest -v
```

Expected: PASS. (`tests/test_share.py`'s `_staticize`/`_staticize_sdgl` rewrite tests construct their own synthetic `href="/"` fixtures and don't read the real files, so they're unaffected by this change — confirmed by inspection, no edits needed there.)

- [ ] **Step 6: Commit**

```bash
git add eln/generators/nav.py catalog/sdgl.html tests/generators/test_nav.py
git commit -m "fix(nav): point the Data Explorer link at sdgl.html, not /

/ now serves the tab shell, not sdgl.html directly. Leaving the nav link
at \"/\" would make an in-shell click load the shell recursively inside
one of its own tabs."
```

---

## Task 5: Wire `sdgl.html` up to `tabnav.js`

**Files:**
- Modify: `catalog/sdgl.html:121` (script include)
- Modify: `catalog/sdgl.html:402-422` (`linkRow`, report branch)

`sdgl.html` is hand-authored, not generated by `render_nav()`-based templates, so it isn't covered by Task 7's generator edits — it needs its own `<script src="tabnav.js">` include. Without it, `sdgl.html`'s nav-bar links and its `xlink` anchors would never get middle-click/Ctrl-Cmd-click interception, and — since `sdgl.html` is the default first tab the shell opens — no tab-title sync would ever happen for fresh Data Explorer tabs (they'd stay labeled with the raw URL).

The report row itself is the original motivating bug: it's a `<div>` (not a real anchor), so its click handler does `window.location.href = ...` directly — which, inside the shell, would navigate the whole shell window away instead of just that tab. Since the row has no native href to begin with, the fix is to expose its target via `data-nav-href` and let `tabnav.js`'s delegated click/middle-click handling (Task 1) manage it like everything else — this also gets middle-click/Ctrl-Cmd-click "open in new tab" for free, which a bespoke per-row listener would have to reimplement.

- [ ] **Step 1: Add the script include**

In `catalog/sdgl.html`, add `tabnav.js` right after the existing `auth.js` include (line 121):

```html
    <script src="auth.js"></script>
    <script src="tabnav.js"></script>
```

- [ ] **Step 2: Wire the report-row click target**

In `catalog/sdgl.html`, replace the report branch of `linkRow` (line 402-422):

```javascript
        function linkRow(link, key) {
            // Reports get special treatment - show with document icon and direct link
            if (link.type === 'report') {
                // The report hangs directly under its series, whose title it would
                // just repeat — label it generically ("Report") instead.
                const row = makeRow({
                    twisty: false, color: '#2b7a5f', icon: '📄',
                    label: 'Report'
                });
                // The fragment must be the filename slug (reports.html anchors are
                // `report-<slug>`), not the numeric DB id embedded in node_id.
                const frag = link.slug || (link.node_id || '').split(':', 2)[1];
                // data-nav-href (not a click listener): this row is a <div>, not
                // a real <a>, so tabnav.js's delegated click/middle-click handler
                // needs an explicit target to navigate it the same way as every
                // other in-app link, including inside the tab shell.
                row.dataset.navHref = `reports.html#${frag}`;
                return wrapLeaf(row);
            }
```

(Everything after the `if (link.type === 'report')` block — the default link-handling branch starting at the original line 424 — is unchanged.)

- [ ] **Step 3: Commit**

```bash
git add catalog/sdgl.html
git commit -m "fix(viewer): wire sdgl.html to tabnav.js and navigate report rows via it, not window.location

Report rows are <div>s, not real anchors, so they need an explicit
data-nav-href for tabnav.js's delegated click handling — fixes the
report-tree's only window.location.href navigation, which was the
original motivating bug for the tab shell (breaks out of the installed
PWA when there's no browser tab strip to escape into)."
```

---

## Task 6: Manual verification checkpoint — shell + Data Explorer only

No other page includes `tabnav.js` yet, so this checkpoint validates the shell mechanism itself in isolation before rolling it out everywhere in Task 7. This step has no automated test — there is no JS test framework in this repo.

- [ ] **Step 1: Start the server against a real (or scratch) data root**

```bash
labbook admin --root /path/to/a/data-repo
```

- [ ] **Step 2: Open `http://127.0.0.1:5000/` in Chromium and verify, checking off each:**
  - [ ] The shell loads with one tab open, showing the Data Explorer (`sdgl.html` content) inside the iframe.
  - [ ] Clicking `+` opens a new tab, also showing the Data Explorer, and switches to it.
  - [ ] Clicking a report row in the explorer tree (if any test data has reports) replaces the *active tab's* content with `reports.html` — the tab strip itself doesn't change, no new tab appears.
  - [ ] Middle-clicking the same report row opens a *new* tab pointed at `reports.html` and switches to it, leaving the original tab's Data Explorer content intact when you switch back.
  - [ ] Ctrl-click (or Cmd-click on macOS) on a nav-bar link (e.g. "Protocols") also opens a new tab, same as middle-click.
  - [ ] Plain-clicking a nav-bar link replaces the active tab's content (stays same tab count).
  - [ ] Closing a tab with `×` removes it and switches to a sibling tab; closing the last remaining tab opens a fresh Data Explorer tab instead of leaving the shell empty.
  - [ ] Reloading the shell page (browser refresh) restores the same set of open tabs (URLs/titles) from `sessionStorage`.
  - [ ] Opening `http://127.0.0.1:5000/sdgl.html` directly (not via `/`) still works exactly as before — full page, own nav bar, no shell chrome.

- [ ] **Step 2a: If any check fails**, fix the relevant file from Tasks 1-5 before proceeding — don't roll the include out to more pages on top of a broken shell.

---

## Task 7: Roll the `tabnav.js` include out to the remaining generators

**Files:**
- Modify: `eln/generators/catalog.py:313` (generates `experiments.html`)
- Modify: `eln/generators/reports.py:533` (`REPORTS_HTML_TEMPLATE`, shared by `reports.html`, and via `eln/generators/code.py`/`documents.py` by `code.html`/`documents.html`)
- Modify: `eln/generators/protocols.py:278` (generates `protocols.html`)
- Modify: `eln/generators/presentations.py:123` (generates `presentations.html`)
- Modify: `eln/generators/posters.py:320` (generates `posters.html`)

All five templates have the identical line `<script src="auth.js"></script>` immediately after `<body>`. Add `<script src="tabnav.js"></script>` right after it, in each file. (`code.py` and `documents.py` import and reuse `reports.py`'s `REPORTS_HTML_TEMPLATE`, so editing `reports.py` alone covers `code.html` and `documents.html` too — no separate edit needed in those two files.)

- [ ] **Step 1: Edit `eln/generators/catalog.py`**

```python
    <script src="auth.js"></script>
    <script src="tabnav.js"></script>
```

(Replaces just the `<script src="auth.js"></script>` line at 313 with both lines.)

- [ ] **Step 2: Edit `eln/generators/reports.py`** (line 533), same replacement

```python
    <script src="auth.js"></script>
    <script src="tabnav.js"></script>
```

- [ ] **Step 3: Edit `eln/generators/protocols.py`** (line 278), same replacement

```python
    <script src="auth.js"></script>
    <script src="tabnav.js"></script>
```

- [ ] **Step 4: Edit `eln/generators/presentations.py`** (line 123), same replacement

```python
    <script src="auth.js"></script>
    <script src="tabnav.js"></script>
```

- [ ] **Step 5: Edit `eln/generators/posters.py`** (line 320), same replacement

```python
    <script src="auth.js"></script>
    <script src="tabnav.js"></script>
```

- [ ] **Step 6: Run the full Python suite**

```bash
pytest -v
```

Expected: PASS, full file. (No existing test asserts an exact full-document match for any of these five generators or their downstream pages — confirmed by inspection — so this is a purely additive change from the test suite's point of view.)

- [ ] **Step 7: Commit**

```bash
git add eln/generators/catalog.py eln/generators/reports.py eln/generators/protocols.py eln/generators/presentations.py eln/generators/posters.py
git commit -m "feat(pwa): include tabnav.js on every generated catalog page"
```

---

## Task 8: Final regression pass + manual verification checkpoint — every page

**Files:** none (verification only)

- [ ] **Step 1: Run the full Python suite one more time**

```bash
pytest -v
```

Expected: PASS, full file, zero failures.

- [ ] **Step 2: Regenerate catalogs against a real/scratch data root and start the server**

```bash
labbook regenerate --root /path/to/a/data-repo
labbook admin --root /path/to/a/data-repo
```

- [ ] **Step 3: In the shell at `http://127.0.0.1:5000/`, open one tab per nav-bar entry** (Data Explorer, Experiment Catalog, Reports, Protocols, Code, Documents, Presentations, Posters) **and verify, checking off each:**
  - [ ] Every page renders correctly inside its tab (no missing styles, no broken layout from being in an iframe).
  - [ ] Plain-clicking any nav-bar link from inside any tab replaces that tab's content; the tab count never grows from a plain click.
  - [ ] Middle-click / Ctrl-Cmd-click from inside any of these pages opens a new tab, same as Task 6 verified for the Data Explorer.
  - [ ] The Export/Publish toolbar and any page-specific "+ Add" buttons (from `edit-overlay.js`) still work normally *inside* each tab's content (only the shell's own chrome was exempted from the overlay in Task 3 — individual pages still get it).
  - [ ] Opening a presentation deck still pops a separate browser *window* (not a new shell tab) — unchanged, out of scope per the design's non-goals.
  - [ ] A poster thumbnail's `target="_blank"` link still opens in a real new browser tab outside the shell — unchanged, out of scope per the design's non-goals.

- [ ] **Step 4: Verify standalone access still works for every page**, opening each directly (not via `/`): `http://127.0.0.1:5000/sdgl.html`, `/experiments.html`, `/reports.html`, `/protocols.html`, `/code.html`, `/documents.html`, `/presentations.html`, `/posters.html`. Each should render full-page with its own nav bar, no shell chrome, exactly as before this feature existed.

- [ ] **Step 5: If everything checks out, the feature is done.** If any check fails, return to the relevant task above, fix it, and re-run this checkpoint — don't consider the feature complete with a known-failing manual check.
