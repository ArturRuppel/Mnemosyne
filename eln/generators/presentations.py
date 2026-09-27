#!/usr/bin/env python3
"""Generate the presentations catalog page (``presentations.html``).

Scans ``ROOT/presentations``; each subdirectory containing an ``index.html`` is
treated as a presentation. No database is read.
"""

import argparse
import re
from pathlib import Path

from eln.generators.nav import render_nav

# Presentation decks open in a separate window. window.open with explicit
# width/height/left/top requests a popup *window* (not a tab); the click handler
# preventDefault stops the anchor from also navigating in place. The raw <a href>
# stays as a no-JS fallback. Defined as a plain string (not inside the page
# f-string) so the JS braces need no escaping.
PRESENTATION_WINDOW_SCRIPT = '''
    <script>
    (function () {
        function openDeck(url) {
            var w = Math.min(1600, Math.round(screen.availWidth * 0.9));
            var h = Math.min(1000, Math.round(screen.availHeight * 0.9));
            var left = Math.round((screen.availWidth - w) / 2) + (screen.availLeft || 0);
            var top = Math.round((screen.availHeight - h) / 2) + (screen.availTop || 0);
            var features = 'popup=yes,noopener,width=' + w + ',height=' + h +
                           ',left=' + left + ',top=' + top;
            window.open(url, '_blank', features);
        }
        document.querySelectorAll('.presentation-link').forEach(function (a) {
            a.addEventListener('click', function (e) {
                e.preventDefault();
                openDeck(a.href);
            });
        });
    })();
    </script>'''


def parse_presentation_dir(dirname):
    """Extract date and title from directory name like '2026-01-21_QBio_seminar_Pasteur'."""
    match = re.match(r'(\d{4}-\d{2}-\d{2})_(.*)', dirname)
    if match:
        date = match.group(1)
        title = match.group(2).replace('_', ' ')
        return date, title
    return None, dirname.replace('_', ' ')


def count_slides(pres_dir):
    """Count PNG files in the slides/ subdirectory."""
    slides_dir = pres_dir / "slides"
    if slides_dir.exists():
        return len(list(slides_dir.glob("*.png")))
    return 0


def generate_presentations(root, catalog_out=None):
    """Generate ``presentations.html`` by scanning ``root/presentations``.

    Output is written to *catalog_out* (default ``root/catalog``).
    """
    root = Path(root)
    presentations_dir = root / "presentations"
    catalog_dir = Path(catalog_out) if catalog_out else root / "catalog"

    presentations = []

    if presentations_dir.exists():
        for pres_dir in sorted(presentations_dir.iterdir(), reverse=True):
            if pres_dir.is_dir() and (pres_dir / "index.html").exists():
                date, title = parse_presentation_dir(pres_dir.name)
                slide_count = count_slides(pres_dir)
                presentations.append({
                    'dirname': pres_dir.name,
                    'date': date or '',
                    'title': title,
                    'slide_count': slide_count,
                })

    # Build HTML
    rows = ""
    for p in presentations:
        rows += f"""
            <tr data-pres-dir="{p['dirname']}">
                <td>{p['date']}</td>
                <td><a href="presentations/{p['dirname']}/index.html" class="presentation-link">{p['title']}</a></td>
                <td>{p['slide_count']}</td>
            </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Presentations</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #262033; background: #f1eff5; }}
        .header {{ background: #2d1f4e; color: white; padding: 1.25rem 1.5rem; }}
        .header h1 {{ font-size: 1.55rem; margin-bottom: 0.25rem; }}
        .header p {{ color: #ddd3ee; }}
        .nav {{ display: flex; flex-wrap: wrap; gap: 1rem; background: white; padding: 0.8rem 1.5rem; border-bottom: 1px solid #dcd8e3; }}
        .nav a {{ color: #0f766e; text-decoration: none; font-weight: 650; }}
        .nav a:hover {{ text-decoration: underline; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 1.5rem; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }}
        .stat-card {{ background: white; padding: 1rem 1.25rem; border: 1px solid #dcd8e3; border-radius: 8px; }}
        .stat-card .number {{ font-size: 1.5rem; font-weight: 700; color: #6b3fa0; }}
        .stat-card .label {{ color: #6c6680; margin-top: 0.25rem; font-size: 0.85rem; }}
        .table-container {{ background: white; border: 1px solid #dcd8e3; border-radius: 8px; overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
        th {{ background: #f4f2f7; color: #564f66; padding: 0.65rem; text-align: left; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; border-bottom: 1px solid #e4e0ea; }}
        td {{ padding: 0.65rem; border-bottom: 1px solid #e4e0ea; vertical-align: top; }}
        tr:hover {{ background: #faf9fc; }}
        .presentation-link {{ color: #0f766e; text-decoration: none; font-weight: 600; }}
        .presentation-link:hover {{ text-decoration: underline; }}
        .footer {{ text-align: center; padding: 1.5rem; color: #6c6680; font-size: 0.85rem; margin-top: 2rem; }}
    </style>
</head>
<body>
    <script src="auth.js"></script>
    <div class="header">
        <div style="display: flex; align-items: center; gap: 0.8rem;">
            <svg width="34" height="34" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M50 10 C 50 10, 40 24, 40 31 A 10 10 0 0 0 60 31 C 60 24, 50 10, 50 10 Z" fill="#f1eff5"></path><g stroke="#5cc9bb" stroke-linecap="round"><ellipse cx="50" cy="70" rx="12" ry="4" stroke-width="4.5"></ellipse><ellipse cx="50" cy="70" rx="27" ry="9" stroke-width="4" stroke-opacity="0.75"></ellipse><ellipse cx="50" cy="70" rx="42" ry="15" stroke-width="3.5" stroke-opacity="0.45"></ellipse></g></svg>
            <h1>Mnemosyne</h1>
        </div>
        <p style="margin-left: calc(34px + 0.8rem);">Presentations</p>
    </div>

    {render_nav()}

    <div class="container">
        <div class="stats">
            <div class="stat-card">
                <div class="number">{len(presentations)}</div>
                <div class="label">Total Presentations</div>
            </div>
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="width: 15%;">Date</th>
                        <th>Title</th>
                        <th style="width: 10%;">Slides</th>
                    </tr>
                </thead>
                <tbody>{rows}
                </tbody>
            </table>
        </div>
    </div>

    <div class="footer">
        Mnemosyne
    </div>
{PRESENTATION_WINDOW_SCRIPT}
</body>
</html>"""

    catalog_dir.mkdir(parents=True, exist_ok=True)
    output_file = catalog_dir / "presentations.html"
    output_file.write_text(html)
    print(f"Presentations catalog generated at: {output_file}")
    return output_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="data-repo root (holds presentations/)")
    parser.add_argument("--catalog-out", type=Path, default=None,
                        help="output directory (default: ROOT/catalog)")
    args = parser.parse_args(argv)
    generate_presentations(args.root, args.catalog_out)


if __name__ == "__main__":
    main()
