"""The chrome every page of the notebook shares: the family stylesheet, the notebook's own
shared rules, and the header.

Pages stay self-contained (they open from a file and survive ``eln export``), so nothing here
is linked: :func:`bake` writes the CSS and the header into a page in place of two markers.

- ``/*@HOUSE_CSS@*/`` at the top of a page's ``<style>`` becomes the family sheet followed by
  :data:`CHROME_CSS`. The page's own rules come after and win.
- ``<!--@HEADER Reports@-->`` becomes the header, with the text as the page's name.

``eln/static/harmonia/harmonia.css`` is a vendored, byte-identical copy of the Harmonia repo's
sheet (edit there, copy out). It defines the ``--hm-*`` tokens; the notebook's home colour is
teal, set by ``data-home="teal"`` on ``<html>``.
"""

import re
from pathlib import Path

_FAMILY_SHEET = Path(__file__).resolve().parents[1] / "static" / "harmonia" / "harmonia.css"

# The drop-and-ripples mark, drawn in the current colour.
_MARK = (
    '<svg viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    '<path d="M50 10 C 50 10, 40 24, 40 31 A 10 10 0 0 0 60 31 C 60 24, 50 10, 50 10 Z" fill="currentColor"></path>'
    '<g stroke="currentColor" stroke-linecap="round">'
    '<ellipse cx="50" cy="70" rx="12" ry="4" stroke-width="4.5"></ellipse>'
    '<ellipse cx="50" cy="70" rx="27" ry="9" stroke-width="4" stroke-opacity="0.75"></ellipse>'
    '<ellipse cx="50" cy="70" rx="42" ry="15" stroke-width="3.5" stroke-opacity="0.45"></ellipse>'
    '</g></svg>'
)

# Flat, square, ink on neutral grey: a 2px ink rule is structure, a 1px line separates rows,
# and teal marks what you act on. A page's own block follows this one and may add to it.
CHROME_CSS = """
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font: 400 15px/1.6 var(--hm-font); color: var(--hm-ink); background: var(--hm-ground); -webkit-text-size-adjust: 100%; }
        :focus-visible { outline: 2px solid var(--hm-home); outline-offset: 2px; }
        code, pre, kbd, samp { font-family: var(--hm-mono); }
        .header { display: flex; align-items: center; gap: 12px; min-height: 56px; padding: 0 1.5rem; background: var(--hm-ground); color: var(--hm-ink); border-bottom: 2px solid var(--hm-ink); line-height: 1; }
        .header .mark { flex: none; display: grid; place-items: center; width: 32px; height: 32px; background: var(--hm-home); color: var(--hm-on-home); }
        .header .mark svg { display: block; width: 68%; height: 68%; }
        .header h1 { font: 800 22px/1 var(--hm-font); letter-spacing: -.03em; white-space: nowrap; }
        .header p { padding-left: 12px; border-left: 2px solid var(--hm-divider); font: 700 11px/1.6 var(--hm-font); letter-spacing: .08em; text-transform: uppercase; color: var(--hm-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .nav { display: flex; flex-wrap: nowrap; gap: 24px; overflow-x: auto; white-space: nowrap; scrollbar-width: none; padding: 0 1.5rem; background: var(--hm-ground); border-bottom: 1px solid var(--hm-divider); }
        .nav::-webkit-scrollbar { display: none; }
        .nav a { flex: none; display: flex; align-items: center; height: 44px; color: var(--hm-dim); font: 700 13px/1 var(--hm-font); text-decoration: none; }
        .nav a:hover { color: var(--hm-ink); }
        .nav a[aria-current="page"] { color: var(--hm-ink); box-shadow: inset 0 -3px 0 var(--hm-home); }
        @media (max-width: 560px) {
            .header, .nav { padding-left: 1rem; padding-right: 1rem; }
            .header h1 { font-size: 18px; }
            .header p { display: none; }
        }
"""

_CSS_MARK = "/*@HOUSE_CSS@*/"
_HEADER_MARK = re.compile(r"<!--@HEADER (.*?)@-->")


def house_css():
    """The family sheet followed by the notebook's shared rules."""
    return _FAMILY_SHEET.read_text(encoding="utf-8") + CHROME_CSS


def render_header(subtitle):
    """The top bar: the mark on the home colour, the notebook's name, and the page's."""
    return (
        '<div class="header">\n'
        f'        <span class="mark">{_MARK}</span>\n'
        '        <h1>Electronic Lab Notebook</h1>\n'
        f'        <p>{subtitle}</p>\n'
        '    </div>'
    )


def bake(html, *, template=False):
    """Replace the chrome markers in *html*. A page with no markers comes back unchanged, so
    this is safe to call on a page that is already baked.

    Pass ``template=True`` for a ``str.format`` template: the CSS is brace-escaped so the
    template still formats, and a ``{placeholder}`` in the header text survives for it."""
    css = house_css()
    if template:
        css = css.replace("{", "{{").replace("}", "}}")
    html = html.replace(_CSS_MARK, css)
    return _HEADER_MARK.sub(lambda m: render_header(m.group(1)), html)
