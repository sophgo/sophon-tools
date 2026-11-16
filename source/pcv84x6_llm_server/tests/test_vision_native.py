"""The C++ vision pipeline must reproduce the reference preprocessing exactly.

Image preprocessing is pure host software -- decode, smart_resize, Pillow's
bicubic resize, normalise, patchify -- so this is checked with a plain C++
binary on any machine: no board, no NPU. That is the point of porting it: the
values the NPU receives can be compared against the reference stack's output
without hardware.

tests/vision_golden.json holds the reference values (tools/gen_vision_golden.py
regenerates them from transformers' own _preprocess and Pillow). The comparison
is bitwise, because the pipeline is deterministic: "close" would hide exactly
the kind of silent drift that would make the model answer differently.
"""

from __future__ import annotations

import json
import gzip
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "vision_golden.json"
FIXTURES = ROOT / "tests" / "vision_fixtures"


def _cxx() -> str:
    cxx = shutil.which("g++") or shutil.which("c++") or shutil.which("clang++")
    if cxx is None:
        pytest.skip("no C++ compiler to build the vision checker")
    return cxx


@pytest.fixture(scope="module")
def checker(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("visioncheck") / "vision_check"
    srcs = [str(ROOT / "tools" / "vision_check.cpp"),
            str(ROOT / "native" / "src" / "vision.cpp")]
    proc = subprocess.run(
        [_cxx(), "-std=c++17", "-O1", f"-I{ROOT / 'native' / 'include'}",
         *srcs, "-o", str(out), "-ljpeg", "-lz"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"vision checker does not build here: {proc.stderr[:400]}")
    return out


def test_pipeline_matches_reference_bitwise(checker: Path):
    if not GOLDEN.exists():
        pytest.skip("tests/vision_golden.json is missing")
    proc = subprocess.run([str(checker), str(GOLDEN), str(FIXTURES)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, (
        "the C++ vision pipeline no longer matches the reference stack:\n"
        f"{proc.stdout}\n{proc.stderr}")


def test_golden_covers_the_awkward_inputs():
    """A shrunken fixture set would quietly stop testing the hard paths."""
    if not GOLDEN.exists():
        pytest.skip("tests/vision_golden.json is missing")
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    names = {c["name"] for c in data["cases"]}
    for required in ("gradient.png", "noise.png", "photo.jpg", "palette.png",
                     "rgba.png", "wide.png", "tiny.png", "gray.png"):
        assert required in names, f"golden lost the {required} case"
    # Every case must have the temporal patch group folded in (tc = 2), i.e. a
    # patch vector of C*tc*patch^2 = 1536, not 768.
    for c in data["cases"]:
        assert c["shape"][-1] == 1536, f"{c['name']}: patch vector {c['shape'][-1]}"
    assert len(data["resize_cases"]) >= 6


def test_vl_embedding_matches_official_torchvision_processor(checker, tmp_path):
    """A different floating-point operation order changes the low bits.

    Recorded with the pinned embedding config and Transformers 5.6.2; the
    legacy chat preprocessing golden above must continue to pass as well.
    """
    golden = tmp_path / "vl_golden.json"
    with gzip.open(ROOT / "tests" / "vision_vl_golden.json.gz", "rb") as stream:
        golden.write_bytes(stream.read())
    result = subprocess.run([str(checker), str(golden), str(FIXTURES)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_wemm_matches_official_image_entry_including_rgba(checker, tmp_path):
    """WeMM passes the original image to qwen-vl-utils, which composites RGBA.

    The pinned Transformers 5.2.0 golden covers all eight existing fixtures;
    the other tests keep the legacy RGB conversion contract independently.
    """
    golden = tmp_path / "wemm_golden.json"
    with gzip.open(ROOT / "tests" / "vision_wemm_golden.json.gz", "rb") as stream:
        golden.write_bytes(stream.read())
    result = subprocess.run([str(checker), str(golden), str(FIXTURES)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
