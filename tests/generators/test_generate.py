"""Static page generators: end-to-end against a tiny data root, plus the core
byte-identical-regeneration guarantee (no timestamp churn)."""

import os
import re
import sqlite3
from datetime import datetime

import pytest

from eln.db import init_db
from eln.sdgl import SDGL
from eln.generators import (
    generate_all,
    generate_catalog,
    generate_reports,
    generate_protocol_catalog,
    generate_presentations,
)
from eln.generators.reports import parse_series, build_experiments_block


def _touch(path, ts):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    os.utime(path, (ts, ts))


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """A data-repo root: experiments.db (with protocols/tags/channels), an SDGL
    scan over a CODE-NN tree, a report using the Plan F overview, and a slide deck."""
    root = tmp_path
    db = root / "experiments.db"
    init_db.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO experiment_codes (title, code) VALUES ('Traction Force', 'TFMSP')")
    # Two active reps + one excluded (excluded must be omitted from the overview).
    conn.execute("INSERT INTO experiments (id, experiment_type, repetition, excluded, file_path, "
                 "cell_types, microscope) VALUES (1,'Traction Force',1,0,'x','HUVEC','Spinning disk')")
    conn.execute("INSERT INTO experiments (id, experiment_type, repetition, excluded, file_path) "
                 "VALUES (2,'Traction Force',2,0,'x')")
    conn.execute("INSERT INTO experiments (id, experiment_type, repetition, excluded, file_path) "
                 "VALUES (3,'Traction Force',3,1,'x')")
    # A protocol (latest) linked to rep 1.
    conn.execute("INSERT INTO protocols (id, name, version, description, content, is_latest) "
                 "VALUES (10,'Gel casting','2','How to cast','# Gel casting\n\nMix **A** and B.',1)")
    conn.execute("INSERT INTO experiment_protocols (experiment_id, protocol_id) VALUES (1, 10)")
    # A tag + a channel on rep 1.
    conn.execute("INSERT INTO tags (id, name) VALUES (5, 'migration')")
    conn.execute("INSERT INTO experiment_tags (experiment_id, tag_id) VALUES (1, 5)")
    conn.execute("INSERT INTO experiment_channels (experiment_id, channel_order, channel_label, "
                 "target, modality) VALUES (1, 0, 'Blue', 'F-actin', 'Fluorescence')")
    conn.commit()
    conn.close()

    data = root / "data"
    ts1 = datetime(2025, 3, 10, 12, 0).timestamp()
    ts2 = datetime(2025, 4, 15, 9, 0).timestamp()
    _touch(data / "TFMSP-01" / "raw" / "img.tif", ts1)
    _touch(data / "TFMSP-02" / "raw" / "img.tif", ts2)

    # A report that embeds the Plan F overview, and one that does not.
    reports = root / "reports"
    (reports / "weekly").mkdir(parents=True)
    (reports / "weekly" / "tfm_progress.md").write_text(
        "# TFM progress\n\n**Series:** TFMSP\n\n**Date:** 2025-03-10\n\n{{experiments}}\n\nLooking good.\n"
    )
    (reports / "notes.md").write_text("# Random notes\n\nNo series here.\n")

    # A presentation directory.
    pres = root / "presentations" / "2025-05-01_Lab_meeting"
    pres.mkdir(parents=True)
    (pres / "index.html").write_text("<html></html>")
    (pres / "slides").mkdir()
    (pres / "slides" / "1.png").write_bytes(b"x")

    expected = {
        1: datetime.fromtimestamp(ts1).strftime("%Y-%m-%d"),
        2: datetime.fromtimestamp(ts2).strftime("%Y-%m-%d"),
    }

    # Unified config (discoverable via LABBOOK_CONFIG) so scan_from_config works.
    cfg = root / "labbook.toml"
    cfg.write_text(
        f'data_root = "{root}"\n\n[scanner]\nrun_on_startup = false\n\n'
        '[[scan_roots]]\nname = "data"\npath = "data"\n'
    )
    monkeypatch.setenv("LABBOOK_CONFIG", str(cfg))

    # Run a real SDGL scan so sdgl.db exists and dates are derivable.
    SDGL(root).scan_from_config()
    return root, db, expected


# --- pure helpers -----------------------------------------------------------

def test_parse_series():
    assert parse_series("intro\n**Series:** TFMSP\nrest") == "TFMSP"
    assert parse_series("no series declared") is None


