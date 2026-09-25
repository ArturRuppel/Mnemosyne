#!/usr/bin/env python3
"""Interactive data explorers: discovery, catalog links, and export copying.

Each explorer is a directory below ``ROOT/explorers`` with an ``explorer.json``
manifest (naming its experiment, ``CODE-NN``) and an ``index.html`` entry point;
explorers may share code from ``ROOT/explorers/_shared``. The browser sees only
the derived explorer bundle; raw data paths are provenance, not runtime
dependencies.
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
from pathlib import Path



def discover_explorers(root):
    """Return validated explorer manifests in stable experiment/title order."""
    root = Path(root)
    explorers_root = root / "explorers"
    found = []
    if not explorers_root.is_dir():
        return found

    for manifest_path in sorted(explorers_root.rglob("explorer.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entry = manifest_path.parent / manifest.get("entry", "index.html")
        if not entry.is_file():
            continue
        rel_dir = manifest_path.parent.relative_to(root)
        found.append({
            "title": str(manifest.get("title") or rel_dir.name),
            "experiment": str(manifest.get("experiment") or ""),
            "description": str(manifest.get("description") or ""),
            "method": str(manifest.get("method") or "Interactive viewer"),
            "detail": str(manifest.get("detail") or ""),
            "rel_dir": rel_dir,
            "entry": entry.name,
            "source_dir": manifest_path.parent,
        })
    return sorted(found, key=lambda item: (item["experiment"], item["title"]))


def explorer_links(root):
    """Explorer entry points keyed by experiment id (``CODE-NN``).

    The experiment catalog and the report experiment tables link each session to
    its explorers through these; hrefs are relative to the catalog root.
    """
    links = {}
    for item in discover_explorers(root):
        if item["experiment"]:
            links.setdefault(item["experiment"], []).append({
                "title": item["title"],
                "href": f'{item["rel_dir"].as_posix()}/{item["entry"]}',
            })
    return links


def explorer_cell(links):
    """Table-cell HTML for one session's explorers, or ``-`` when it has none."""
    if not links:
        return "-"
    return " ".join(
        f'<a class="explorer-link" href="{html.escape(link["href"], quote=True)}" '
        f'title="{html.escape(link["title"], quote=True)}">Open</a>'
        for link in links
    )


def generate_explorers(root, catalog_out=None, plugins=None):
    """Copy the explorer bundles into a full static export.

    Explorers are linked from the experiment catalog and the report tables, not
    from a page of their own. The server mounts ``ROOT/explorers`` directly; an
    export to a directory outside ``ROOT/catalog`` gets the whole tree (bundles
    and the ``_shared`` viewer), because Luxar loads hashed JS/WASM and Zarr
    chunks dynamically and an HTML-reference scraper cannot discover those files.
    """
    root = Path(root)
    catalog_dir = Path(catalog_out) if catalog_out else root / "catalog"
    source = root / "explorers"
    if source.is_dir() and catalog_dir.resolve() != (root / "catalog").resolve():
        shutil.copytree(source, catalog_dir / "explorers", dirs_exist_ok=True)
    print(f"Explorers: {len(discover_explorers(root))}")
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--catalog-out", type=Path, default=None)
    args = parser.parse_args(argv)
    generate_explorers(args.root, args.catalog_out)


if __name__ == "__main__":
    main()
