// Service worker for the Mnemosyne PWA: installability plus a read-only
// offline cache.
//
// Every successful same-origin GET that browsing causes (pages, report figures,
// explorer bundles, thumbnails, slides) is copied into Cache Storage as it
// passes through. The server always answers first: a request waits up to
// NETWORK_TIMEOUT_MS for response headers, and the cached copy is served only
// when the server fails, the HTTPS proxy reports it unreachable (502-504), or it
// is slower than that AND a cached copy exists. Online browsing therefore stays
// live; the cache is a fallback, never a source of truth. Nothing is cache-first:
// no URL this server hands out is content-hashed, so every one of them can change.
//
// Cached HTML served in place of the server's answer gets a
// <meta name="mnemosyne-offline"> marker, which the snippet the server injects
// into every page turns into an "offline · cached copy from <time>" badge.
//
// The /api/ surface is network-only (editor reads must never be stale, status and
// verification answers would mislead), with one exception: the data-explorer
// tree, which the sdgl page renders as content. Editing and scanning stay online.

const CACHE_NAME = 'mnemosyne-offline-v1';
const DB_NAME = 'mnemosyne-offline';
const NETWORK_TIMEOUT_MS = 4000;
// After a timeout, the server is presumed hung for SLOW_SERVER_WINDOW_MS: the
// requests that follow (a page's own scripts and figures) wait only this long
// before a cached copy stands in, instead of NETWORK_TIMEOUT_MS each in turn.
const SLOW_SERVER_TIMEOUT_MS = 500;
const SLOW_SERVER_WINDOW_MS = 30000;
// Total budget for cached bodies; least recently used entries go first.
const MAX_CACHE_BYTES = 20 * 1024 ** 3;
// Eviction trims down to this fraction of the budget so it does not run per put.
const EVICT_TO_FRACTION = 0.9;
// No single response larger than this is stored.
const MAX_ENTRY_BYTES = 256 * 1024 ** 2;
// A ranged request (video, large media) for a file up to this size triggers one
// background download of the whole file, from which ranges are served offline.
// Larger media streams live and is not available offline.
const MAX_RANGED_FILE_BYTES = 128 * 1024 ** 2;
const CACHED_AT_HEADER = 'x-mnemosyne-cached-at';

// Same-origin GET paths that are never cached or answered from the cache.
const NETWORK_ONLY = [
  /^\/sw\.js$/,
  /^\/auth\.js$/,
  /^\/api\//,
];
// ...except these read-only views, which pages render as content.
const CACHEABLE_API = [
  /^\/api\/sdgl\/tree$/,
];

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => event.waitUntil((async () => {
  // A future cache layout bumps CACHE_NAME; drop the old one rather than strand it.
  for (const name of await caches.keys()) {
    if (name.startsWith('mnemosyne-') && name !== CACHE_NAME) await caches.delete(name);
  }
  await self.clients.claim();
})()));

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (!isCacheable(url.pathname)) return;
  if (request.cache === 'no-store' || request.headers.has('authorization')) return;
  event.respondWith(request.headers.has('range')
    ? handleRanged(event, request)
    : handleGet(event, request));
});

function isCacheable(path) {
  if (CACHEABLE_API.some((re) => re.test(path))) return true;
  return !NETWORK_ONLY.some((re) => re.test(path));
}

// ---- server first, cached fallback -----------------------------------------

// `first` resolves to {timeout: true} once NETWORK_TIMEOUT_MS passes without
// response headers, else to the network result: {response} on success,
// {error[, response]} when the server is unreachable. `network` keeps running
// after a timeout, and the event is kept alive until its copy is stored, so a
// late answer still refreshes the cache. The copy is cloned here, before the
// page can start reading the body.
let serverSlowUntil = 0;

