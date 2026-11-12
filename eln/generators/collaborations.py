#!/usr/bin/env python3
"""Generate the Collaborations tab (``collaborations.html``).

A document under ``ROOT/documents`` is a *collaboration* when its front matter
carries a ``**Collaborators:** Name, Name`` line. The files stay where they are,
so every link to them and the document edit API keep working; only the rendering
splits. The Documents page skips them, and this tab shows them as the same tiles
as the Reports index (title, date, byline, preview, summary), each linking to
its own page ``collaboration-<slug>.html``, flat next to the index so that
catalog-relative links inside the document resolve unchanged.
"""

import argparse
import posixpath
import re
from pathlib import Path

from eln.generators.code import build_code_index
from eln.generators.documents import (
    document_slug,
    parse_collaborators,
    read_document,
)
from eln.generators.nav import render_nav
from eln.generators.reports import (
    REPORTS_HTML_TEMPLATE,
    THUMBNAIL_RE,
    _VIDEO_EXT,
    _attr,
    _escape,
    _rewrite_relative_images,
    discover_report_files,
    extract_report_date,
    extract_summary,
    first_image,
    markdown_to_html,
    render_notebook_full,
)

PAGE_NAME = "collaborations.html"
PAGE_GLOB = "collaboration-*.html"

_KEY_LINE_RE = re.compile(r'^\*\*(?!Summary:)[^*\n]+:\*\*.*$\n?', re.MULTILINE)
_H1_LINE_RE = re.compile(r'^# .*$\n?', re.MULTILINE)


def collaboration_page_name(slug):
    """File name of a collaboration's own page, flat next to the index."""
    return f"collaboration-{slug}.html"


def _summary_source(content):
    """*content* without the H1 and the ``**Key:**`` front-matter lines.

    ``extract_summary`` skips a whole paragraph that starts with a heading or a
    bold key, so prose that follows such a line in the same paragraph would be
    lost; removing the lines first lets the first prose sentence through."""
    return _KEY_LINE_RE.sub("", _H1_LINE_RE.sub("", content))


def _render(doc_file, root, code_index):
    """Everything one collaboration needs, or ``None`` for a malformed notebook."""
    doc = read_document(doc_file)
    if doc is None:
        return None
    nb, content = doc
    collaborators = parse_collaborators(content)
    if not collaborators:
        return None

    doc_dir = doc_file.parent.relative_to(root)
    thumb_decl = THUMBNAIL_RE.search(content)
    content = THUMBNAIL_RE.sub("", content)
    content = _rewrite_relative_images(content, doc_dir)

    title_match = re.search(r"^# (.+)$", content, re.MULTILINE)
    title = (title_match.group(1).strip() if title_match
             else doc_file.stem.replace("_", " ").replace("-", " ").title())
    return {
        "nb": nb,
        "content": content,
        "html": markdown_to_html(content),
        "title": title,
        "slug": document_slug(doc_file, root),
        "date": extract_report_date(content, doc_file),
        "collaborators": collaborators,
        "thumb_decl": thumb_decl.group(1) if thumb_decl else None,
        "doc_dir": doc_dir,
        "rel_src": doc_file.relative_to(root).as_posix(),
        "code_html": (render_notebook_full(nb, doc_dir, code_index)
                      if nb is not None else None),
    }


def _page_card(d):
    slug = d["slug"]
    if d["code_html"] is not None:
        toggle = f"""
                        <div class="report-view-toggle">
                            <button type="button" class="view-btn active" id="btn-report-{slug}"
                                    onclick="setReportView('{slug}', 'report')">Report</button>
                            <button type="button" class="view-btn" id="btn-code-{slug}"
                                    onclick="setReportView('{slug}', 'code')">Code</button>
                        </div>"""
        code_pane = f"""
                        <div class="report-code" id="code-{slug}" style="display: none;">
                            {d["code_html"]}
                        </div>"""
    else:
        toggle = code_pane = ""
    return f"""
                <a class="report-back" href="{PAGE_NAME}">&larr; All collaborations</a>
                <div class="report-card" id="report-{slug}" data-report-src="{_attr(d["rel_src"])}">
                    <div class="report-header standalone">
                        <div class="report-title-row">
                            {_attr(d["title"])}
                        </div>
                        <div class="report-date">{_attr(d["date"])}</div>
                    </div>
                    <div class="report-details" id="details-{slug}" style="display: block;">{toggle}
                        <div class="report-view" id="view-{slug}">
                            <div class="report-content">
                                {d["html"]}
                            </div>
                        </div>{code_pane}
                    </div>
                </div>
            """


