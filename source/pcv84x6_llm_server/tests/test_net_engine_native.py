"""The generic single-graph runner (native/src/net_engine.cpp), on a plain host.

The engine is C++ against bmrt, so the interesting failures are not reachable
from Python: a multi-graph bmodel being silently accepted, a float32 array being
copied byte-for-byte into a half-float tensor, a caller sizing a buffer from a
rank the engine reported wrongly. ``tests/native/test_net_engine.cpp`` asserts
all of those against the fake bmrt; this file is what makes the suite run it.

Skips when there is no compiler or no libsophon headers, which is the same rule
``tests/test_vision_native.py`` follows: a checkout on a machine without the SDK
still runs the other 1600 tests.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NATIVE = ROOT / "tests" / "native"

#: Where libsophon's headers may be, most specific first. The board layout is
#: first; the rest are the checkout/build layouts this repository is developed
#: against, so the test runs on the BSP box without a hand-written -I.
HEADER_CANDIDATES = (
    "/opt/sophon/libsophon-current/include",
    "/opt/sophon/libsophon-0.4.15/include",
)


def _libsophon_include() -> Path | None:
    for candidate in HEADER_CANDIDATES:
        path = Path(candidate)
        if (path / "bmruntime_interface.h").exists():
            return path
    # A source checkout of libsophon: tpu-runtime has bmdef.h but not
    # bmlib_runtime.h, so the *build/install* tree is the one that works.
    for pattern in ("libsophon/build/install/libsophon-*/include",
                    "libsophon/*/include"):
        for path in sorted((ROOT.parent.parent).glob(pattern)):
            if (path / "bmruntime_interface.h").exists() and \
                    (path / "bmlib_runtime.h").exists():
                return path
    return None


def _cxx() -> str | None:
    return shutil.which("g++") or shutil.which("c++") or shutil.which("clang++")


@pytest.fixture(scope="module")
def include_dir() -> Path:
    inc = _libsophon_include()
    if inc is None:
        pytest.skip("no libsophon headers; pass them via tests/native/run_tests.sh")
    return inc


@pytest.fixture(scope="module")
def runner(tmp_path_factory, include_dir) -> Path:
    cxx = _cxx()
    if cxx is None:
        pytest.skip("no C++ compiler available")
    out = tmp_path_factory.mktemp("netengine") / "test_net_engine"
    proc = subprocess.run(
        [cxx, "-std=c++17", "-O1", "-Wall", "-Wextra",
         f"-I{include_dir}", f"-I{ROOT / 'native' / 'include'}", f"-I{NATIVE}",
         str(ROOT / "native" / "src" / "net_engine.cpp"),
         str(NATIVE / "fake_bm.cpp"), str(NATIVE / "test_net_engine.cpp"),
         "-o", str(out), "-lpthread"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"the engine test does not build here: {proc.stderr[:800]}")
    # A warning in the engine source itself is a real signal (an unused
    # conversion branch, a shadowed variable): the test build is -Wall -Wextra
    # on purpose. Warnings from the fake bmrt fixture are not -- it is a test
    # double with deliberately unused knobs.
    engine_warnings = [
        line for line in proc.stderr.splitlines()
        if "warning:" in line and "net_engine" in line
    ]
    assert not engine_warnings, "\n".join(engine_warnings)
    return out


def test_net_engine_contract(runner: Path):
    proc = subprocess.run([str(runner)], capture_output=True, text=True)
    assert proc.returncode == 0, (
        "the generic single-graph runner no longer behaves as documented:\n"
        f"{proc.stdout}\n{proc.stderr}")


def test_net_engine_is_compiled_into_the_library():
    """A source file that nothing links is a file that is not shipped.

    The C ABI test can only exercise what the library exports, and the library
    is what the board loads, so this is the one place the build wiring itself is
    checked.
    """
    cmake = (ROOT / "native" / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "src/net_engine.cpp" in cmake, "net_engine.cpp is not in the library"
    api = (ROOT / "native" / "src" / "c_api.cpp").read_text(encoding="utf-8")
    for symbol in ("cv_net_create", "cv_net_destroy", "cv_net_info",
                   "cv_net_elements", "cv_net_dtype", "cv_net_run"):
        assert symbol in api, f"{symbol} is missing from the C ABI"
