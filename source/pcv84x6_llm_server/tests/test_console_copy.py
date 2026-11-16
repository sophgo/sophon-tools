"""The console's own copy: no fixed board capacity, no absolute fit verdict.

The user reported the Docs page saying "the board has 2.6 GB, so OpenClaw
cannot run beside a 35B model" -- a statement about a specific board presented
as a fact about the product. It was wrong on that board (``free -m`` reports
2133 MiB there after the NPU/CMA reservations, not 2.6 GB) and it would be wrong
on a bigger one, while the service already answers the fit question at start
time from the live ``MemAvailable``.

These read the TSX sources as text. That is deliberate: the defect is the
wording itself, so the cheapest honest check is to look for the wording. The
real-browser check that the page renders without these claims is
``tools/probe_console_docs.py`` against the built console.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB_SRC = Path(__file__).resolve().parent.parent / "web" / "src"

# Claims that assert a property of the hardware rather than of the software.
# Each one was in the page before MYS-2424 and is not something a page can know:
# board RAM differs per SKU, and "cannot run beside X" is a runtime decision.
CAPACITY_CLAIMS = (
    "2.6 GB",
    "2.6GB",
    "板卡只有",
    "板卡共",
    "不能与",
    "无法同时运行",
)

# The second half of the same defect: the agent chapter used to justify the
# memory floor with an absolute verdict of its own -- "it will not come up and
# then be OOM-killed -- killing the inference process may hang the NPU" -- and a
# "can it run beside the loaded model" paragraph. Both are predictions the page
# cannot make (the kernel's choice of victim, whether a driver hangs) and the
# operator asked for the estimate and nothing more. The floor itself is
# untouched: ``_check_memory`` still refuses a start below it.
ABSOLUTE_VERDICT_CLAIMS = (
    "OOM",
    "共存",
    "卡死",
    "固定容量",
    "写死容量",
)

TSX_FILES = sorted(WEB_SRC.rglob("*.tsx"))


def _uncommented(path: Path) -> str:
    """Source with // and /* */ comments removed.

    A comment explaining why a threshold exists is fine; the user sees the
    rendered text, so only what can reach the page is checked.
    """
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    return text


def _docs_agent_chapter() -> str:
    """The agent chapter of the Docs page, comments removed.

    Scoped rather than page-wide: ``OOM`` and ``卡死`` are legitimate elsewhere
    -- the "NPU 故障" note under 故障与限制 really is about the driver hanging,
    and the memory-floor comment in the manager really is about the kernel -- so
    a page-wide ban would delete true documentation. What the operator objected
    to is the *agent memory* paragraph making those predictions.
    """
    source = _uncommented(WEB_SRC / "pages" / "Docs.tsx")
    start = source.find('<h2 id="agents"')
    assert start >= 0, "the docs page no longer has an agent chapter"
    end = source.find('<h2 id="', start + 1)
    return source[start:] if end < 0 else source[start:end]


@pytest.mark.parametrize("agent_id", ["picoclaw", "opencode", "openclaw"])
def test_agent_cards_show_only_a_memory_estimate(agent_id):
    """The card's visible text is the note the API returns and nothing more.

    The note is rendered verbatim (``{a.card_note}`` in Agents.tsx), so checking
    the API's value here is checking what the operator reads. The rule itself is
    in ``tests/test_agents.py::test_agent_card_copy_is_a_memory_estimate_and_nothing_else``;
    this asserts the page actually renders it.
    """
    agents_tsx = (WEB_SRC / "pages" / "Agents.tsx").read_text(encoding="utf-8")
    assert "{a.card_note}" in agents_tsx, "the card no longer renders the API note"
    # No second, hardcoded memory line next to it.
    assert "实测运行内存" not in agents_tsx


def test_docs_page_states_no_fixed_board_capacity():
    """No page may assert how much RAM the board has."""
    offenders = []
    for path in TSX_FILES:
        source = _uncommented(path)
        for claim in CAPACITY_CLAIMS:
            if claim in source:
                line = next(
                    (i for i, t in enumerate(source.splitlines(), 1) if claim in t), 0
                )
                offenders.append(f"{path.relative_to(WEB_SRC)}:{line} claims {claim!r}")
    assert not offenders, "fixed-capacity wording is back:\n" + "\n".join(offenders)


def test_docs_page_explains_how_memory_is_actually_checked():
    """Removing the false claim must leave the true explanation in its place.

    A page that simply deleted the paragraph would leave an operator with no
    answer to "will this fit?". The replacement has to say where the real number
    comes from and that the service enforces it.
    """
    docs = _uncommented(WEB_SRC / "pages" / "Docs.tsx")
    assert "MemAvailable" in docs, "the docs no longer name the real memory reading"
    assert "总览" in docs, "the docs no longer point at the live memory readout"
    assert "预估内存" in docs, "the docs no longer explain the card's estimate"
    assert "拒绝" in docs, "the docs no longer say the service refuses a start"


def test_agent_chapter_makes_no_absolute_verdict():
    """The agent chapter states the estimate, not what the kernel will do.

    Regression guard for the wording the operator rejected: "it will not come up
    and then be OOM-killed -- killing the inference process may hang the NPU"
    and the "can it run beside the loaded model" paragraph. Neither is something
    a page can know, and both read as a fixed capacity even after the numbers
    were parameterised. The real enforcement (``_check_memory`` against live
    ``MemAvailable``) is unchanged and is asserted by
    ``tests/test_agents.py::test_memory_check_keeps_the_per_agent_floor``.
    """
    chapter = _docs_agent_chapter()
    offenders = [c for c in ABSOLUTE_VERDICT_CLAIMS if c in chapter]
    assert not offenders, (
        "the agent chapter is back to predicting the kernel's behaviour: "
        f"{offenders} in\n{chapter}"
    )


def test_agent_chapter_still_says_what_the_operator_can_act_on():
    """The three facts MYS-2424 asked to keep, all in the agent chapter.

    Deleting the rejected sentences is only half the change: an operator still
    has to learn where the estimate is, that a start is checked against live
    memory, and where the real usage shows up. Asserted on the same scoped text
    so the words existing elsewhere on the page cannot satisfy it.
    """
    chapter = _docs_agent_chapter()
    assert "预估内存" in chapter, "the chapter no longer explains the card's estimate"
    assert "MemAvailable" in chapter, "the chapter no longer names the live reading"
    assert "拒绝启动" in chapter, "the chapter no longer says a start can be refused"
    assert "总览" in chapter, "the chapter no longer points at the usage readout"


# -- the shipped artefact --------------------------------------------------
#
# Reading the source proves what the next build will contain; the operator saw
# the *committed* bundle, so the wording the task rejects is also checked where
# it actually reached them. A stale dist is the same defect one step later: the
# page renders the old sentences while the source looks fixed.

DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


def _dist_bundles() -> list[Path]:
    return sorted((DIST / "assets").glob("index-*.js"))


def test_the_committed_bundle_carries_no_oom_or_coexistence_copy():
    """The built console the operator loads must not contain the old wording."""
    bundles = _dist_bundles()
    if not bundles:
        pytest.skip("web/dist is not built in this checkout")
    offenders = []
    for path in bundles:
        text = path.read_text(encoding="utf-8", errors="replace")
        for claim in ("内核 OOM", "被内核 OOM 杀掉", "能不能和已加载的模型共存"):
            if claim in text:
                offenders.append(f"{path.name} still ships {claim!r}")
    assert not offenders, "the shipped bundle is stale:\n" + "\n".join(offenders)


def test_the_committed_bundle_carries_the_replacement_copy():
    """...and it carries the three facts the corrected chapter states."""
    bundles = _dist_bundles()
    if not bundles:
        pytest.skip("web/dist is not built in this checkout")
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in bundles)
    assert "预估内存" in text, "the bundle no longer explains the card's estimate"
    assert "MemAvailable" in text, "the bundle no longer names the live memory reading"
    assert "总览" in text, "the bundle no longer points at the usage readout"