function raceNetwork(event, request, onResponse) {
  let timer;
  const network = fetch(request).then(
    (response) => {
      clearTimeout(timer);
      if (response.status >= 502 && response.status <= 504) {
        return { error: new Error('upstream ' + response.status), response };
      }
      serverSlowUntil = 0;
      return { response, stored: onResponse(response) };
    },
    (error) => {
      clearTimeout(timer);
      return { error };
    },
  );
  event.waitUntil(network.then((result) => result.stored).catch(() => {}));
  const wait = Date.now() < serverSlowUntil ? SLOW_SERVER_TIMEOUT_MS : NETWORK_TIMEOUT_MS;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => {
      serverSlowUntil = Date.now() + SLOW_SERVER_WINDOW_MS;
      resolve({ timeout: true });
    }, wait);
  });
  return { network, first: Promise.race([network, timeout]) };
}

async function handleGet(event, request) {
  const { network, first } = raceNetwork(event, request,
    (response) => (response.status === 200 ? remember(request.url, response.clone())
      : (response.status === 404 || response.status === 410) ? forget(request.url) : undefined));
  let result = await first;
  if (result.timeout) {
    const cached = await lookup(request.url);
    if (cached) return fromCache(event, request, cached);
    result = await network;
  }
  if (!result.error) return result.response;

  const cached = await lookup(request.url);
  if (cached) return fromCache(event, request, cached);
  if (request.mode === 'navigate') return notCachedPage(request.url);
  return result.response || Response.error();
}

// Cached copy standing in for the server: mark HTML for the badge, tell the page.
async function fromCache(event, request, cached) {
  const cachedAt = Number(cached.headers.get(CACHED_AT_HEADER)) || 0;
  event.waitUntil(touch(request.url));
  if (request.mode !== 'navigate' && event.clientId) {
    event.waitUntil(self.clients.get(event.clientId).then((client) => {
      if (client) client.postMessage({ type: 'mnemosyne-offline', cachedAt });
    }));
  }
  if (!(cached.headers.get('content-type') || '').includes('text/html')) return cached;
  const html = await cached.text();
  const marker = '<meta name="mnemosyne-offline" content="' + cachedAt + '">';
  const head = /<head[^>]*>/i.exec(html);
  const at = head ? head.index + head[0].length : 0;
  const headers = new Headers(cached.headers);
  headers.delete('content-length');
  return new Response(html.slice(0, at) + marker + html.slice(at), { status: 200, headers });
}

function notCachedPage(href) {
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const body = '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    + '<meta name="viewport" content="width=device-width, initial-scale=1">'
    + '<title>Not in the offline cache</title><style>'
    + 'body{font-family:system-ui,sans-serif;max-width:34rem;margin:15vh auto;padding:0 1.2rem;'
    + 'color:#1d1d1f;background:#f3f3f4;line-height:1.5}a{color:#0e7c7b}'
    + '@media (prefers-color-scheme:dark){body{color:#e8e8ea;background:#18181a}a{color:#3fb3b1}}'
    + 'code{word-break:break-all;font-size:.9em}</style></head><body>'
    + '<h1>Not in the offline cache</h1>'
    + '<p>The lab notebook server is not answering, and this page was never opened '
    + 'while it was, so there is no copy of it on this device.</p>'
    + '<p><code>' + esc(href) + '</code></p>'
    + '<p><a href="/">Back to the start page</a> &middot; '
    + '<a href="" onclick="location.reload();return false">Try again</a></p>'
    + '</body></html>';
  return new Response(body, {
    status: 503,
    headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
  });
}

// ---- ranged requests (video, large media) -----------------------------------

// A 206 cannot be stored, so ranges pass through live and the whole file is
// fetched once in the background; offline, ranges are cut from that copy.
async function handleRanged(event, request) {
  const { network, first } = raceNetwork(event, request,
    (response) => cacheWholeFile(request.url, response));
  let result = await first;
  if (result.timeout) {
    const cached = await lookup(request.url);
    if (cached) return rangeFromCache(event, request, cached);
    result = await network;
  }
  if (!result.error) return result.response;
  const cached = await lookup(request.url);
  if (cached) return rangeFromCache(event, request, cached);
  return result.response || Response.error();
}