def test_build_experiments_block_unknown_series_is_inline_error(data_root):
    root, db, _ = data_root
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    html = build_experiments_block("ZZZZZ", conn, None)
    conn.close()
    assert "exp-overview-error" in html and "ZZZZZ" in html


# --- end-to-end -------------------------------------------------------------

def test_generate_all_writes_all_pages(data_root):
    root, db, expected = data_root
    written = generate_all(root)
    catalog = root / "catalog"
    for page in ("experiments.html", "protocols.html", "reports.html",
                 "presentations.html", "documents.html", "code.html",
                 "posters.html"):
        assert (catalog / page).exists(), f"{page} missing"
    assert set(written) == {"experiments", "protocols", "reports",
                            "presentations", "documents", "code", "posters"}
    assert not (catalog / "explorers.html").exists()


def _explorer(root, experiment):
    bundle = root / "explorers" / experiment
    bundle.mkdir(parents=True)
    (bundle / "index.html").write_text("<h1>viewer</h1>")
    (bundle / "explorer.json").write_text(
        '{"title": "TFM viewer", "experiment": "%s"}' % experiment)


def test_catalog_links_session_explorer(data_root):
    root, db, expected = data_root
    _explorer(root, "TFMSP-01")
    generate_catalog(root)
    html = (root / "catalog" / "experiments.html").read_text()
    assert '<th data-column="explorer">Explorer</th>' in html
    row = re.search(r'<tr data-id="1".*?</tr>', html, re.S).group(0)
    assert 'href="explorers/TFMSP-01/index.html"' in row
    other = re.search(r'<tr data-id="2".*?</tr>', html, re.S).group(0)
    assert "explorer-link" not in other


def test_report_overview_links_session_explorer(data_root):
    root, db, expected = data_root
    _explorer(root, "TFMSP-02")
    generate_reports(root)
    html = (root / "catalog" / "reports.html").read_text()
    assert "<th>Explorer</th>" in html
    assert 'href="explorers/TFMSP-02/index.html"' in html


def test_catalog_has_ids_and_derived_dates(data_root):
    root, db, expected = data_root
    generate_catalog(root)
    html = (root / "catalog" / "experiments.html").read_text()
    assert "TFMSP-01" in html
    assert "TFMSP-02" in html
    assert expected[1] in html and expected[2] in html


def test_catalog_orders_by_derived_date_and_sinks_undated(data_root):
    """The catalog is a chronological index: rows come out newest-first by the
    file-derived date, and rep 3 — which has no raw files, so no derivable date —
    lands last rather than sorting as if it were the oldest."""
    root, db, expected = data_root
    generate_catalog(root)
    html = (root / "catalog" / "experiments.html").read_text()

    # Newest first, undated last.
    order = re.findall(r'data-date="([^"]*)"', html)
    assert order == [expected[2], expected[1], ""]

    # The undated row renders the explicit "no raw files" dash, not a blank cell.
    assert "date-missing" in html

    # And the client-side comparator keeps blanks at the bottom in *both*
    # directions, so clicking Date into oldest-first does not float the undated
    # row to the top. Asserted on the emitted script since there is no JS runtime
    # in this suite.
    assert "if (!aValue !== !bValue) {" in html


def test_reports_inject_series_overview(data_root):
    root, db, expected = data_root
    generate_reports(root)
    html = (root / "catalog" / "reports.html").read_text()
    # The {{experiments}} token was replaced by the DB-generated overview...
    assert "{{experiments}}" not in html
    assert "exp-overview" in html
    assert "TFMSP-01" in html
    # ...excluded rep 3 is not listed, and the linked protocol appears.
    assert "TFMSP-03" not in html
    assert "Gel casting" in html
    # The non-series report still renders.
    assert "Random notes" in html


def test_protocols_and_presentations(data_root):
    root, db, _ = data_root
    generate_protocol_catalog(root)
    generate_presentations(root)
    catalog = root / "catalog"
    assert "Gel casting" in (catalog / "protocols.html").read_text()
    assert "Lab meeting" in (catalog / "presentations.html").read_text()


def test_regeneration_is_byte_identical(data_root):
    """The core guarantee: regenerating twice over unchanged inputs yields the
    same bytes (static footers; date-only 'Last updated')."""
    root, db, _ = data_root
    generate_all(root)
    catalog = root / "catalog"
    first = {p.name: p.read_bytes() for p in catalog.glob("*.html")}
    generate_all(root)
    second = {p.name: p.read_bytes() for p in catalog.glob("*.html")}
    assert first.keys() == second.keys()
    for name in first:
        assert first[name] == second[name], f"{name} changed across regeneration"
