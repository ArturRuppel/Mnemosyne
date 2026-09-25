import json

from eln.db import init_db
from eln.generators import generate_all
from eln.server import create_app


def test_explorer_bundle_is_served_without_a_catalog_page(tmp_path):
    init_db.init_db(tmp_path / "experiments.db")
    bundle = tmp_path / "explorers" / "CIRCP-01" / "pilot"
    (bundle / "viewer").mkdir(parents=True)
    (bundle / "index.html").write_text(
        '<h1>CIRCP explorer</h1><iframe id="viewer"></iframe>'
        '<script>const dataUrl = new URL("./data", window.location.href);'
        'const viewerUrl = new URL("./viewer/index.html", window.location.href);</script>'
    )
    (bundle / "viewer" / "index.html").write_text("<canvas></canvas>")
    (bundle / "explorer.json").write_text(json.dumps({
        "title": "CIRCP 561 nm",
        "experiment": "CIRCP-01",
    }))
    generate_all(tmp_path)

    app = create_app(tmp_path, scan_roots=[])
    app.config.update(TESTING=True)
    client = app.test_client()

    assert client.get("/explorers.html").status_code == 404
    entry = client.get("/explorers/CIRCP-01/pilot/index.html")
    assert entry.status_code == 200
    assert b"CIRCP explorer" in entry.data
    assert b'new URL("./data", window.location.href)' in entry.data
    assert b'new URL("./viewer/index.html", window.location.href)' in entry.data
    viewer = client.get("/explorers/CIRCP-01/pilot/viewer/index.html")
    assert viewer.status_code == 200
    assert b"<canvas></canvas>" in viewer.data