const wholeFileFetches = new Map();

async function cacheWholeFile(key, response) {
  // The server ignored the Range header and sent everything: store that.
  if (response.status === 200) return remember(key, response.clone());
  if (response.status !== 206) return;
  const total = Number((response.headers.get('content-range') || '').split('/')[1]);
  if (!total || total > MAX_RANGED_FILE_BYTES) return;
  const etag = response.headers.get('etag');
  const entry = await getMeta(key);
  if (entry && etag && entry.etag === etag && await lookup(key)) return touch(key);
  if (!wholeFileFetches.has(key)) {
    const job = fetch(key, { credentials: 'same-origin' })
      .then((full) => (full.status === 200 ? remember(key, full) : undefined))
      .catch(() => { /* server went away mid-download: try again next time */ })
      .finally(() => wholeFileFetches.delete(key));
    wholeFileFetches.set(key, job);
  }
  return wholeFileFetches.get(key);
}

async function rangeFromCache(event, request, cached) {
  const blob = await cached.blob();
  const size = blob.size;
  const headers = new Headers(cached.headers);
  headers.set('Accept-Ranges', 'bytes');
  event.waitUntil(touch(request.url));
  if (event.clientId) {
    const cachedAt = Number(cached.headers.get(CACHED_AT_HEADER)) || 0;
    event.waitUntil(self.clients.get(event.clientId).then((client) => {
      if (client) client.postMessage({ type: 'mnemosyne-offline', cachedAt });
    }));
  }
  const range = parseRange(request.headers.get('range'), size);
  if (range === null) {
    headers.set('Content-Length', String(size));
    return new Response(blob, { status: 200, headers });
  }
  if (range === 'unsatisfiable') {
    headers.set('Content-Range', 'bytes */' + size);
    headers.set('Content-Length', '0');
    return new Response(null, { status: 416, headers });
  }
  const [start, end] = range;
  headers.set('Content-Range', 'bytes ' + start + '-' + end + '/' + size);
  headers.set('Content-Length', String(end - start + 1));
  return new Response(blob.slice(start, end + 1), { status: 206, headers });
}

// "bytes=a-b" | "bytes=a-" | "bytes=-n" → [start, end]; null for a header
// answered with the whole body (multi-range, other units); 'unsatisfiable' → 416.
function parseRange(header, size) {
  const m = /^bytes=(\d*)-(\d*)$/.exec((header || '').trim());
  if (!m || (m[1] === '' && m[2] === '')) return null;
  let start;
  let end;
  if (m[1] === '') {
    const suffix = Number(m[2]);
    if (suffix === 0) return 'unsatisfiable';
    start = Math.max(0, size - suffix);
    end = size - 1;
  } else {
    start = Number(m[1]);
    end = m[2] === '' ? size - 1 : Math.min(Number(m[2]), size - 1);
  }
  if (start >= size || start > end) return 'unsatisfiable';
  return [start, end];
}

// ---- storing ----------------------------------------------------------------

// Writes are serialised so the running total and eviction never race.
let writeChain = Promise.resolve();
function serialised(task) {
  const run = writeChain.then(task, task);
  writeChain = run.catch(() => {});
  return run;
}

