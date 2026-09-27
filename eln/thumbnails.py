"""Catalog thumbnails: one preview image per experiment session (CODE-NN).

``labbook thumbnails`` walks the configured scan roots for every session's
folder, ranks what it finds, renders the best candidate to
``<data_root>/thumbnails/<CODE-NN>.png`` and records the choice in
``thumbnails/sources.json``.

Ranking, highest first:

1. Rendered results under a processed tree — a ``force_cell_overlay`` movie,
   a ``cell_labels`` / ``tracked_labels`` segmentation, force or displacement
   maps, exported figure frames.
2. Other processed images and movies (crops, contact sheets, z-averages).
3. Raw acquisition data, preferring a nuclei/cell/transmitted channel over a
   bead channel and a local copy over a CIFS share.
4. QC diagnostics and binary masks, which say nothing at 400 px.

Everything is read page by page so a multi-GB stack costs one plane. The
heavy readers (numpy, Pillow, tifffile, zarr, ffmpeg) are imported lazily:
install the ``thumbnails`` extra (``pip install -e '.[thumbnails]'``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from eln.sdgl import format_experiment_id

MAXPX = 400
THUMBS_DIR = "thumbnails"
SOURCES_FILE = "sources.json"

IMAGE_EXT = (".tif", ".tiff", ".ics", ".png", ".jpg", ".jpeg")
MOVIE_EXT = (".mp4", ".gif")
WALK_EXT = IMAGE_EXT + MOVIE_EXT
WALK_CAP = 4000

LOCAL_ROOTS = {"data", "expansion", "onetouch"}
KEY_RE = re.compile(r"^[A-Z0-9]{5}-X?\d{2,}$")

# ---- candidate ranking ------------------------------------------------------

PROCESSED_DIR = re.compile(r"/(processed|curated|TFM_data|analysis|figures|figures_masked|qc)/")
SKIP_DIR = re.compile(r"/(archive|excluded[^/]*|_inputs|TFM_inputs[^/]*|\.zarr)/", re.I)

# Processed tiers. First match wins; the score has to clear the raw range
# (at most 15) to count as "processed beats raw".
PROCESSED_TIERS = (
    (re.compile(r"force_cell_overlay\.(mp4|gif)$", re.I), 40, "force overlay"),
    (re.compile(r"(^|/)(3_cell/tracked_labels|cell_labels)\.tiff?$", re.I), 36, "cell labels"),
    (re.compile(r"(^|/)(2_nucleus/tracked_labels|nucleus_labels)\.tiff?$", re.I), 32, "nucleus labels"),
    (re.compile(r"(force_map|displacement_map|normal_stress|sigma_[xy]{2})\.(mp4|gif)$", re.I), 28, "force map"),
    (re.compile(r"(corrected_)?frame_\d+.*\.(png|jpg)$", re.I), 24, "figure frame"),
    (re.compile(r"(diagnostic|regist|_qc|/qc/|overview|intensity|profile)", re.I), 4, "qc"),
    (re.compile(r"(^|/)masks?[_\d]*\.tiff?$", re.I), -10, "mask"),
    (re.compile(r"(^|/)crops?/", re.I), 22, "crop"),
    (re.compile(r"\.(mp4|gif)$", re.I), 20, "processed movie"),
    (re.compile(r"\.(png|jpg|jpeg)$", re.I), 18, "processed figure"),
)

RAW_PREFERRED = re.compile(r"nls|nuc|cell|trans|phase|bright", re.I)
RAW_DERIVED = re.compile(
    r"label|mask|_dp_|_prob_|tracked|thumb|figure|montage|overlay|_seg|display"
    r"|results|beads|_inputs|contact_sheet|overview|reference", re.I)


def classify(path):
    """Return ``(score, kind)`` for a candidate path (a str, POSIX separators)."""
    p = path.replace("\\", "/")
    if SKIP_DIR.search(p + "/") and not p.endswith(".zarr"):
        return -100, "skipped"
    name = p.rsplit("/", 1)[-1]
    if PROCESSED_DIR.search(p):
        tail = "/".join(p.split("/")[-2:])
        for rx, score, kind in PROCESSED_TIERS:
            if rx.search(p if kind == "qc" else tail):
                return score, kind
        # A plain stack under processed/ (a registered copy, a z-average): worth
        # about as much as raw, judged by the same channel-name rules.
        score = 8
        kind = "processed stack"
    else:
        score = 8 if ("/raw/" in p or "/0_input/" in p) else 0
        kind = "raw"
    if RAW_PREFERRED.search(name):
        score += 5
    if RAW_DERIVED.search(name):
        score -= 20
    return score, kind


def rank_key(cand):
    """Sort key: best first. ``cand`` is ``(root_name, path, size)``.

    Processed candidates tie-break on path (so ``pos00`` comes before
    ``pos07``); raw candidates tie-break on size (the real stack over a
    snapshot)."""
    root, path, size = cand
    score, kind = classify(path)
    if root in LOCAL_ROOTS:
        score += 2
    if kind in ("raw", "processed stack"):
        return (-score, -size, path)
    return (-score, path)


# ---- discovery --------------------------------------------------------------

def walk_dataset(key, roots, cap=WALK_CAP):
    """Yield ``(root_name, path, size)`` for image-like files under every
    ``<root>/<key>`` or ``<root>/*/<key>`` folder. A ``.zarr`` store is one
    candidate; its chunks are never walked."""
    found = []
    for root in roots:
        base = Path(root["path"])
        if not base.is_dir():
            continue
        tops = [base / key] + sorted(p for p in base.glob(f"*/{key}") if p.is_dir())
        for top in tops:
            if not top.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(top):
                if dirpath.endswith(".zarr"):
                    found.append((root["name"], dirpath, 1 << 40))
                    dirnames[:] = []
                    continue
                dirnames.sort()
                for fn in sorted(filenames):
                    if fn.lower().endswith(WALK_EXT):
                        fp = os.path.join(dirpath, fn)
                        try:
                            found.append((root["name"], fp, os.path.getsize(fp)))
                        except OSError:
                            pass
                if len(found) >= cap:
                    return found
    return found


