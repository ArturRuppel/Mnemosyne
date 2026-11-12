"""Unified configuration for the labbook CLI.

One ``labbook.toml`` (gitignored, in the code repo) replaces the old in-repo
``sdgl.toml`` and additionally records ``data_root`` — the data-repo location.
The file is discovered from the installed package's code-repo checkout (the
directory containing ``pyproject.toml``), overridable by ``--config`` /
``LABBOOK_CONFIG``. The data root is overridable by ``--root`` / ``ELN_ROOT``.
"""

from __future__ import annotations

import os
import threading
import warnings
from dataclasses import dataclass, field
from pathlib import Path

# Resolving a scan root that points at a dead network mount (e.g. an unreachable
# CIFS share) blocks indefinitely in realpath. Cap each resolve at this many
# seconds, then fall back to a non-blocking normalization (see _resolve_path).
_RESOLVE_TIMEOUT = 3.0

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # 3.9 / 3.10
    import tomli as tomllib

CONFIG_FILENAME = "labbook.toml"
ENV_CONFIG = "LABBOOK_CONFIG"
ENV_ROOT = "ELN_ROOT"
ENV_ALLOWED_HOSTS = "LABBOOK_ALLOWED_HOSTS"


@dataclass
class Config:
    """Resolved configuration. ``scan_roots`` paths are absolute."""

    data_root: Path
    scanner: dict = field(default_factory=dict)
    scan_roots: list = field(default_factory=list)  # [{"name": str, "path": Path}]
    channel_aliases: list = field(default_factory=list)  # [[canonical, variant, ...]]
    timestamp: dict = field(default_factory=dict)  # [timestamp] table (RFC 3161)
    iris_web: Path | None = None  # a built Iris web site for `labbook export --all`
    iris_url: str | None = None  # a served Iris that opens and saves lab-book figures
    # Host names (besides loopback) the server answers to, e.g. the name a reverse
    # proxy publishes it under. Anything else gets 400 (DNS-rebinding guard).
    allowed_hosts: list = field(default_factory=list)


def find_config_path() -> Path:
    """Locate ``labbook.toml``.

    ``LABBOOK_CONFIG`` wins; otherwise derive the code-repo checkout from this
    package's location (the nearest parent holding ``pyproject.toml``).
    """
    env = os.environ.get(ENV_CONFIG)
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent / CONFIG_FILENAME
    raise FileNotFoundError(
        "Could not locate the code-repo root (no pyproject.toml above "
        f"{here}). Set {ENV_CONFIG} to the labbook.toml path."
    )


def _resolve_path(p, timeout=_RESOLVE_TIMEOUT):
    """Resolve *p* (symlinks + absolute) without ever hanging on a dead mount.

    ``Path.resolve()`` calls ``realpath``, which blocks indefinitely when a path
    sits on an unreachable network mount — wedging *every* CLI command at config
    load, even ones (like ``regenerate``) that never touch the scan roots. Run the
    resolve in a daemon thread and give it *timeout* seconds; if it doesn't return,
    fall back to a non-blocking ``os.path.abspath`` normalization and warn, so a
    flaky scan root degrades to 'unresolved' instead of freezing the process. The
    abandoned thread is a daemon, so it never blocks interpreter exit.
    """
    result = {}

    def _work():
        try:
            result["path"] = p.resolve()
        except OSError as exc:  # resolve can raise on permission/loop errors
            result["error"] = exc

    worker = threading.Thread(target=_work, daemon=True)
    worker.start()
    worker.join(timeout)
    if "path" in result:
        return result["path"]

    fallback = Path(os.path.abspath(p))
    if worker.is_alive():
        warnings.warn(
            f"scan root {p} is unreachable (resolve exceeded {timeout}s, likely a "
            f"dead network mount); using the unresolved path {fallback}")
    else:
        warnings.warn(f"could not resolve scan root {p}: {result.get('error')}; "
                      f"using {fallback}")
    return fallback


def load_config(config_path=None, *, root_override=None) -> Config:
    """Parse the unified config into a :class:`Config`.

    Root precedence: ``root_override`` (``--root``) > ``ELN_ROOT`` > the file's
    ``data_root``. Relative ``scan_roots`` paths resolve against ``data_root``.
    """
    path = Path(config_path) if config_path else find_config_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found: {path}. Copy labbook.toml.example to {path}."
        )
    data = tomllib.loads(path.read_text(encoding="utf-8"))

    root = root_override or os.environ.get(ENV_ROOT) or data.get("data_root")
    if not root:
        raise ValueError(
            "No data_root: set --root, ELN_ROOT, or data_root in the config."
        )
    data_root = Path(root).expanduser().resolve()

    scan_roots = []
    for entry in data.get("scan_roots", []):
        p = Path(entry["path"]).expanduser()
        if not p.is_absolute():
            p = data_root / p
        scan_roots.append({"name": entry.get("name"), "path": _resolve_path(p)})

    # Channel fungibility: equivalence groups of interchangeable markers
    # (e.g. ["GFP", "488", "FITC"]); the first member is canonical.
    channel_aliases = [
        list(group) for group in data.get("channels", {}).get("aliases", [])
    ]

    # allowed_hosts from the file, plus any in LABBOOK_ALLOWED_HOSTS (comma-separated).
    allowed_hosts = [str(h).strip() for h in data.get("allowed_hosts", []) if str(h).strip()]
    allowed_hosts += [h.strip() for h in os.environ.get(ENV_ALLOWED_HOSTS, "").split(",")
                      if h.strip()]

    return Config(
        data_root=data_root,
        scanner=data.get("scanner", {}),
        scan_roots=scan_roots,
        channel_aliases=channel_aliases,
        timestamp=data.get("timestamp", {}),
        iris_web=Path(data["iris_web"]).expanduser() if data.get("iris_web") else None,
        iris_url=data.get("iris_url"),
        allowed_hosts=allowed_hosts,
    )
