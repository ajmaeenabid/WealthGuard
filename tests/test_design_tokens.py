"""The design tokens: every component colour comes from tokens.css, and the important text/background pairs meet WCAG AA."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
CSS = (STATIC / "tokens.css").read_text(encoding="utf-8")


def lum(h):
    h = h.lstrip("#")
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a, b):
    la, lb = sorted([lum(a), lum(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def block(selector):
    i = CSS.index(selector)
    return CSS[i:CSS.index("}", i)]


def token(blk, name):
    m = re.search(rf"--{name}:\s*(var\(--([\w-]+)\)|#[0-9A-Fa-f]{{6}})", blk)
    assert m, name
    if m.group(2):
        return token(CSS, m.group(2))
    return m.group(1)


LIGHT, DARK = block(":root, :root[data-theme=\"light\"]"), block(":root[data-theme=\"dark\"] {")


def test_reference_palette_values_are_present():
    for hexv in ("#F2EEDB", "#E4CFB5", "#FAF7ED", "#81A482", "#6D795F", "#815B3D", "#29251F", "#D5C4AA"):
        assert hexv in CSS


def test_light_theme_pairs_meet_aa():
    pairs = [("color-text-primary", "color-bg-primary"), ("color-text-primary", "color-bg-surface"), ("color-text-primary", "color-bg-secondary"),
             ("color-text-secondary", "color-bg-primary"), ("color-text-secondary", "color-bg-secondary"), ("color-text-muted", "color-bg-surface"),
             ("color-on-action", "color-action"), ("color-action", "color-bg-primary"), ("color-success", "color-bg-primary"),
             ("color-warning", "color-bg-primary"), ("color-danger", "color-bg-primary"), ("color-info", "color-bg-primary")]
    for fg, bg in pairs:
        assert ratio(token(LIGHT, fg), token(LIGHT, bg)) >= 4.5, (fg, bg)


def test_dark_theme_pairs_meet_aa():
    pairs = [("color-text-primary", "color-bg-primary"), ("color-text-secondary", "color-bg-surface"), ("color-text-muted", "color-bg-surface"),
             ("color-on-action", "color-action"), ("color-action", "color-bg-primary"), ("color-success", "color-bg-primary"),
             ("color-warning", "color-bg-primary"), ("color-danger", "color-bg-primary"), ("color-info", "color-bg-primary")]
    for fg, bg in pairs:
        assert ratio(token(DARK, fg), token(DARK, bg)) >= 4.5, (fg, bg)


def test_dark_theme_follows_the_reference_layout_and_scopes_every_rule():
    dark = (STATIC / "theme-dark.css").read_text(encoding="utf-8")
    rules = [ln for ln in dark.splitlines() if ln.strip().startswith(":root") or ln.strip().startswith("@media") or ln.strip().startswith("/*") or not ln.strip() or ln.startswith(" ") or ln.startswith("}")]
    assert 'data-theme="dark"' in dark and ".sidebar" in dark and ".stage" in dark and "radial-gradient" in dark          # floating panels, green glow
    assert "#62E05A" in CSS and "--color-action: #62E05A" in CSS                                                          # the one lime accent
    for ln in dark.splitlines():
        if ln.startswith(".") or ln.startswith("body"):                                                                   # an unscoped selector would leak into the light theme
            raise AssertionError(ln)


def test_theme_layer_uses_tokens_not_raw_colours():
    theme = (STATIC / "theme.css").read_text(encoding="utf-8")
    raw = re.findall(r"#[0-9A-Fa-f]{3,6}\b|rgba?\(", theme)
    assert len(raw) <= 8, raw              # a handful of deliberate exceptions (white on destructive hover, hero shadow)
    assert 'href="/static/tokens.css"' in (STATIC / "index.html").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index("tokens.css") < html.index("theme.css") < html.index("theme-dark.css") and "Playfair" in html and "Inter" in html
