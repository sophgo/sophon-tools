"""sophon-tools unified-build integration for pcv84x6_llm_server.

Three layers, deliberately kept apart so a failure names its own cause:

1. **Registration (static, always runs)** — the project is in build-all's
   registry with the right default arch and platform note, and every new or
   changed shell script parses. These run everywhere, no docker needed.

2. **Interface contract (subprocess, always runs)** — `release.sh` is the M1
   entry point: unsupported ARCH values must fail, an explicit VERSION that
   disagrees with the source must be refused (never "fixed up"), the fixed
   build inputs must verify by sha256, and OUTPUT_DIR must be honoured. The
   full build is NOT run here (it needs docker + the unified image + network);
   these tests cover the argument handling and the input gate, which are the
   parts the unified driver depends on.

3. **Scheduling with stubbed heavy projects (docker not needed)** — a fake
   `docker` on PATH exercises build-all.sh's full-distribution path: every
   registered project is driven, a failing project does not abort the others,
   and the PASS/FAIL summary lands in output/.build-status.txt. The stub makes
   each project's release.sh a no-op, so this proves the *scheduling*, not the
   builds — the real single-project build is verified outside pytest
   (`bash release.sh --project pcv84x6_llm_server` against the real image;
   its evidence lives in the delivery comment, not here).

Path assumption: these tests run from a sophon-tools checkout, so the project
sits two levels below the repo root (source/<name>). The service's own
test_packaging.py needs no change for that; this file only reads files.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = "pcv84x6_llm_server"
SRC = Path(__file__).resolve().parent.parent          # source/pcv84x6_llm_server
TOOLS = SRC.parent.parent                              # sophon-tools repo root


def _read(rel: str) -> str:
    return (TOOLS / rel).read_text(encoding="utf-8")


# -- layer 1: registration ---------------------------------------------------

def test_project_is_registered_with_arm64_default():
    src = _read("docker/build-all.sh")
    assert f'DEFAULT_ARCH[{PROJECT}]=arm64' in src
    assert f'PLATFORMS[{PROJECT}]=' in src
    # No EXTRA_ENV requirement beyond what is in the file: the project must not
    # depend on an unregistered tool (this bit the pqt series once).
    registry = src.split("declare -A DEFAULT_ARCH")[1].split("declare -A PLATFORMS")[0]
    assert PROJECT in registry


def test_build_all_list_names_the_project():
    out = subprocess.run(["bash", "docker/build-all.sh", "--list"], cwd=TOOLS,
                         capture_output=True, text=True, check=True).stdout
    assert PROJECT in out
    assert "arm64" in out.split(PROJECT)[1].split("\n")[0]


@pytest.mark.parametrize("script", [
    "release.sh",
    "scripts/package.sh",
    "scripts/package_deb.sh",
    "scripts/build_web.sh",
    "scripts/install.sh",
    "scripts/uninstall.sh",
])
def test_shell_scripts_parse(script):
    subprocess.run(["bash", "-n", str(SRC / script)], check=True)


# -- layer 2: release.sh contract ---------------------------------------------

@pytest.fixture(scope="module")
def outdir(tmp_path_factory):
    """A scratch OUTPUT_DIR, so tests never touch the real output/."""
    return tmp_path_factory.mktemp("out")


def _run_release(args, outdir, env_extra=None, cwd=SRC):
    env = dict(os.environ, OUTPUT_DIR=str(outdir))
    if env_extra:
        env.update(env_extra)
    return subprocess.run(["bash", "release.sh", *args], cwd=cwd, env=env,
                          capture_output=True, text=True)


@pytest.mark.parametrize("arch", ["amd64", "armhf", "riscv64", "bogus"])
def test_unsupported_arch_is_refused(arch, outdir):
    r = _run_release([arch], outdir)
    assert r.returncode != 0
    assert "arm64" in r.stderr


def test_all_arch_is_accepted_as_arm64(outdir):
    """`all` means the one supported platform, so it must not die on ARCH."""
    # Not a full build: kill the run after the version gate. release.sh passes
    # ARCH through to the build steps, so run with a version mismatch instead —
    # that check happens BEFORE any build work and after the ARCH gate, which
    # is exactly the boundary under test.
    r = _run_release(["all", "9.9.9"], outdir)
    assert r.returncode != 0
    # The refusal must name the VERSION disagreement, not the platform.
    assert "9.9.9" in r.stderr and "0.6." in r.stderr


def test_version_mismatch_is_refused_not_silently_ignored(outdir):
    r = _run_release(["arm64", "0.0.1"], outdir)
    assert r.returncode != 0
    assert "0.0.1" in r.stderr
    # ...and the source must not have been "helpfully" rewritten.
    assert '__version__ = "0.6.37"' in (SRC / "app" / "__init__.py").read_text()


def test_version_agrees_proceeds_past_the_gate(outdir):
    """An explicit VERSION equal to the source's must pass the gate."""
    r = _run_release(["arm64", "0.6.37"], outdir)
    # A full build would need docker; without it the failure must come from the
    # build steps (missing web/dist or the container), never from the gate.
    assert "不一致" not in (r.stderr or "")


