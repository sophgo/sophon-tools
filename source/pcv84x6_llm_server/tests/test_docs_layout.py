"""The documentation set: every relative link resolves, and nothing rots silently.

Two failure modes this guards against, both of which happened while the docs were
being reorganised:

* a document moves (``docs/decode-optimization.md`` -> ``docs/research/``) and the
  links *into* it, or the ones *inside* it, keep pointing at the old depth;
* a link is written from the repository root's point of view inside a file that
  lives two directories down, so it renders on GitHub but not in the checkout.

The check is deliberately text-only and structure-agnostic: it does not care
which documents exist, only that a link that looks relative points at a path
that is actually there. Anchor-only (``#section``) and external links are out of
scope -- there is no way to verify a URL offline.

Why this is a test rather than a script: the docs carry the evidence behind
production decisions (``docs/research/``), so a dead pointer there costs more
than a broken README link. It has to run on every change, not when someone
remembers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# ``[text](target)``; the text may contain nested brackets from `code` spans.
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

# Schemes that are not filesystem paths.
EXTERNAL = ("http://", "https://", "mailto:", "mention://", "#")


def _markdown_files() -> list[Path]:
    files = []
    for path in sorted(ROOT.rglob("*.md")):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in (".git", "node_modules") or "node_modules" in rel.parts:
            continue
        files.append(path)
    return files


def _relative_links(path: Path) -> list[tuple[int, str]]:
    """(line number, target) for every link that should resolve in the tree."""
    out = []
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        for match in LINK.finditer(line):
            target = match.group(1).strip()
            if target.startswith(EXTERNAL) or not target:
                continue
            out.append((lineno, target))
    return out


def test_every_markdown_file_is_reachable_from_the_docs_index():
    """A document nobody links to is a document nobody maintains.

    The root README and the two indexes are the entry points; every other
    document has to be reachable from one of them. This is what keeps
    ``docs/research/`` from becoming a graveyard.
    """
    entries = {"README.md", "docs/README.md", "docs/research/README.md"}
    seen: set[str] = set()
    queue = [ROOT / name for name in entries]
    while queue:
        current = queue.pop()
        rel = str(current.relative_to(ROOT))
        if rel in seen or not current.is_file():
            continue
        seen.add(rel)
        for _, target in _relative_links(current):
            resolved = (current.parent / target.split("#")[0]).resolve()
            if resolved.is_file() and resolved.suffix == ".md":
                queue.append(resolved)

    documented = {p for p in _markdown_files() if p.relative_to(ROOT).parts[0] in ("docs",)}
    documented |= {ROOT / "README.md", ROOT / "CONTRIBUTING.md"}
    orphans = {
        str(p.relative_to(ROOT))
        for p in documented
        if str(p.relative_to(ROOT)) not in seen
    }
    assert not orphans, (
        "these documents are not reachable from README.md / docs/README.md: "
        + ", ".join(sorted(orphans))
    )


@pytest.mark.parametrize("path", _markdown_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(path: Path):
    missing = []
    for lineno, target in _relative_links(path):
        resolved = (path.parent / target.split("#")[0]).resolve()
        if not resolved.exists():
            missing.append(f"{path.relative_to(ROOT)}:{lineno} -> {target}")
    assert not missing, "broken relative links:\n" + "\n".join(missing)


def test_the_packaging_scripts_reference_files_that_exist():
    """`package.sh` copies payload by literal path; a rename must break here.

    The deb reuses that tree, so a stale path in `package.sh` silently drops a
    file from both release formats. Reading the script is the only way to catch
    it without building a package (which needs the board's engine library).
    """
    src = (ROOT / "scripts" / "package.sh").read_text(encoding="utf-8")
    # ``cp -a deploy README.md "$D/"`` and the named tool copies.
    copied = re.findall(r"^cp -a ([\w./ -]+?)\s+\"\$D/?", src, flags=re.M)
    assert copied, "package.sh no longer copies a payload in the expected shape"
    for group in copied:
        for name in group.split():
            assert (ROOT / name).exists(), f"package.sh copies a missing path: {name}"


def test_the_design_document_still_ships_in_the_deb():
    """The operator-facing docs ride along in /usr/share/doc.

    DESIGN.md moved content around during the reorganisation; the packaging only
    guards it with ``if [ -f ... ]``, so a move would drop it from the package
    without any failure. It is the document an operator reads when deciding
    whether to move the data directory, so it has to be there.
    """
    src = (ROOT / "scripts" / "package_deb.sh").read_text(encoding="utf-8")
    assert "docs/DESIGN.md" in src
    assert (ROOT / "docs" / "DESIGN.md").is_file()
    assert "README.md" in src
    assert (ROOT / "README.md").is_file()
