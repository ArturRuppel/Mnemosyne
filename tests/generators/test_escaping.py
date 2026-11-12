"""Database values reach generated pages as text, never as markup or script."""

import sqlite3
from html.parser import HTMLParser

import pytest

from eln.db import init_db
from eln.generators import generate_catalog, generate_protocol_catalog
from eln.generators.protocols import markdown_to_html

HOSTILE = """He said "stop" & left <script>alert('x')</script>"""
PROTOCOL = """Dad's "fast" <b>gel</b>"""


@pytest.fixture
def root(tmp_path):
    db = tmp_path / "experiments.db"
    init_db.init_db(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO experiment_codes (title, code) VALUES (?, 'SYNTH')", (HOSTILE,))
    conn.execute(
        "INSERT INTO experiments (id, experiment_type, repetition, excluded, file_path, "
        "cell_types, microscope, live_or_fixed, comments) VALUES (1, ?, 1, 0, 'x', ?, ?, ?, ?)",
        (HOSTILE, f"A549, {HOSTILE}", HOSTILE, HOSTILE, HOSTILE))
    conn.execute("INSERT INTO protocols (id, name, version, description, content, is_latest, "
                 "created_at) VALUES (10, ?, '1', ?, ?, 0, '2026-01-01')",
                 (PROTOCOL, HOSTILE, "# Old\n\n" + HOSTILE))
    conn.execute("INSERT INTO protocols (id, name, version, description, content, is_latest, "
                 "created_at, file_path) VALUES (11, ?, '2', ?, ?, 1, '2026-02-01', ?)",
                 (PROTOCOL, HOSTILE, "# New\n\n" + HOSTILE, HOSTILE))
    conn.execute("INSERT INTO experiment_protocols (experiment_id, protocol_id) VALUES (1, 11)")
    conn.execute("INSERT INTO tags (id, name) VALUES (5, ?)", (HOSTILE,))
    conn.execute("INSERT INTO experiment_tags (experiment_id, tag_id) VALUES (1, 5)")
    conn.execute("INSERT INTO experiment_channels (experiment_id, channel_order, channel_label, "
                 "target, modality) VALUES (1, 0, ?, ?, NULL)", (HOSTILE, HOSTILE))
    conn.commit()
    conn.close()
    return tmp_path


class _Collect(HTMLParser):
    """Attributes and text as a browser would decode them, plus every element name."""

    def __init__(self):
        super().__init__()
        self.attrs, self.tags, self.text, self.scripts = [], [], [], []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend(attrs)
        self._in_script = tag == "script"

    def handle_endtag(self, tag):
        self._in_script = False

    def handle_data(self, data):
        (self.scripts if self._in_script else self.text).append(data)


def parse(path):
    p = _Collect()
    p.feed(path.read_text())
    return p


def body_of(path):
    """The page minus its template scripts (which legitimately hold markup)."""
    html = path.read_text()
    return html[html.index("<body>"):]


def test_catalog_escapes_every_field(root):
    page = generate_catalog(root, catalog_out=root / "catalog", plugins=[])
    body = body_of(page)
    assert "<script>alert" not in body
    assert "<b>" not in body
    p = parse(page)
    # each attribute still holds the whole value: the quote did not end it early
    row = dict(a for a in p.attrs if a[0].startswith("data-"))
    assert row["data-comments"] == HOSTILE
    assert row["data-experiment_type"] == HOSTILE
    assert row["data-microscope"] == HOSTILE
    assert row["data-tags"] == HOSTILE
    assert row["data-protocol"] == PROTOCOL
    assert row["data-channels"] == f"{HOSTILE}: {HOSTILE}"
    # and the text shows it literally
    assert HOSTILE in "".join(p.text)
    assert PROTOCOL in "".join(p.text)


def test_protocols_escape_every_field(root):
    page = generate_protocol_catalog(root, catalog_out=root / "catalog", plugins=[])
    html = page.read_text()
    body = html[html.index("<body>"):html.index("const protocolVersions")]
    assert "<script>alert" not in body
    assert "<b>gel</b>" not in body
    p = parse(page)
    text = "".join(p.text)
    assert PROTOCOL in text and HOSTILE in text
    # the name rides in a data- attribute, not in an inline JS string
    assert ("data-protocol", PROTOCOL) in p.attrs
    assert ("onchange", "changeVersion(this)") in p.attrs
    assert not any(v and "Dad" in v for k, v in p.attrs if k.startswith("on"))


def test_protocols_json_cannot_close_its_script(root):
    page = generate_protocol_catalog(root, catalog_out=root / "catalog", plugins=[])
    html = page.read_text()
    script = html[html.index("const protocolVersions"):]
    script = script[:script.index("</script>")]
    # the only </script> after the JSON is the template's own
    assert "alert(" in script  # the content is there, as data
    assert "<" not in script.split(";", 1)[0]


def test_markdown_escapes_quotes_so_a_link_cannot_grow_attributes():
    p = _Collect()
    p.feed(markdown_to_html('[x](a"onmouseover=alert(1))'))
    assert [k for k, _ in p.attrs] == ["href"]


def test_markdown_escapes_markup():
    assert "<script>" not in markdown_to_html("<script>alert('x')</script>")


def test_report_series_overview_escapes_database_values(root):
    from eln.generators.reports import build_experiments_block
    conn = sqlite3.connect(root / "experiments.db")
    conn.row_factory = sqlite3.Row
    block = build_experiments_block("SYNTH", conn, None)
    conn.close()
    assert "<script>alert" not in block and "<b>gel</b>" not in block
    p = _Collect()
    p.feed(block)
    text = "".join(p.text)
    assert HOSTILE in text and PROTOCOL in text


def test_report_card_title_from_the_series_is_escaped(root):
    from eln.generators import generate_reports
    (root / "reports").mkdir()
    (root / "reports" / "synth.md").write_text("# Synth\n\n**Series:** SYNTH\n\nBody.\n")
    generate_reports(root, catalog_out=root / "catalog", plugins=[])
    for page in (root / "catalog").glob("*.html"):
        assert "<script>alert" not in body_of(page), page.name


def test_presentation_dir_names_are_escaped(tmp_path):
    from eln.generators import generate_presentations
    deck = tmp_path / "presentations" / '2026-01-01_a"b<i>c'
    deck.mkdir(parents=True)
    (deck / "index.html").write_text("<html></html>")
    out = generate_presentations(tmp_path, catalog_out=tmp_path / "catalog")
    p = parse(out)
    assert ("data-pres-dir", '2026-01-01_a"b<i>c') in p.attrs
    assert "i" not in p.tags
