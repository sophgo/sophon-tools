"""The checked-in test fixtures are present, unchanged, and actually used.

The service's test suite depends on fixed fixtures under ``tests/data/``. The
repository's root ``.gitignore`` used to swallow that directory (its ``data/``
rule), so a clean checkout ran the suite with 96 ``FileNotFoundError`` failures
-- and worse, a handful of tests *skipped* themselves when a golden was missing,
which reads as "passed" in a summary line.

These tests keep the fixtures honest rather than merely present:

* the set matches ``PROVENANCE.md`` byte for byte (missing, changed or
  unlisted files all fail);
* the directory is actually trackable, i.e. the ``.gitignore`` exception that
  lets it be committed is still in force -- otherwise the files could be
  present locally and absent from the next clean checkout;
* a missing golden makes its dependent test fail, not skip.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent          # source/pcv84x6_llm_server
DATA = SRC / "tests" / "data"
REPO = SRC.parent.parent                              # sophon-tools root
VERIFY = DATA / "verify_fixtures.py"

# Every fixture the suite reads. Named explicitly so a rename shows up here as
# a failure rather than as a silently smaller fixture set.
REQUIRED = (
    "qwen3_6_chat_template.jinja",
    "bm_smi_noloop_cv84x6_idle.txt",
    "aux_token_golden.json",
    "asr/features.npz",
    "asr/meta.json",
    "asr/prompts.json",
    "kb/text.pdf",
    "kb/scan.pdf",
    "kb/mixed.pdf",
    "kb/blank.pdf",
    "ocr/golden.json",
    "ocr/slanet_inference.yml",
    "ocr/postprocess.npz",
    "ocr/layout_tensors.npz",
    "ocr/otsl_golden.json",
    "ocr/table_truth.json",
    "ocr/twocolumn_truth.json",
    "ocr/tokenizer_golden_paddleocr_vl.json",
)


def test_every_required_fixture_is_present():
    missing = [name for name in REQUIRED if not (DATA / name).is_file()]
    assert not missing, f"missing test fixtures: {missing}"


def test_the_fixture_set_matches_its_recorded_digests():
    """PROVENANCE.md is the manifest; the files must equal it.

    Runs the same checker as CI so a fixture cannot be edited into agreeing
    with a changed test.
    """
    done = subprocess.run([sys.executable, str(VERIFY)], capture_output=True, text=True)
    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"


def test_an_unlisted_or_changed_fixture_is_reported(tmp_path):
    """The checker must fail on a changed file and on a stray file."""
    import hashlib
    import importlib.util

    spec = importlib.util.spec_from_file_location("verify_fixtures", VERIFY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Point the module at a throwaway tree with one good file and one stray.
    original_here, original_prov = module.HERE, module.PROVENANCE
    try:
        good = tmp_path / "good.bin"
        good.write_bytes(b"payload")
        digest = hashlib.sha256(b"payload").hexdigest()
        (tmp_path / "PROVENANCE.md").write_text(
            f"| `good.bin` | 7 | `{digest}` |\n")
        module.HERE, module.PROVENANCE = tmp_path, tmp_path / "PROVENANCE.md"
        assert module.verify() == []

        (tmp_path / "stray.bin").write_bytes(b"x")
        problems = module.verify()
        assert any("unlisted: stray.bin" in p for p in problems)

        good.write_bytes(b"tampered")
        problems = module.verify()
        assert any("digest changed: good.bin" in p for p in problems)
    finally:
        module.HERE, module.PROVENANCE = original_here, original_prov


def test_the_fixture_directory_is_not_gitignored():
    """The directory must be committable, or a clean checkout loses it again.

    This is the regression for the reviewed defect: the files existed locally
    while ``.gitignore``'s ``data/`` rule kept them out of the repository, so
    "it passes on my machine" was true and "it passes from a clean checkout"
    was not.
    """
    probe = DATA / "qwen3_6_chat_template.jinja"
    if not (REPO / ".git").exists() and not (REPO / ".git").is_file():
        pytest.skip("not a git checkout")
    done = subprocess.run(["git", "check-ignore", "-v", str(probe)],
                          cwd=REPO, capture_output=True, text=True)
    # `git check-ignore` exits 0 when the path IS ignored. A negation rule that
    # re-includes the path still makes check-ignore exit 0, so read the rule:
    # the last matching pattern must be the negated one.
    if done.returncode == 0:
        rule = done.stdout.strip().split(":", 2)[-1].strip()
        assert rule.startswith("!"), (
            f"tests/data is ignored by {done.stdout.strip()!r}; a clean checkout "
            f"would not have the fixtures")
    else:
        assert done.returncode == 1, done.stderr


def test_the_ignore_exception_is_scoped_to_the_fixture_directory():
    """No global `data/` reopening: other `data/` paths must stay ignored."""
    if not (REPO / ".git").exists() and not (REPO / ".git").is_file():
        pytest.skip("not a git checkout")
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    # The only negations allowed to mention data are the two fixture ones.
    for line in ignore.splitlines():
        stripped = line.strip()
        if stripped.startswith("!") and "data" in stripped:
            assert stripped in (
                "!source/pcv84x6_llm_server/tests/data/",
                "!source/pcv84x6_llm_server/tests/data/**",
                "!source/psophliteos/frontend/src/**/data/",
                "!source/psophliteos/frontend/src/**/data/**",
            ), f"unexpected data exception in .gitignore: {stripped}"
    # And a representative non-fixture path must still be ignored.
    done = subprocess.run(["git", "check-ignore", "-q", "data/runtime-state.json"],
                          cwd=REPO)
    assert done.returncode == 0, "the global data/ rule was removed; that is not the fix"


def test_a_missing_golden_fails_instead_of_skipping():
    """A missing fixture must not turn into a skip.

    ``pytest.skip`` on a missing golden makes a summary line read "passed" while
    the assertion never ran. The tests that depend on these fixtures must fail
    loudly instead, which is what a clean checkout did after the ignore rule was
    fixed: they were errors, not skips, and that is the correct behaviour.
    """
    offenders = []
    for path in (SRC / "tests").glob("test_*.py"):
        if path.name == Path(__file__).name:
            continue  # this file names the pattern it forbids; it is not one
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if "pytest.skip" not in stripped and "pytestmark" not in stripped:
                continue
            # Only the fixture-missing skips are at issue; skips for an absent
            # optional toolchain (compiler, model config) are legitimate.
            lowered = stripped.lower()
            if "tests/data" in lowered or "golden" in lowered and "missing" in lowered:
                offenders.append(f"{path.name}: {stripped}")
    assert not offenders, (
        "a missing test fixture must fail, not skip:\n" + "\n".join(offenders))