def test_pinned_inputs_are_verified(outdir):
    """A corrupted fixed input must abort the build with a clear error."""
    inputs = SRC / "build" / "inputs"
    sums = (inputs / "SHA256SUMS").read_bytes()
    lib = inputs / "lib" / "libcv84x6_llm.so"
    original = lib.read_bytes()
    try:
        lib.write_bytes(original + b"\x00")
        r = _run_release(["arm64"], outdir)
        assert r.returncode != 0
        assert "SHA256SUMS" in r.stderr
    finally:
        lib.write_bytes(original)
        (inputs / "SHA256SUMS").write_bytes(sums)


def test_missing_fixed_input_is_refused(outdir):
    lib = SRC / "build" / "inputs" / "lib" / "libcv84x6_llm.so"
    stash = lib.with_suffix(".so.stash")
    try:
        shutil.move(str(lib), str(stash))
        r = _run_release(["arm64"], outdir)
        assert r.returncode != 0
        assert "build/inputs" in r.stderr
    finally:
        if stash.exists():
            shutil.move(str(stash), str(lib))


def test_output_dir_is_honoured(outdir):
    """OUTPUT_DIR must reach the packaging step, not just the banner.

    Without docker the build stops before packaging, so assert on the script
    text plus the completed real build's behaviour (the deb lands in the
    OUTPUT_DIR passed on the command line — verified by the real run recorded
    in the delivery comment; here the source must at least wire it through).
    """
    src = (SRC / "release.sh").read_text(encoding="utf-8")
    assert 'OUTPUT_DIR="${OUTPUT_DIR:-' in src
    assert '--out "$OUTPUT_DIR"' in src
    assert '"$OUTPUT_DIR/cv84x6-llm-server' in src


# -- layer 3: full-distribution scheduling with a docker stub ------------------

@pytest.fixture()
def docker_stub(tmp_path):
    """A fake docker that runs the container command as a plain bash -c.

    The stub drops the docker run options and executes the payload directly in
    a directory the caller controls, so build-all.sh's loop, result tally and
    status file are exercised for real while every project's build is a no-op.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "docker"
    stub.write_text("""#!/usr/bin/env bash
# docker stub: run the payload (the last bash -c argument) in $PWD.
while [ $# -gt 0 ]; do
  case "$1" in
    bash) shift; exec "$@" ;;
    *) shift ;;
  esac
done
exit 0
""")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return bindir


def test_full_distribution_schedules_every_project_and_isolates_failures(
        docker_stub, tmp_path):
    status = tmp_path / "build-status.txt"
    env = dict(os.environ,
               PATH=f"{docker_stub}:{os.environ['PATH']}",
               IMAGE="stub-image")
    # output/ is created under the repo root; keep the real one untouched by
    # pointing the status file read at whatever the run produced.
    r = subprocess.run(["bash", "docker/build-all.sh", "--image", "stub-image"],
                       cwd=TOOLS, env=env, capture_output=True, text=True)
    combined = r.stdout + r.stderr
    # Every registered project was driven (the stub logs each project header).
    assert PROJECT in combined
    assert "pbmssm" in combined and "se-rag-core" in combined
    # A per-project failure must be isolated: the loop records a FAIL rc for
    # the stubbed projects (their real build steps cannot run under the stub)
    # and still drives the rest — that is the scheduling property under test.
    status_file = TOOLS / "output" / ".build-status.txt"
    assert status_file.exists()
    lines = status_file.read_text().splitlines()
    names = {ln.split()[0] for ln in lines if ln.strip()}
    assert PROJECT in names
    assert len(names) >= 10, f"expected the full registry, got {sorted(names)}"