def dataset_keys(db_path):
    """``{CODE-NN: experiment id}`` for every session in experiments.db."""
    conn = sqlite3.connect(str(db_path))
    try:
        codes = dict(conn.execute("SELECT title, code FROM experiment_codes"))
        rows = conn.execute(
            "SELECT id, experiment_type, repetition, excluded FROM experiments").fetchall()
    finally:
        conn.close()
    keys = {}
    for eid, title, rep, excluded in rows:
        code = codes.get(title)
        if code and rep is not None:
            keys[format_experiment_id(code, rep, bool(excluded))] = eid
    return keys


# ---- readers ----------------------------------------------------------------

def _np():
    import numpy as np
    return np


def focus_score(plane):
    """Gradient energy on a coarse view: an in-focus plane has more of it."""
    np = _np()
    p = plane[::4, ::4].astype(np.float32)
    if p.size == 0:
        return 0.0
    return float(np.diff(p, axis=0).var() + np.diff(p, axis=1).var())


def best_index(n, read_plane, samples=5):
    """Pick the sharpest of a few evenly spaced planes along one axis."""
    if n <= 1:
        return 0
    idxs = sorted({int(round(i * (n - 1) / (samples - 1))) for i in range(samples)})
    best, best_s = idxs[0], -1.0
    for i in idxs:
        try:
            s = focus_score(read_plane(i))
        except Exception:
            continue
        if s > best_s:
            best, best_s = i, s
    return best


