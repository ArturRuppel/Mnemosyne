"""Collaborations tab — documents with a **Collaborators:** line."""

from eln.generators.collaborations import generate_collaborations
from eln.generators.documents import generate_documents


def _doc(root, dirname, filename, text):
    d = root / "documents" / dirname
    d.mkdir(parents=True)
    (d / filename).write_text(text)
    return d


PROSE = ("A first sentence about the project. A second sentence with more detail. "
         "A third sentence that must be cut.")


def _collab(root, dirname="2026-10-27_joint", extra="", body=PROSE):
    return _doc(root, dirname, "REPORT.md",
                f"# Joint Study\n\n**Date:** 2026-10-27\n**Author:** A. Writer\n"
                f"**Collaborators:** Ada Lovelace, Alan Turing\n{extra}\n{body}\n")


def test_no_collaborations_message(tmp_path):
    out = generate_collaborations(tmp_path)
    assert out.name == "collaborations.html"
    html = out.read_text()
    assert "No collaborations yet" in html
    assert 'aria-current="page">Collaborations</a>' in html


def test_index_tile_has_title_date_byline_and_link(tmp_path):
    _collab(tmp_path)
    html = generate_collaborations(tmp_path).read_text()
    assert "Joint Study" in html
    assert "2026-10-27" in html
    assert '<div class="tile-byline">with Ada Lovelace, Alan Turing</div>' in html
    assert 'href="collaboration-2026-10-27_joint-REPORT.html"' in html


def test_non_collaboration_documents_are_ignored(tmp_path):
    _doc(tmp_path, "plain", "plain.md", "# Plain\n\n**Date:** 2026-01-01\n\nBody.\n")
    html = generate_collaborations(tmp_path).read_text()
    assert "No collaborations yet" in html
    assert "Plain" not in html


def test_tiles_newest_first_by_date(tmp_path):
    _doc(tmp_path, "old", "old.md",
         "# Old One\n\n**Date:** 2025-01-01\n**Collaborators:** X\n\nText.\n")
    _doc(tmp_path, "new", "new.md",
         "# New One\n\n**Date:** 2026-06-01\n**Collaborators:** Y\n\nText.\n")
    html = generate_collaborations(tmp_path).read_text()
    assert html.index("New One") < html.index("Old One")


def test_summary_is_prose_not_front_matter(tmp_path):
    _collab(tmp_path)
    html = generate_collaborations(tmp_path).read_text()
    assert ('<p class="tile-summary">A first sentence about the project. '
            'A second sentence with more detail.</p>') in html
    assert "third sentence" not in html.split("tile-summary")[1].split("</p>")[0]
    assert "Author:" not in html.split('class="tile-summary"')[1].split("</p>")[0]


def test_summary_survives_prose_directly_after_front_matter(tmp_path):
    _doc(tmp_path, "tight", "tight.md",
         "# Tight\n**Date:** 2026-02-02\n**Collaborators:** Z\nDirect prose here.\n")
    html = generate_collaborations(tmp_path).read_text()
    assert '<p class="tile-summary">Direct prose here.</p>' in html


def test_thumbnail_declaration_wins_and_is_stripped(tmp_path):
    _collab(tmp_path, extra="**Thumbnail:** cover.png\n", body="![fig](other.png)\n\n" + PROSE)
    out = generate_collaborations(tmp_path)
    html = out.read_text()
    assert '<img src="documents/2026-10-27_joint/cover.png"' in html
    page = (tmp_path / "catalog" / "collaboration-2026-10-27_joint-REPORT.html").read_text()
    assert "Thumbnail:" not in page


def test_first_image_fallback_and_placeholder(tmp_path):
    _collab(tmp_path, body="![fig](other.png)\n\n" + PROSE)
    html = generate_collaborations(tmp_path).read_text()
    assert '<img src="documents/2026-10-27_joint/other.png"' in html
    _doc(tmp_path, "bare", "bare.md", "# Zeta\n\n**Collaborators:** Q\n\nText.\n")
    html = generate_collaborations(tmp_path).read_text()
    assert '<span class="tile-placeholder">Z</span>' in html


def test_per_document_page_is_open_with_back_link_and_untouched_links(tmp_path):
    _collab(tmp_path, body="![fig](plot.png)\n\nSee [explorer](explorers/e1/index.html) "
                           "and [data](documents/2026-10-27_joint/analysis/f.iris).\n")
    generate_collaborations(tmp_path)
    page = (tmp_path / "catalog" / "collaboration-2026-10-27_joint-REPORT.html").read_text()
    assert '<a class="report-back" href="collaborations.html">&larr; All collaborations</a>' in page
    assert 'style="display: block;"' in page
    assert "documents/2026-10-27_joint/plot.png" in page
    assert 'href="explorers/e1/index.html"' in page
    assert 'href="documents/2026-10-27_joint/analysis/f.iris"' in page
    assert 'data-report-src="documents/2026-10-27_joint/REPORT.md"' in page


def test_documents_page_excludes_collaboration_and_redirects(tmp_path):
    _collab(tmp_path)
    _doc(tmp_path, "plain", "plain.md", "# Plain Doc\n\n**Date:** 2026-01-01\n\nBody.\n")
    html = generate_documents(tmp_path).read_text()
    assert "Plain Doc" in html
    assert "Joint Study" not in html
    assert '"2026-10-27_joint-REPORT": "collaboration-2026-10-27_joint-REPORT.html"' in html


def test_documents_page_without_collaborations_has_no_redirect_map(tmp_path):
    _doc(tmp_path, "plain", "plain.md", "# Plain Doc\n\nBody.\n")
    assert "moved" not in generate_documents(tmp_path).read_text()


def test_stale_collaboration_pages_removed(tmp_path):
    d = _collab(tmp_path)
    generate_collaborations(tmp_path)
    page = tmp_path / "catalog" / "collaboration-2026-10-27_joint-REPORT.html"
    assert page.exists()
    (d / "REPORT.md").write_text("# Joint Study\n\nNo collaborators any more.\n")
    generate_collaborations(tmp_path)
    assert not page.exists()
