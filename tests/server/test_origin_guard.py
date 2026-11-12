"""The app-wide Host / Origin guard that stands in for authentication."""

import base64
import hashlib
import io
import json
import zipfile

import pytest

from eln.db import init_db
from eln.server.app import create_app

FOREIGN = "https://evil.example"
IRIS_URL = "https://iris.example:8766"
FIGURE = "documents/note/analysis/fig.iris"
SVG = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'


def iris_bytes(marker="a"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("manifest.json"), json.dumps({"marker": marker}))
        z.writestr(zipfile.ZipInfo("analyses/0000-plot.json"), "{}")
    return buf.getvalue()


@pytest.fixture
def root(tmp_path):
    init_db.init_db(tmp_path / "experiments.db")
    folder = tmp_path / "documents" / "note" / "analysis"
    folder.mkdir(parents=True)
    (folder / "fig.iris").write_bytes(iris_bytes())
    (folder / "fig.svg").write_text("<svg>old</svg>")
    return tmp_path


def make_client(root, **kw):
    app = create_app(root, scan_roots=[], **kw)
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def client(root):
    return make_client(root, iris_url=IRIS_URL)


def new_experiment(client, **headers):
    return client.post("/api/experiments", headers=headers, json={
        "experiment_type": "Synthetic", "code": "SYNTH", "comments": "x"})


# ---- writes from a foreign origin ----------------------------------------

def test_foreign_origin_post_is_refused(client):
    assert new_experiment(client, Origin=FOREIGN).status_code == 403
    assert client.get("/api/experiments").get_json() == []


def test_foreign_origin_delete_is_refused(client):
    assert new_experiment(client).status_code == 200
    (exp,) = client.get("/api/experiments").get_json()
    r = client.delete(f"/api/experiments/{exp['id']}", headers={"Origin": FOREIGN})
    assert r.status_code == 403
    assert client.get(f"/api/experiments/{exp['id']}").status_code == 200


def test_null_origin_is_refused(client):
    assert new_experiment(client, Origin="null").status_code == 403


def test_another_port_on_the_same_host_is_another_origin(client):
    assert new_experiment(client, Origin="http://localhost:9999").status_code == 403


def test_cross_site_fetch_metadata_is_refused(client):
    r = new_experiment(client, **{"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_preflight_from_a_foreign_origin_gets_no_cors(client):
    r = client.options("/api/experiments/1", headers={
        "Origin": FOREIGN, "Access-Control-Request-Method": "DELETE"})
    assert "Access-Control-Allow-Origin" not in r.headers
    assert "Access-Control-Allow-Methods" not in r.headers


def test_reads_carry_no_cors(client):
    r = client.get("/api/experiments", headers={"Origin": FOREIGN})
    assert "Access-Control-Allow-Origin" not in r.headers


# ---- writes that must keep working ---------------------------------------

def test_no_origin_post_still_works(client):
    # curl, the labbook CLI and agents on loopback send no Origin
    r = new_experiment(client)
    assert r.status_code == 200, r.text


def test_same_origin_post_works(client):
    r = new_experiment(client, Origin="http://localhost", **{"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200, r.text


def test_same_origin_behind_a_tls_proxy_works(root):
    # Tailscale Serve: the browser says https, Flask sees http, the Host is kept
    c = make_client(root, allowed_hosts=["lab.example"])
    r = new_experiment(c, Origin="https://lab.example:5001",
                       **{"Host": "lab.example:5001", "X-Forwarded-Proto": "https"})
    assert r.status_code == 200, r.text


# ---- Host allow-list (DNS rebinding) -------------------------------------

def test_unknown_host_is_refused(client):
    assert client.get("/api/experiments", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/", headers={"Host": "evil.example:5001"}).status_code == 400


@pytest.mark.parametrize("host", ["localhost", "localhost:5001", "127.0.0.1:5001", "[::1]:5001"])
def test_loopback_hosts_are_served(client, host):
    assert client.get("/api/experiments", headers={"Host": host}).status_code == 200


def test_configured_host_is_served(root):
    c = make_client(root, allowed_hosts=["lab.example:5001", "10.0.0.7", "fd00::7"])
    for host in ("lab.example:5001", "LAB.example", "10.0.0.7:5001", "[fd00::7]:5001"):
        assert c.get("/api/experiments", headers={"Host": host}).status_code == 200, host


def test_iris_host_is_served(client):
    # whoever configured iris_url trusts its name; a path-mounted Iris shares it
    assert client.get("/api/experiments", headers={"Host": "iris.example:5001"}).status_code == 200


def test_plugin_routes_are_guarded(root):
    app = create_app(root, scan_roots=[])
    app.config.update(TESTING=True)
    app.add_url_rule("/plugin/write", "plugin_write", lambda: "ok", methods=["POST"])
    c = app.test_client()
    assert c.post("/plugin/write", headers={"Origin": FOREIGN}).status_code == 403
    assert c.post("/plugin/write", headers={"Host": "evil.example"}).status_code == 400
    assert c.post("/plugin/write").status_code == 200


# ---- the configured Iris -------------------------------------------------

def save(client, origin, base=None, **headers):
    return client.put(f"/api/figures/{FIGURE}", headers={"Origin": origin, **headers}, json={
        "iris_base64": base64.b64encode(iris_bytes("b")).decode(), "svg": SVG,
        "base_sha256": base or hashlib.sha256(iris_bytes()).hexdigest(), "session": "s1"})


def test_iris_on_its_own_origin_saves_a_figure_with_cors(client, root):
    pre = client.options(f"/api/figures/{FIGURE}", headers={
        "Origin": IRIS_URL, "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "content-type"})
    assert pre.headers["Access-Control-Allow-Origin"] == IRIS_URL
    assert "PUT" in pre.headers["Access-Control-Allow-Methods"]
    r = save(client, IRIS_URL, **{"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 200, r.text
    assert r.headers["Access-Control-Allow-Origin"] == IRIS_URL
    assert (root / FIGURE).read_bytes() == iris_bytes("b")


def test_iris_origin_gets_cors_on_figure_routes_only(client):
    assert new_experiment(client, Origin=IRIS_URL).status_code == 403
    pre = client.options("/api/experiments/1", headers={
        "Origin": IRIS_URL, "Access-Control-Request-Method": "DELETE"})
    assert "Access-Control-Allow-Origin" not in pre.headers


def test_path_mounted_iris_saves_same_origin(root):
    c = make_client(root, iris_url="https://lab.example:5001/iris")
    r = save(c, "https://lab.example:5001", Host="lab.example:5001")
    assert r.status_code == 200, r.text
    assert "Access-Control-Allow-Origin" not in r.headers


def test_figure_save_still_needs_an_origin(client):
    r = client.put(f"/api/figures/{FIGURE}", json={})
    assert r.status_code == 403


def test_foreign_origin_cannot_save_a_figure(client):
    assert save(client, FOREIGN).status_code == 403
    pre = client.options(f"/api/figures/{FIGURE}", headers={
        "Origin": FOREIGN, "Access-Control-Request-Method": "PUT"})
    assert "Access-Control-Allow-Origin" not in pre.headers
