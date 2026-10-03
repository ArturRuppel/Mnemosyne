# `catalog/` — static frontend assets

This directory holds the **hand-written** static frontend assets that ship with
the code:

- `edit-overlay.js` / `edit-overlay.css` — local edit toolbar + inline Edit/Add
  buttons injected by the server into catalog pages.
- `forms.js` — the inline create/edit form modals (experiments, protocols,
  documents, reports) opened from the viewer's Edit/Add buttons.
- `sdgl.html` — the Scientific Data Graph Layer, served at `/`; it is the
  notebook's home page.
- `manifest.webmanifest`, `sw.js`, `icon-*.png` — PWA assets so `labbook admin`
  is installable as a standalone app (own window, launcher / home-screen icon).
  The server injects the manifest link + service-worker registration into every
  served page's `<head>`, and the registration alone (plus the offline badge)
  into HTML served from the data mounts (explorer bundles, report embeds).
- `sw.js` is also a **read-only offline cache**. It needs a secure context:
  serve over HTTPS (e.g. Tailscale Serve, see the top-level README) or
  `localhost`; over plain `http://<address>` it never registers and the app
  behaves exactly as without it.
  - *Stored:* every successful same-origin GET as it passes through — pages,
    CSS/JS, report figures and media, explorer bundles and the data they load,
    thumbnails, slides, linked sources, and `/api/sdgl/tree`.
  - *Never stored or answered from cache:* non-GET requests, the rest of
    `/api/` (editor reads, tags/field values, scan/backup/verify status — the
    server marks them `no-store`), `/sw.js`, `auth.js`, anything `no-store`,
    and other origins (the MathJax CDN).
  - *Policy:* server first for everything (no URL here is content-hashed);
    the cached copy is used when the request fails, the proxy answers 502–504,
    or no response headers arrive within 4 s (0.5 s for 30 s after such a
    timeout). A 404 from the server drops the cached copy.
  - *Ranged requests (video):* passed through live; the whole file is then
    fetched once in the background if it is at most `MAX_RANGED_FILE_BYTES`
    (128 MiB), and offline ranges are cut from it (206 / 416). Larger media is
    not available offline.
  - *Bounds:* `MAX_CACHE_BYTES` (20 GiB) total with least-recently-used
    eviction (IndexedDB keeps size and last use per URL), at most
    `MAX_ENTRY_BYTES` (256 MiB) per response; `navigator.storage.persist()` is
    requested.
  - *Offline view:* cached HTML is marked with `<meta name="mnemosyne-offline">`
    and the injected snippet shows "offline · cached copy from <time>"; a page
    never cached gets a "Not in the offline cache" page linking back to `/`.
  - *Updates:* `/sw.js` is served `no-cache` and registered with
    `updateViaCache: 'none'`; the worker calls `skipWaiting` + `clients.claim`.
    Bump `CACHE_NAME` only when the stored layout changes (it drops the old cache).
- shared CSS.

The **generated** pages (`experiments.html`, `protocols.html`, `notebooks.html`,
`reports.html`) are produced by `eln.generators` at build time and are
**gitignored** (`catalog/*.html`). On deploy they are built fresh and served via
GitLab Pages from the **data** repo.

Assets are ported from the original server + overlay; the former standalone admin
panel has been absorbed into the viewer as inline `forms.js` modals.