def read_tiff(path):
    """Return (H,W) or (C,H,W) from the sharpest middle of the stack."""
    import tifffile
    np = _np()
    with tifffile.TiffFile(path) as tf:
        s = tf.series[0]
        axes, shape = s.axes, tuple(s.shape)
        if len(shape) == 2:
            return tf.pages[0].asarray()
        if axes.endswith("YXS") or axes.endswith("YXC"):
            return tf.pages[len(tf.pages) // 2].asarray()
        lead, lead_axes = shape[:-2], axes[:-2]
        expected = int(np.prod(lead)) if lead else 1
        if expected != len(tf.pages):
            # OME/MMStack split over files: this file holds part of the series.
            return tf.pages[len(tf.pages) // 2].asarray()
        cidx = lead_axes.find("C")
        if cidx >= 0 and not (2 <= lead[cidx] <= 4):
            cidx = -1
        mid = [d // 2 for d in lead]
        ax = next((i for i in range(len(lead) - 1, -1, -1) if i != cidx), -1)
        if ax >= 0 and lead[ax] > 1:
            def _plane(i, ax=ax, mid=mid, lead=lead, cidx=cidx):
                idx = list(mid)
                idx[ax] = i
                if cidx >= 0:
                    idx[cidx] = 0
                return tf.pages[int(np.ravel_multi_index(idx, lead))].asarray()
            mid[ax] = best_index(lead[ax], _plane)
        if cidx < 0:
            return tf.pages[int(np.ravel_multi_index(mid, lead))].asarray()
        planes = []
        for c in range(lead[cidx]):
            idx = list(mid)
            idx[cidx] = c
            planes.append(tf.pages[int(np.ravel_multi_index(idx, lead))].asarray())
        return np.stack(planes)


def read_labels(path):
    """Middle plane of a label image, kept integer for the LUT render."""
    import tifffile
    arr = tifffile.imread(path)
    while arr.ndim > 2:
        arr = arr[arr.shape[0] // 2]
    return arr


def read_ics(path):
    """Minimal ICS 1.0 reader: text header, raw uncompressed .ids beside it."""
    np = _np()
    order = sizes = None
    fmt, sign, byte_order = "integer", "unsigned", "1 2"
    with open(path, "rb") as fh:
        for raw in fh.read(8192).split(b"\n"):
            parts = raw.decode("latin-1").strip().split("\t")
            if parts[:2] == ["layout", "order"]:
                order = parts[2:]
            elif parts[:2] == ["layout", "sizes"]:
                sizes = [int(x) for x in parts[2:]]
            elif parts[:2] == ["representation", "format"]:
                fmt = parts[2]
            elif parts[:2] == ["representation", "sign"]:
                sign = parts[2]
            elif parts[:2] == ["representation", "byte_order"]:
                byte_order = " ".join(parts[2:])
    if not order or not sizes:
        raise ValueError("unreadable ICS header")
    if fmt != "integer":
        raise ValueError(f"unsupported ICS format {fmt}")
    endian = "<" if byte_order.split()[0] == "1" else ">"
    dtype = np.dtype(f"{endian}{'u' if sign == 'unsigned' else 'i'}{sizes[0] // 8}")
    dims = list(zip(order[1:], sizes[1:]))
    shape = tuple(n for _, n in reversed(dims))
    names = [a for a, _ in reversed(dims)]
    arr = np.memmap(path[:-4] + ".ids", dtype=dtype, mode="r", shape=shape)
    cidx = names.index("ch") if "ch" in names else -1
    sl = [slice(None) if (n in ("x", "y") or i == cidx) else shape[i] // 2
          for i, n in enumerate(names)]
    out = np.asarray(arr[tuple(sl)])
    if cidx >= 0 and names.index("ch") > names.index("y"):
        out = np.moveaxis(out, -1, 0)
    return out


def read_zarr(path):
    import zarr
    np = _np()
    g = zarr.open(path, mode="r")
    keys = sorted(g.array_keys()) if hasattr(g, "array_keys") else []
    if not keys:
        g = g[sorted(g.group_keys())[0]]
        keys = sorted(g.array_keys())
    a = g[keys[0]]
    if a.ndim == 2:
        return np.asarray(a)
    lead = a.shape[:-2]
    cidx = next((i for i, d in enumerate(lead) if 2 <= d <= 4), -1)
    sl = [d // 2 for d in lead]
    ax = next((i for i in range(len(lead) - 1, -1, -1) if i != cidx), -1)
    if ax >= 0 and lead[ax] > 1:
        def _plane(i, ax=ax, sl=list(sl), cidx=cidx):
            idx = list(sl)
            idx[ax] = i
            if cidx >= 0:
                idx[cidx] = 0
            return np.asarray(a[tuple(idx) + (slice(None), slice(None))])
        sl[ax] = best_index(lead[ax], _plane)
    if cidx >= 0:
        sl[cidx] = slice(None)
    return np.asarray(a[tuple(sl) + (slice(None), slice(None))])


def read_movie_frame(path):
    """The middle frame of a GIF (via Pillow) or an MP4 (via ffmpeg) as RGB."""
    from PIL import Image
    if path.lower().endswith(".gif"):
        im = Image.open(path)
        im.seek(getattr(im, "n_frames", 1) // 2)
        return im.convert("RGB")
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not on PATH; cannot read mp4 thumbnails")
    duration = 0.0
    if ffprobe:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
        try:
            duration = float(out)
        except ValueError:
            duration = 0.0
    with tempfile.TemporaryDirectory() as td:
        frame = os.path.join(td, "frame.png")
        subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-ss", f"{duration / 2:.3f}", "-i", path,
             "-frames:v", "1", frame], check=True)
        return Image.open(frame).convert("RGB")


# ---- rendering --------------------------------------------------------------

def stretch(plane):
    np = _np()
    p = plane.astype(np.float32)
    lo, hi = np.percentile(p, (1.0, 99.5))
    if hi <= lo:
        lo, hi = float(p.min()), float(p.max())
    if hi <= lo:
        return np.zeros(p.shape, np.uint8)
    return (np.clip((p - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)


def is_brightfield(plane):
    """Transmitted light fills the histogram; fluorescence sits on a dark floor."""
    np = _np()
    p = plane.astype(np.float32)
    lo, med, hi = np.percentile(p, (1.0, 50.0, 99.5))
    return hi > lo and (med - lo) / (hi - lo) > 0.35


TINTS = [(1, 0, 1), (0, 1, 0), (0, 1, 1)]          # magenta, green, cyan


def labels_to_image(lab, seed=0):
    """Colour every label with a fixed random LUT; background stays black."""
    np = _np()
    from PIL import Image
    lab = np.asarray(lab).astype(np.int64)
    lab[lab < 0] = 0
    n = int(lab.max()) + 1
    lut = np.random.default_rng(seed).integers(60, 256, size=(n, 3)).astype(np.uint8)
    lut[0] = 0
    return Image.fromarray(lut[lab], "RGB")


def to_image(arr):
    np = _np()
    from PIL import Image
    arr = np.squeeze(arr)
    if arr.ndim == 3 and arr.shape[-1] in (3, 4):
        arr = np.moveaxis(arr, -1, 0)[:3]
    while arr.ndim > 3:
        arr = arr[arr.shape[0] // 2]
    if arr.ndim == 2:
        return Image.fromarray(stretch(arr), "L").convert("RGB")
    chans = list(arr[:4])
    bf = [c for c in chans if is_brightfield(c)]
    fluo = [c for c in chans if not is_brightfield(c)]
    if bf and fluo:
        base = stretch(bf[0]).astype(np.float32) * 0.65
        rgb = np.stack([base] * 3, -1)
        for c, tint in zip(fluo[:3], TINTS):
            layer = stretch(c).astype(np.float32)
            for i, on in enumerate(tint):
                if on:
                    rgb[..., i] += layer
        return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    ch = [stretch(c) for c in (fluo or chans)[:3]]
    if len(ch) == 2:
        g, m = ch
        rgb = np.stack([m, g, m], -1)
    elif len(ch) == 1:
        rgb = np.stack([ch[0]] * 3, -1)
    else:
        rgb = np.stack(ch, -1)
    return Image.fromarray(rgb, "RGB")


def trim_border(img, tol=12):
    """Crop a uniform margin (matplotlib's white figure padding, or a black
    letterbox) so the data fills the thumbnail. Leaves the image alone when
    nothing would remain."""
    from PIL import Image, ImageChops
    bg = Image.new(img.mode, img.size, img.getpixel((0, 0)))
    diff = ImageChops.difference(img, bg).convert("L").point(lambda v: 255 if v > tol else 0)
    box = diff.getbbox()
    if box and box[2] - box[0] > 16 and box[3] - box[1] > 16:
        return img.crop(box)
    return img


def crop_figure_panel(img, min_keep=0.55, max_cut=0.4, white=235):
    """Drop the colourbar or legend strip that a plotting library laid beside
    the data panel, separated from it by a white gap. Keeps the largest
    non-white band along each axis, and only when that band holds most of the
    image (*min_keep*) and the discarded strips are thin (*max_cut*), so a
    sparse figure with white between its cells is left alone."""
    np = _np()
    a = np.asarray(img.convert("RGB"))
    is_white = (a > white).all(-1)
    h, w = is_white.shape

    def largest_band(gap):
        best, start = (0, 0), None
        for i, g in enumerate(list(gap) + [True]):
            if not g and start is None:
                start = i
            elif g and start is not None:
                if i - start > best[1] - best[0]:
                    best = (start, i)
                start = None
        return best

    r0, r1 = largest_band(is_white.mean(1) >= 0.98)
    c0, c1 = largest_band(is_white.mean(0) >= 0.98)
    box = [0, 0, w, h]
    if min_keep * h <= r1 - r0 < h and h - (r1 - r0) <= max_cut * h:
        box[1], box[3] = r0, r1
    if min_keep * w <= c1 - c0 < w and w - (c1 - c0) <= max_cut * w:
        box[0], box[2] = c0, c1
    return img.crop(box) if box != [0, 0, w, h] else img


def first_panel(img, ratio=1.9):
    """A frame at least *ratio* times wider than tall is a side-by-side
    montage; keep its leftmost square panel."""
    w, h = img.size
    return img.crop((0, 0, h, h)) if w >= ratio * h else img


def figure_image(img):
    return first_panel(crop_figure_panel(trim_border(img)))


def render(path, kind, dest):
    """Render one candidate to *dest* (PNG). Returns the thumbnail size."""
    from PIL import Image
    low = path.lower()
    if kind in ("cell labels", "nucleus labels"):
        img = labels_to_image(read_labels(path))
    elif low.endswith(MOVIE_EXT):
        img = figure_image(read_movie_frame(path))
    elif low.endswith((".png", ".jpg", ".jpeg")):
        img = figure_image(Image.open(path).convert("RGB"))
    elif low.endswith(".ics"):
        img = to_image(read_ics(path))
    elif low.endswith(".zarr") or ".zarr/" in low:
        img = to_image(read_zarr(path))
    else:
        img = to_image(read_tiff(path))
    img.thumbnail((MAXPX, MAXPX), Image.LANCZOS)
    img.save(dest, "PNG", optimize=True)
    return img.size


# ---- driver -----------------------------------------------------------------

def choose(key, roots, tries=12):
    """Ranked candidates for one session, best first (at most *tries*)."""
    cands = sorted(walk_dataset(key, roots), key=rank_key)
    out = []
    for root, path, size in cands:
        if path.lower().endswith(".ids"):
            continue
        score, kind = classify(path)
        if kind == "skipped":
            continue
        out.append({"root": root, "path": path, "score": score, "kind": kind})
        if len(out) >= tries:
            break
    return out


def generate(data_root, roots, keys=None, db_path=None, force=False,
             dry_run=False, report=print):
    """Render thumbnails for *keys* (default: every session in the DB).

    Writes ``thumbnails/<KEY>.png``, updates ``thumbnails/sources.json`` and
    fills an empty ``thumbnail_path`` in experiments.db. Returns
    ``{key: source record or None}``."""
    data_root = Path(data_root)
    out_dir = data_root / THUMBS_DIR
    db_path = Path(db_path) if db_path else data_root / "experiments.db"
    ids = dataset_keys(db_path) if db_path.exists() else {}
    if keys is None:
        keys = sorted(ids)
    unknown = [k for k in keys if not KEY_RE.match(k)]
    if unknown:
        raise ValueError(f"not a CODE-NN identifier: {', '.join(unknown)}")

    sources_path = out_dir / SOURCES_FILE
    sources = {}
    if sources_path.exists():
        try:
            sources = json.loads(sources_path.read_text())
        except ValueError:
            sources = {}

    results = {}
    for key in keys:
        dest = out_dir / f"{key}.png"
        if dest.exists() and not force and not dry_run and sources.get(key):
            report(f"keep {key:<10} {sources[key]['kind']}: {sources[key]['path']}")
            results[key] = sources[key]
            continue
        cands = choose(key, roots)
        if not cands:
            report(f"none {key:<10} no image files found under any root")
            results[key] = None
            continue
        if dry_run:
            top = cands[0]
            report(f"pick {key:<10} [{top['score']:>3} {top['kind']}] {top['path']}")
            results[key] = top
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        picked = err = None
        for cand in cands:
            try:
                size = render(cand["path"], cand["kind"], dest)
            except Exception as exc:  # noqa: BLE001 - try the next candidate
                err = f"{type(exc).__name__}: {exc}"
                continue
            picked = dict(cand, size=list(size))
            break
        if picked:
            report(f"ok   {key:<10} [{picked['score']:>3} {picked['kind']}] {picked['path']}")
            sources[key] = picked
            results[key] = picked
        else:
            report(f"fail {key:<10} {err}")
            results[key] = None

    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        sources_path.write_text(json.dumps(sources, indent=1, sort_keys=True) + "\n")
        if db_path.exists():
            _link_thumbnails(db_path, ids, [k for k in keys if results.get(k)])
    return results


def _link_thumbnails(db_path, ids, keys):
    """Point experiments with an empty thumbnail_path at their rendered file."""
    conn = sqlite3.connect(str(db_path))
    try:
        for key in keys:
            eid = ids.get(key)
            if eid is None:
                continue
            conn.execute(
                "UPDATE experiments SET thumbnail_path = ? "
                "WHERE id = ? AND (thumbnail_path IS NULL OR thumbnail_path = '')",
                (f"{THUMBS_DIR}/{key}.png", eid))
        conn.commit()
    finally:
        conn.close()
