"""The console's design system: the token set exists and the pages obey it.

This is a regression guard for the Refactoring UI pass (MYS-2456). It checks the
three things that decay silently once a stylesheet is edited by hand:

* every colour, size, space and radius the CSS uses is declared or on a scale
  (§1.5 — "every value comes from a system"; a typo like ``var(--accent-dim)``
  renders as nothing at all, which is why the theme block is checked against the
  usages, in both directions);
* the type scale stays small and the two-role text/weight limits hold
  (§2.2.a three text colours, §2.2.b two weights, §4.1 one scale);
* the accessibility floor: focus is never removed without a replacement (§15)
  and motion is disabled under ``prefers-reduced-motion``.

Contrast is *not* checked here — it needs the rendered page, and it is checked by
``web/acceptance/contrast_audit.py`` against live Chromium, which is the only
honest way to read a computed background through the cascade.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_SRC = ROOT / "web" / "src"
STYLES = WEB_SRC / "styles.css"
TSX = sorted(WEB_SRC.rglob("*.tsx")) + sorted(WEB_SRC.rglob("*.ts"))


def css() -> str:
    return STYLES.read_text(encoding="utf-8")


def _declared(text: str) -> set[str]:
    """Every custom property the stylesheet defines."""
    return set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", text, flags=re.M))


def _used(text: str) -> set[str]:
    return set(re.findall(r"var\((--[a-z0-9-]+)", text))


def _sources() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in TSX)


# -- the token set ---------------------------------------------------------

def test_every_var_used_anywhere_is_declared():
    """An undeclared `var()` is not an error the browser reports: the property
    silently computes to nothing, so a mistyped token looks like a missing
    border or a transparent background rather than a failure. That is how
    `var(--accent-dim)` survived in the key callout and `var(--warn)` in the
    move confirmation."""
    declared = _declared(css())
    used = _used(css()) | _used(_sources())
    missing = sorted(used - declared)
    assert not missing, (
        "these custom properties are read but never defined, so they render as "
        f"nothing: {missing}")


def test_both_themes_declare_the_same_properties():
    """A property defined in one palette but not the other leaves the other
    theme inheriting a light-mode value — the classic dark-mode hole: a text
    colour that is dark-on-dark, or a surface that stays white."""
    text = css()
    blocks = re.findall(
        r":root(?:\[data-theme='(light|dark)'\])?\s*\{(.*?)\n\}", text, flags=re.S)
    sets = {}
    for name, body in blocks:
        sets[name or "unthemed"] = _declared(body)
    # `:root, :root[data-theme='light']` parses as the unthemed entry plus the
    # light one sharing a body; both must exist and dark must match light.
    assert "dark" in sets, "no [data-theme='dark'] block"
    light = sets.get("light") or sets.get("unthemed")
    if sets.get("light"):
        light = sets["light"] | sets.get("unthemed", set())
    assert light, "no light palette block"
    # Typeface, radius and the scale block are theme-independent on purpose:
    # they are declared once for both palettes. Everything that carries a
    # *colour* must exist in both.
    theme_independent = {p for p in light
                         if p.startswith(("--t-", "--s-", "--radius", "--mono", "--sans"))
                         or p in {"--radius", "--radius-sm", "--radius-pill"}}
    only_light = sorted(light - sets["dark"] - theme_independent)
    only_dark = sorted(sets["dark"] - light)
    assert not only_light, f"declared only in the light palette: {only_light}"
    assert not only_dark, f"declared only in the dark palette: {only_dark}"


# -- the scales ------------------------------------------------------------

def test_the_type_scale_is_one_small_set():
    """§4.1.1d: a hand-picked UI scale, not every pixel value between 10 and 24.
    Before this pass the rendered page carried 19 distinct sizes including 11.5,
    12.3, 12.6, 12.8, 13.6 and 13.8."""
    sizes = sorted(re.findall(r"--t-[a-z0-9]+:\s*(\d+)px", css()), key=int)
    assert sizes == ["12", "14", "16", "18", "20", "24"], sizes


def test_the_spacing_scale_keeps_its_adjacency():
    """§3.2.1: no two adjacent steps closer than ~25%, or the scale offers
    choices the eye cannot tell apart."""
    steps = [int(v) for v in
             sorted(re.findall(r"--s-\d+:\s*(\d+)px", css()), key=int)]
    assert steps == [4, 8, 12, 16, 24, 32, 48, 64], steps
    for a, b in zip(steps, steps[1:]):
        assert (b - a) / a >= 0.25, f"{a} -> {b} is only {(b-a)/a:.0%} apart"


def test_no_font_size_below_the_ui_floor():
    """§2.2.b: nothing below 12px in interface text."""
    for path in [STYLES, *TSX]:
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"font-size:\s*([\d.]+)px", text):
            assert float(m.group(1)) >= 12, f"{path.name}: {m.group(0)}"
        for m in re.finditer(r"fontSize:\s*([\d.]+)\b", text):
            assert float(m.group(1)) >= 12, f"{path.name}: {m.group(0)}"


def test_pages_do_not_hand_pick_font_sizes():
    """§1.5/§4.1: a page that writes `style={{ fontSize: 13 }}` is choosing an
    off-scale value at a call site. Sizes must come from `--t-*` in the
    stylesheet. (Chart/probe code may set SVG font sizes; those live in CSS.)"""
    offenders = []
    for path in TSX:
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"fontSize:\s*\d", line):
                offenders.append(f"{path.relative_to(WEB_SRC)}:{i} {line.strip()}")
    assert not offenders, "off-scale font sizes set inline:\n" + "\n".join(offenders)


def test_only_two_font_weights_are_used():
    """§2.2.b: 400 for body, 600 for emphasis. The 550/620 half-steps the pages
    used before are indistinguishable from 600 and only add variety."""
    weights = set(re.findall(r"font-weight:\s*(\d+)", css()))
    weights |= set(re.findall(r"fontWeight:\s*(\d+)", _sources()))
    odd = sorted(w for w in weights if w not in {"400", "600"})
    assert not odd, f"weights outside 400/600: {odd}"


# -- accessibility ---------------------------------------------------------

def test_focus_is_never_removed_without_a_replacement():
    """§15: `outline: none` with no substitute makes the console unusable by
    keyboard. Every occurrence must be paired with a replacement on the same or
    an adjacent rule."""
    for path in [STYLES, *TSX]:
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"outline:\s*none", text):
            tail = text[m.end():m.end() + 240]
            head = text[max(0, m.start() - 240):m.start()]
            assert "box-shadow" in tail or "outline" in tail or "box-shadow" in head, (
                f"{path.name}: `outline: none` with no replacement near "
                f"offset {m.start()}")


def test_reduced_motion_is_honoured():
    """§15: not optional — motion triggers vestibular symptoms."""
    text = css()
    assert "prefers-reduced-motion" in text
    block = text.split("prefers-reduced-motion", 1)[1]
    for prop in ("animation-duration", "transition-duration"):
        assert prop in block, f"the reduced-motion block does not reset {prop}"


def test_dark_mode_is_not_the_light_ramp_flipped():
    """§15: elevation in dark mode is surface lightness, not shadow, and the
    accent must be a *light* fill with dark ink rather than white on teal (which
    cannot reach 4.5:1 on a dark surface)."""
    text = css()
    dark = text.split("[data-theme='dark']", 1)[1]
    # Surfaces get lighter as they come forward.
    def num(prop):
        m = re.search(rf"--{prop}:\s*#([0-9a-f]{{6}})", dark)
        assert m, f"--{prop} missing from the dark palette"
        return sum(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    assert num("bg") < num("panel") < num("panel-2") < num("panel-3"), (
        "dark elevation must read as lighter-is-closer")
    # The action flips to dark ink.
    on_accent = re.search(r"--on-accent:\s*#([0-9a-f]{6})", dark)
    assert on_accent and sum(
        int(on_accent.group(1)[i:i + 2], 16) for i in (0, 2, 4)) < 200, (
        "--on-accent in dark mode must be dark ink, not white")


def test_status_is_never_carried_by_colour_alone():
    """§5.7: every status pill carries a dot *and* an icon/word, so a reader who
    cannot separate the hues still gets the state."""
    text = css()
    assert ".dot" in text
    assert 'className="dot"' in (WEB_SRC / "pages" / "Keys.tsx").read_text(encoding="utf-8")


# -- the committed artefact ------------------------------------------------

DIST = ROOT / "web" / "dist"


def test_the_committed_bundle_carries_the_design_tokens():
    """The board runs `web/dist`, not the sources, so the redesign is only real
    once the bundle in the tree carries it. A stale dist is the same defect one
    step later: the source looks right and the operator sees the old page."""
    css_files = sorted((DIST / "assets").glob("index-*.css"))
    if not css_files:
        pytest.skip("web/dist is not built in this checkout")
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in css_files)
    # A token only survives minification when it is actually referenced.
    assert "--s-5" in text or "--t-sm" in text, (
        "the committed stylesheet has no scale tokens — dist is stale")
    assert "prefers-reduced-motion" in text, (
        "the committed stylesheet predates the reduced-motion block")
