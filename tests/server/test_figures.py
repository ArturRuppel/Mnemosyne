"""Saving a lab-book figure from Iris."""

import base64
import hashlib
import io
import json
import zipfile

import pytest

from eln.db import init_db
from eln.server.app import create_app

IRIS_URL = "https://iris.example:8766"
SVG = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'
FIGURE = "documents/note/analysis/fig.iris"
URL = f"/api/figures/{FIGURE}"


def iris_bytes(plots=1, marker="a"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps({"marker": marker}))
        for i in range(plots):
            z.writestr(f"analyses/{i:04d}-plot.json", "{}")
    return buf.getvalue()


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def root(tmp_path):
    init_db.init_db(tmp_path / "experiments.db")
    folder = tmp_path / "documents" / "note" / "analysis"
    folder.mkdir(parents=True)
    (folder / "fig.iris").write_bytes(iris_bytes())
    (folder / "fig.svg").write_text("<svg>old</svg>")
    return tmp_path


@pytest.fixture
def client(root):
    app = create_app(root, scan_roots=[], iris_url=IRIS_URL)
    app.config.update(TESTING=True)
    return app.test_client()


def put(client, iris, base, svg=SVG, session="s1", origin=IRIS_URL, url=URL):
    return client.put(url, headers={"Origin": origin}, json={
        "iris_base64": base64.b64encode(iris).decode(), "svg": svg,
        "base_sha256": base, "session": session})


def test_get_describes_the_figure(client):
    body = client.get(URL).get_json()
    assert body["plots"] == 1
    assert body["sha256"] == sha(iris_bytes())
    assert body["iris_url"] == IRIS_URL


def test_save_replaces_the_pair(client, root):
    new = iris_bytes(marker="b")
    r = put(client, new, sha(iris_bytes()))
    assert r.status_code == 200, r.text
    assert r.get_json()["sha256"] == sha(new)
    folder = root / "documents/note/analysis"
    assert (folder / "fig.iris").read_bytes() == new
    assert (folder / "fig.svg").read_text() == SVG


def test_one_snapshot_per_session_and_a_chained_log(client, root):
    a, b, c = iris_bytes(), iris_bytes(marker="b"), iris_bytes(marker="c")
    put(client, b, sha(a))
    put(client, c, sha(b))
    put(client, a, sha(c), session="s2")
    versions = root / "documents/note/analysis/.versions/fig"
    snapshots = sorted(versions.glob("*.iris"))
    assert [p.read_bytes() for p in snapshots] == [a, c]
    assert len(list(versions.glob("*.svg"))) == 2

    lines = (versions / "log.jsonl").read_bytes().splitlines()
    assert len(lines) == 3
    entries = [json.loads(line) for line in lines]
    assert entries[0]["previous_line"] is None
    assert entries[1]["previous_line"] == sha(lines[0])
    assert entries[2]["previous_line"] == sha(lines[1])
    assert [e["snapshot"] is not None for e in entries] == [True, False, True]
    assert client.get(URL).get_json()["history"] == entries


@pytest.mark.parametrize("plots", [0, 2])
def test_refuses_anything_but_one_plot(client, root, plots):
    r = put(client, iris_bytes(plots=plots), sha(iris_bytes()))
    assert r.status_code == 422
    assert (root / FIGURE).read_bytes() == iris_bytes()


def test_refuses_a_file_changed_since_it_was_opened(client, root):
    r = put(client, iris_bytes(marker="b"), "stale")
    assert r.status_code == 409
    assert (root / FIGURE).read_bytes() == iris_bytes()
    assert not (root / "documents/note/analysis/.versions").exists()


def test_refuses_another_origin(client):
    r = put(client, iris_bytes(marker="b"), sha(iris_bytes()), origin="https://evil.example")
    assert r.status_code == 403


def test_refuses_saves_when_iris_is_not_configured(root):
    app = create_app(root, scan_roots=[])
    r = put(app.test_client(), iris_bytes(marker="b"), sha(iris_bytes()))
    assert r.status_code == 403


@pytest.mark.parametrize("svg", [
    "not xml", "<html/>",
    '<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>',
    '<!DOCTYPE svg [<!ENTITY a "b">]><svg/>',
])
def test_refuses_a_bad_svg(client, svg):
    assert put(client, iris_bytes(marker="b"), sha(iris_bytes()), svg=svg).status_code == 422


@pytest.mark.parametrize("rel", [
    "documents/../experiments.db", "documents/note/x.txt", "catalog/x.iris",
    "documents/note/analysis/.versions/fig/x.iris",
])
def test_refuses_paths_outside_the_figures(client, rel):
    r = put(client, iris_bytes(), "x", url=f"/api/figures/{rel}")
    assert r.status_code in (403, 404)


def test_refuses_a_missing_figure(client):
    assert client.get("/api/figures/documents/note/none.iris").status_code == 404