def _tile(d):
    thumb = (posixpath.normpath(f"{d['doc_dir'].as_posix()}/{d['thumb_decl']}")
             if d["thumb_decl"] else None) or first_image(d["content"])
    if not thumb:
        thumb_html = f'<span class="tile-placeholder">{_escape(d["title"][:1])}</span>'
    elif thumb.lower().endswith(_VIDEO_EXT):
        thumb_html = f'<video src="{_attr(thumb)}#t=0.1" muted playsinline preload="metadata"></video>'
    else:
        thumb_html = f'<img src="{_attr(thumb)}" alt="" loading="lazy">'
    summary = extract_summary(_summary_source(d["content"]))
    summary_html = f'<p class="tile-summary">{_escape(summary)}</p>' if summary else ""
    href = collaboration_page_name(d["slug"])
    byline = _escape(", ".join(d["collaborators"]))
    # The id is not "tile-<slug>": the shared template redirects those hashes to
    # report-<slug>.html, which is the wrong page for a collaboration.
    return f"""
                <article class="report-tile" id="collab-{d["slug"]}" data-report-src="{_attr(d["rel_src"])}">
                    <h2 class="tile-title"><a href="{href}">{_attr(d["title"])}</a></h2>
                    <div class="tile-date">{_attr(d["date"])}</div>
                    <div class="tile-byline">with {byline}</div>
                    <a class="tile-thumb" href="{href}" tabindex="-1" aria-hidden="true">{thumb_html}</a>
                    {summary_html}
                </article>"""


def generate_collaborations(root, catalog_out=None, plugins=None):
    """Generate ``collaborations.html`` and one page per collaboration.

    Scans ``root/documents`` for documents with a ``**Collaborators:**`` line.
    Output goes to *catalog_out* (default ``root/catalog``); pages of
    collaborations that were removed or lost the line are deleted.
    """
    root = Path(root)
    catalog_dir = Path(catalog_out) if catalog_out else root / "catalog"
    nav = render_nav(plugins, current=PAGE_NAME)
    code_index = build_code_index(root)

    docs = [d for d in (_render(f, root, code_index)
                        for f in discover_report_files(root / "documents")) if d]
    # Newest first by the date shown (a range's start), not by file mtime.
    docs.sort(key=lambda d: d["date"][:10], reverse=True)

    pages = {}
    for d in docs:
        pages[collaboration_page_name(d["slug"])] = REPORTS_HTML_TEMPLATE.format(
            nav=nav, reports_html=_page_card(d),
            page_title=_escape(d["title"]), page_heading="Collaborations")

    if docs:
        index_html = ('<div class="report-tiles">' + "".join(_tile(d) for d in docs)
                      + '\n            </div>')
    else:
        index_html = ('<div class="no-reports">No collaborations yet. Add '
                      '<code>**Collaborators:** Name, Name</code> to a document '
                      'under documents/.</div>')
    pages[PAGE_NAME] = REPORTS_HTML_TEMPLATE.format(
        nav=nav, reports_html=index_html,
        page_title="Collaborations", page_heading="Collaborations")

    catalog_dir.mkdir(parents=True, exist_ok=True)
    for stale in catalog_dir.glob(PAGE_GLOB):
        if stale.name not in pages:
            stale.unlink()
    for name, html in pages.items():
        (catalog_dir / name).write_text(html)

    output_file = catalog_dir / PAGE_NAME
    print(f"Collaborations page generated at: {output_file}")
    print(f"Total collaborations: {len(docs)}")
    return output_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="data-repo root (holds documents/)")
    parser.add_argument("--catalog-out", type=Path, default=None,
                        help="output directory (default: ROOT/catalog)")
    args = parser.parse_args(argv)
    generate_collaborations(args.root, args.catalog_out)


if __name__ == "__main__":
    main()
