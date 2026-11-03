"""Lab-book figures: a one-plot ``.iris`` and the SVG beside it, edited from Iris.

The data repo ignores ``*.iris``, so git holds no earlier state of these files.
``<dir>/.versions/<stem>/`` is their history instead: the first save of an editing
session copies the previous pair there, and every save appends a line to
``log.jsonl`` that carries the hash of the line before it.
"""

import hashlib
import io
import json
import os
import shutil
import threading
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

VERSIONS_DIR = ".versions"
FIGURE_ROOTS = ("documents", "reports")

_save_lock = threading.Lock()


class FigureError(Exception):
    """A refused figure operation; ``status`` is the HTTP status to answer with."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def resolve_figure(root, rel):
    """The ``.iris`` at ``rel``, or ``None`` if it is outside the figure roots."""
    parts = Path(rel).parts
    if len(parts) < 2 or parts[0] not in FIGURE_ROOTS or not rel.endswith(".iris"):
        return None
    base = (Path(root) / parts[0]).resolve()
    path = (Path(root) / rel).resolve()
    if base not in path.parents or VERSIONS_DIR in path.parts:
        return None
    return path


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def plot_count(data):
    """How many plots a ``.iris`` holds. Raises ``FigureError`` if it is not one."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
    except zipfile.BadZipFile as e:
        raise FigureError(422, "not a .iris file") from e
    if "manifest.json" not in names:
        raise FigureError(422, "not a .iris file")
    return sum(n.startswith("analyses/") and n.endswith(".json") for n in names)


def _check_svg(svg):
    if "<!ENTITY" in svg:
        raise FigureError(422, "the SVG declares XML entities")
    try:
        tree = ET.fromstring(svg)
    except ET.ParseError as e:
        raise FigureError(422, f"not an SVG: {e}") from e
    tags = [el.tag.rsplit("}", 1)[-1] for el in tree.iter()]
    if tags[0] != "svg":
        raise FigureError(422, "not an SVG")
    if "script" in tags:
        raise FigureError(422, "the SVG contains a script")


def _write_atomic(path, data):
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _versions_dir(path):
    return path.parent / VERSIONS_DIR / path.stem


def read_history(path):
    log = _versions_dir(path) / "log.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def describe_figure(path):
    """What a client needs before opening the figure."""
    if not path.is_file():
        raise FigureError(404, "figure not found")
    data = path.read_bytes()
    return {"plots": plot_count(data), "sha256": _sha256(data), "history": read_history(path)}


def save_figure(path, iris, svg, base_sha256, session):
    """Replace the pair at ``path``, keeping what it replaces. Returns the new hash."""
    if not session:
        raise FigureError(422, "a save needs a session")
    plots = plot_count(iris)
    if plots != 1:
        raise FigureError(422, f"a lab-book figure holds exactly one plot, not {plots}")
    _check_svg(svg)
    with _save_lock:
        if not path.is_file():
            raise FigureError(404, "figure not found")
        before = _sha256(path.read_bytes())
        if before != base_sha256:
            raise FigureError(409, "the file changed since it was opened; reload to continue")

        svg_path = path.with_suffix(".svg")
        versions = _versions_dir(path)
        versions.mkdir(parents=True, exist_ok=True)
        log = versions / "log.jsonl"
        lines = log.read_bytes().splitlines() if log.exists() else []
        history = [json.loads(line) for line in lines]
        now = datetime.now(timezone.utc)
        snapshot = None
        if not any(entry["session"] == session for entry in history):
            snapshot = now.strftime("%Y%m%dT%H%M%S%fZ")
            shutil.copy2(path, versions / f"{snapshot}.iris")
            if svg_path.exists():
                shutil.copy2(svg_path, versions / f"{snapshot}.svg")

        after = _sha256(iris)
        entry = {
            "time": now.isoformat(),
            "session": session,
            "before": before,
            "after": after,
            "snapshot": snapshot,
            "previous_line": _sha256(lines[-1]) if lines else None,
        }
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        _write_atomic(path, iris)
        _write_atomic(svg_path, svg.encode("utf-8"))
    return after
