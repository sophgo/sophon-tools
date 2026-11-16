"""The C++ tokenizer must keep matching the Python reference exactly.

tests/tokenizer_golden.json is what the Python `tokenizers` package produced
(tools/gen_tokenizer_golden.py); native/src/tokenizer.cpp is what the board now
runs. This test builds the C++ conformance checker and replays the golden file,
so drift shows up here rather than as wrong tokens on the device.

It needs a C++ compiler and the model's tokenizer.json; both are optional, so the
test skips (rather than fails) where they are missing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "tokenizer_golden.json"

# The golden file records which tokenizer.json it came from; test against the
# same one when it is on this machine, else against any the environment names.
DEFAULT_TOKENIZER_JSON = Path(
    "/home/zzt/workspace/cv84x6-refs/models/Qwen3_5/config/tokenizer.json"
)


def _tokenizer_json() -> Path | None:
    explicit = os.environ.get("CV84X6_TOKENIZER_JSON")
    if explicit:
        return Path(explicit) if Path(explicit).exists() else None
    if DEFAULT_TOKENIZER_JSON.exists():
        return DEFAULT_TOKENIZER_JSON
    return None


@pytest.fixture(scope="module")
def checker(tmp_path_factory) -> Path:
    cxx = shutil.which("g++") or shutil.which("c++") or shutil.which("clang++")
    if cxx is None:
        pytest.skip("no C++ compiler to build the tokenizer checker")
    out = tmp_path_factory.mktemp("tokcheck") / "tok_check"
    srcs = [str(ROOT / "tools" / "tok_check.cpp"), str(ROOT / "native" / "src" / "tokenizer.cpp")]
    proc = subprocess.run(
        [cxx, "-std=c++17", "-O1", f"-I{ROOT / 'native' / 'include'}", *srcs, "-o", str(out)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        pytest.fail(f"tokenizer checker failed to build:\n{proc.stderr}")
    return out


def test_tokenizer_matches_reference_golden(checker: Path):
    tok = _tokenizer_json()
    if tok is None:
        pytest.skip("no tokenizer.json available (set CV84X6_TOKENIZER_JSON)")
    assert GOLDEN.exists(), "tests/tokenizer_golden.json is missing"
    proc = subprocess.run([str(checker), str(tok), str(GOLDEN)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, (
        "the C++ tokenizer no longer matches the reference implementation:\n"
        f"{proc.stdout}\n{proc.stderr}"
    )


def test_golden_file_covers_every_regex_branch():
    """Guard the goldens themselves: a shrinking corpus would hide drift."""
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases = data["cases"]
    assert data["tokenizers_version"], "golden file must record its source version"
    texts = [c["text"] for c in cases]
    # Contractions, spaces, newlines, punctuation, numbers, CJK, marks, added
    # tokens, and the byte-level alphabet each have to appear.
    assert any("'" in t for t in texts), "no contraction cases"
    assert any("\n" in t for t in texts), "no newline cases"
    assert any(t.startswith(" ") for t in texts), "no leading-space cases"
    assert any(t.endswith(" ") for t in texts), "no trailing-space cases"
    assert any(any("一" <= ch <= "鿿" for ch in t) for t in texts), "no CJK cases"
    assert any("́" in t or "̈" in t for t in texts), "no combining-mark cases"
    assert any("<|im_start|>" in t for t in texts), "no added-token cases"
    assert any(ch.isdigit() for t in texts for ch in t), "no digit cases"
    assert len(cases) >= 60, f"golden corpus shrank to {len(cases)} cases"