function remember(key, response) {
  if (response.status !== 200 || response.type !== 'basic' || response.redirected
      || /no-store/i.test(response.headers.get('cache-control') || '')
      || Number(response.headers.get('content-length')) > MAX_ENTRY_BYTES) {
    // An unread clone would buffer the whole body: release it.
    if (response.body) response.body.cancel().catch(() => {});
    return;
  }
  const etag = response.headers.get('etag');
  return serialised(async () => {
    const cache = await caches.open(CACHE_NAME);
    const old = await getMeta(key);
    // Same validator as the stored copy: same bytes, only the last use changes.
    if (old && etag && old.etag === etag && await cache.match(key)) {
      if (response.body) response.body.cancel().catch(() => {});
      return putMeta({ ...old, used: Date.now() });
    }
    const now = Date.now();
    const headers = new Headers(response.headers);
    headers.set(CACHED_AT_HEADER, String(now));
    let size = 0;
    const counted = response.body && response.body.pipeThrough(new TransformStream({
      transform(chunk, controller) {
        size += chunk.byteLength;
        if (size > MAX_ENTRY_BYTES) controller.error(new Error('too large to cache'));
        else controller.enqueue(chunk);
      },
    }));
    try {
      await cache.put(key, new Response(counted, { status: 200, statusText: response.statusText, headers }));
    } catch (e) {
      // Too large, the server went away mid-body, or storage is full. The old
      // copy may be gone too, so drop its record; on a full disk, free space.
      await cache.delete(key);
      if (old) {
        await deleteMeta(key);
        await adjustTotal(-old.size);
      }
      if (e && e.name === 'QuotaExceededError') await evictTo((await getTotal()) - MAX_ENTRY_BYTES);
      return;
    }
    await putMeta({ url: key, size, used: now, cachedAt: now, etag });
    await adjustTotal(size - (old ? old.size : 0));
    if ((await getTotal()) > MAX_CACHE_BYTES) await evictTo(MAX_CACHE_BYTES * EVICT_TO_FRACTION);
  });
}

// The server says the file is gone: so is the cached copy.
function forget(key) {
  return serialised(async () => {
    const old = await getMeta(key);
    if (!old) return;
    await (await caches.open(CACHE_NAME)).delete(key);
    await deleteMeta(key);
    await adjustTotal(-old.size);
  });
}

async function lookup(url) {
  return (await caches.open(CACHE_NAME)).match(url);
}

function touch(key) {
  return serialised(async () => {
    const meta = await getMeta(key);
    if (meta) await putMeta({ ...meta, used: Date.now() });
  });
}

// Delete least recently used entries until the total is at most `target`.
async function evictTo(target) {
  let total = await getTotal();
  const cache = await caches.open(CACHE_NAME);
  const entries = (await allMeta()).sort((a, b) => a.used - b.used);
  for (const entry of entries) {
    if (total <= target) break;
    await cache.delete(entry.url);
    await deleteMeta(entry.url);
    total -= entry.size || 0;
  }
  totalBytes = Math.max(0, total);
}

// ---- metadata (IndexedDB): size, last use and validator per cached URL --------

let dbPromise = null;
function db() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const open = indexedDB.open(DB_NAME, 1);
      open.onupgradeneeded = () => open.result.createObjectStore('entries', { keyPath: 'url' });
      open.onsuccess = () => resolve(open.result);
      open.onerror = () => reject(open.error);
    });
    dbPromise.catch(() => { dbPromise = null; });
  }
  return dbPromise;
}

async function tx(mode, fn) {
  const conn = await db();
  return new Promise((resolve, reject) => {
    const t = conn.transaction('entries', mode);
    const req = fn(t.objectStore('entries'));
    t.oncomplete = () => resolve(req.result);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error);
  });
}

const getMeta = (url) => tx('readonly', (s) => s.get(url)).catch(() => undefined);
const putMeta = (entry) => tx('readwrite', (s) => s.put(entry)).catch(() => {});
const deleteMeta = (url) => tx('readwrite', (s) => s.delete(url)).catch(() => {});
const allMeta = () => tx('readonly', (s) => s.getAll()).catch(() => []);

// Running total of cached bytes, summed from the metadata once per worker start.
let totalBytes = null;
async function getTotal() {
  if (totalBytes === null) totalBytes = (await allMeta()).reduce((sum, e) => sum + (e.size || 0), 0);
  return totalBytes;
}
async function adjustTotal(delta) {
  totalBytes = (await getTotal()) + delta;
}
