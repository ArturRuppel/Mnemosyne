import json

from eln.generators.explorers import (
    discover_explorers,
    explorer_cell,
    explorer_links,
    generate_explorers,
)


def _bundle(root):
    bundle = root / "explorers" / "CIRCP-01" / "pilot"
    (bundle / "viewer" / "assets").mkdir(parents=True)
    (bundle / "data" / "c" / "0").mkdir(parents=True)
    (bundle / "index.html").write_text(
        '<iframe src="./viewer/?src=../data"></iframe>', encoding="utf-8"
    )
    (bundle / "viewer" / "index.html").write_text(
        '<script src="assets/viewer.js"></script>', encoding="utf-8"
    )
    (bundle / "viewer" / "assets" / "viewer.js").write_text("viewer")
    (bundle / "data" / "zarr.json").write_text("{}")
    (bundle / "data" / "c" / "0" / "0").write_bytes(b"chunk")
    (bundle / "explorer.json").write_text(json.dumps({
        "title": "CIRCP 561 nm",
        "experiment": "CIRCP-01",
        "description": "Position 0",
        "method": "Luxar",
        "detail": "3,436 splats",
    }))
    return bundle


def test_discovers_manifest_with_entry(tmp_path):
    _bundle(tmp_path)
    items = discover_explorers(tmp_path)
    assert len(items) == 1
    assert items[0]["experiment"] == "CIRCP-01"


def test_links_are_keyed_by_experiment(tmp_path):
    _bundle(tmp_path)
    links = explorer_links(tmp_path)
    assert links == {"CIRCP-01": [{"title": "CIRCP 561 nm",
                                   "href": "explorers/CIRCP-01/pilot/index.html"}]}


def test_cell_renders_link_or_dash():
    assert explorer_cell(None) == "-"
    cell = explorer_cell([{"title": "A & B", "href": "explorers/X-01/index.html"}])
    assert 'href="explorers/X-01/index.html"' in cell
    assert 'title="A &amp; B"' in cell


def test_no_page_of_its_own(tmp_path):
    _bundle(tmp_path)
    assert generate_explorers(tmp_path) is None
    assert not (tmp_path / "catalog" / "explorers.html").exists()


def test_external_catalog_output_copies_entire_dynamic_bundle(tmp_path):
    bundle = _bundle(tmp_path)
    (tmp_path / "explorers" / "_shared").mkdir()
    (tmp_path / "explorers" / "_shared" / "explorer.js").write_text("shared")
    out = tmp_path.parent / f"{tmp_path.name}-export"
    generate_explorers(tmp_path, catalog_out=out)
    copied = out / bundle.relative_to(tmp_path)
    assert (copied / "viewer" / "assets" / "viewer.js").read_text() == "viewer"
    assert (copied / "data" / "c" / "0" / "0").read_bytes() == b"chunk"
    assert (out / "explorers" / "_shared" / "explorer.js").read_text() == "shared"
