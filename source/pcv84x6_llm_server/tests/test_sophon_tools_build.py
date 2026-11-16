"""sophon-tools unified-build integration for pcv84x6_llm_server.

Isolated by construction: every test here either reads source text (static
contracts) or runs against a MINIMAL throw-away repository built in tmp_path
with all heavy steps stubbed. Nothing in this file touches the real checkout's
output/, the real build inputs, npm/pip, the network, or the caller's git
configuration. The real single-project build is verified separately
(`bash release.sh --project pcv84x6_llm_server` against the real image; its
evidence lives in the delivery comment).

Layers:

1. Static contracts — the project is registered with the right default arch;
   shell scripts parse; the fixed-input manifest pins the real files; the
   vendor lockfile is the single version source for every wheel package.sh
   installs (including tokenizers, which the first version of this work left
   floating).
2. release.sh argument handling in a minimal fixture repo — the ARCH and
   VERSION gates, the fixed-input gate (missing / corrupted), and OUTPUT_DIR
   reaching the deb name. The build itself is stubbed: the fixture's
   scripts/build_web.sh and scripts/package_deb.sh write a marker deb.
3. Unified scheduling with a docker stub — build-all.sh's full-distribution
   loop is driven with a fake docker that RECORDS (project, workdir, OUTPUT_DIR)
   and runs a no-op payload, one designated project forced to fail. Asserts the
   whole registry was driven, the failure was recorded, the rest continued,
   and the exit code is non-zero.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

PROJECT = "pcv84x6_llm_server"
SRC = Path(__file__).resolve().parent.parent          # source/pcv84x6_llm_server
TOOLS = SRC.parent.parent                              # sophon-tools repo root


def _read(rel: str) -> str:
    return (TOOLS / rel).read_text(encoding="utf-8")


# -- layer 1: static contracts -------------------------------------------------

def test_project_is_registered_with_arm64_default():
    src = _read("docker/build-all.sh")
    assert f'DEFAULT_ARCH[{PROJECT}]=arm64' in src
    assert f'PLATFORMS[{PROJECT}]=' in src
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


def test_fixed_inputs_manifest_matches_files():
    """SHA256SUMS must actually pin the shipped fixed inputs (no drift)."""
    import hashlib
    inputs = SRC / "build" / "inputs"
    lines = (inputs / "SHA256SUMS").read_text().splitlines()
    assert lines, "SHA256SUMS is empty"
    for line in lines:
        digest, rel = re.split(r"\s+", line.strip(), maxsplit=1)
        path = inputs / rel
        assert path.exists(), f"manifest names a missing input: {rel}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, rel


def test_every_vendor_install_is_locked_to_the_lockfile():
    """No wheel may resolve a floating version at build time.

    package.sh installs the vendored stack from requirements-vendor-lock.txt
    and a few wheels separately with --no-deps. --no-deps skips dependency
    resolution, NOT version selection, so every one of those separate installs
    must also read its version from the lockfile.
    """
    src = (SRC / "scripts" / "package.sh").read_text(encoding="utf-8")
    lock = (SRC / "requirements-vendor-lock.txt").read_text(encoding="utf-8")
    # A bare `_vendor_pip --no-deps <name>` (no pinned spec) must not exist.
    for line in src.splitlines():
        line = line.strip()
        if not line.startswith("_vendor_pip ") and not line.startswith("_vendor_pip -"):
            continue
        pinned = ("requirements-vendor-lock.txt" in line
                  or "-r \"$STAGE/" in line
                  or "_SPEC\"" in line or "_PKG\"" in line)
        assert pinned, f"vendor install not pinned to the lockfile: {line}"
    # And the tokenizers install specifically reads tokenizers== from the lock.
    assert "tokenizers==" in src
    assert re.search(r"^tokenizers==[^#\s]+", lock, re.M)


def test_build_web_uses_npm_ci_with_committed_lockfile():
    src = (SRC / "scripts" / "build_web.sh").read_text(encoding="utf-8")
    assert "npm ci" in src
    assert "package-lock.json" in src
    assert "npm install" not in src.split("npm ci")[0].replace("#", ""), \
        "plain npm install must not remain in the build path"
    assert (SRC / "web" / "package-lock.json").exists()


def test_no_caller_user_pip_mutation_in_package_sh():
    """The build must not upgrade the caller's own pip installation."""
    src = (SRC / "scripts" / "package.sh").read_text(encoding="utf-8")
    assert "--user" not in src.split("pip install")[1].split("\n")[0] or True
    # Stronger form: no pip --user upgrade anywhere.
    for line in src.splitlines():
        if "pip" in line and "--user" in line:
            raise AssertionError(f"caller user pip touched: {line}")
    # pip is provisioned inside the staging area instead.
    assert "--target \"$STAGE/pip-host\"" in src


# -- layer 2: release.sh in a minimal fixture repo ------------------------------

FIXTURE_VERSION = "0.6.37"


@pytest.fixture()
def fixture_repo(tmp_path):
    """A minimal stand-in for source/pcv84x6_llm_server with stubbed builds.

    Contains ONLY what release.sh reads: app/__init__.py (version source), the
    fixed build inputs, and stub build/packaging scripts. release.sh itself is
    copied verbatim from the real tree — that is the code under test.
    """
    repo = tmp_path / "repo"
    sub = repo / "source" / PROJECT
    (sub / "app").mkdir(parents=True)
    (sub / "app" / "__init__.py").write_text(f'__version__ = "{FIXTURE_VERSION}"\n')
    inputs = sub / "build" / "inputs"
    (inputs / "lib").mkdir(parents=True)
    (inputs / "qwen3_5-config").mkdir()
    lib = inputs / "lib" / "libcv84x6_llm.so"
    lib.write_bytes(b"\x7fELF-fake-aarch64-lib")
    tok = inputs / "qwen3_5-config" / "tokenizer.json"
    tok.write_text("{}")
    import hashlib
    (inputs / "SHA256SUMS").write_text(
        f"{hashlib.sha256(lib.read_bytes()).hexdigest()}  lib/libcv84x6_llm.so\n"
        f"{hashlib.sha256(tok.read_bytes()).hexdigest()}  qwen3_5-config/tokenizer.json\n")
    (sub / "scripts").mkdir()
    # Stub build/packaging: record the call and write a marker deb.
    (sub / "scripts" / "build_web.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\necho 'stub web build'\n")
    (sub / "scripts" / "package_deb.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "out=\"\"\n"
        "while [ $# -gt 0 ]; do case \"$1\" in --out) out=$2; shift 2;; *) shift;; esac; done\n"
        "mkdir -p \"$out\"\n"
        "echo fake-deb > \"$out/cv84x6-llm-server_${FAKE_VERSION:-0.6.37}_arm64.deb\"\n"
        "(cd \"$out\" && sha256sum cv84x6-llm-server_*.deb > cv84x6-llm-server_0.6.37_arm64.deb.sha256)\n"
        "echo \"stub packaged into $out\"\n")
    shutil.copy(SRC / "release.sh", sub / "release.sh")
    return sub


def _run_release(repo: Path, args, outdir, env_extra=None):
    env = dict(os.environ, OUTPUT_DIR=str(outdir))
    if env_extra:
        env.update(env_extra)
    return subprocess.run(["bash", "release.sh", *args], cwd=repo, env=env,
                          capture_output=True, text=True)


@pytest.mark.parametrize("arch", ["amd64", "armhf", "riscv64", "bogus"])
def test_unsupported_arch_is_refused(arch, fixture_repo, tmp_path):
    r = _run_release(fixture_repo, [arch], tmp_path / "out")
    assert r.returncode != 0
    assert "arm64" in r.stderr


def test_version_mismatch_is_refused_and_source_untouched(fixture_repo, tmp_path):
    r = _run_release(fixture_repo, ["arm64", "0.0.1"], tmp_path / "out")
    assert r.returncode != 0
    assert "0.0.1" in r.stderr
    assert f'__version__ = "{FIXTURE_VERSION}"' in (
        fixture_repo / "app" / "__init__.py").read_text()


def test_version_agreement_builds_into_output_dir(fixture_repo, tmp_path):
    """Happy path with stubbed builds: OUTPUT_DIR must receive the deb."""
    out = tmp_path / "custom-out"
    r = _run_release(fixture_repo, ["arm64", FIXTURE_VERSION], out)
    assert r.returncode == 0, r.stderr + r.stdout
    assert (out / f"cv84x6-llm-server_{FIXTURE_VERSION}_arm64.deb").exists()
    assert "stub packaged" in r.stdout


def test_all_arch_is_accepted_as_arm64(fixture_repo, tmp_path):
    out = tmp_path / "out-all"
    r = _run_release(fixture_repo, ["all"], out)
    assert r.returncode == 0, r.stderr
    assert (out / f"cv84x6-llm-server_{FIXTURE_VERSION}_arm64.deb").exists()


def test_corrupted_fixed_input_aborts_the_build(fixture_repo, tmp_path):
    lib = fixture_repo / "build" / "inputs" / "lib" / "libcv84x6_llm.so"
    lib.write_bytes(lib.read_bytes() + b"\x00")
    r = _run_release(fixture_repo, ["arm64"], tmp_path / "out")
    assert r.returncode != 0
    assert "SHA256SUMS" in r.stderr


def test_missing_fixed_input_aborts_the_build(fixture_repo, tmp_path):
    (fixture_repo / "build" / "inputs" / "lib" / "libcv84x6_llm.so").unlink()
    r = _run_release(fixture_repo, ["arm64"], tmp_path / "out")
    assert r.returncode != 0
    assert "build/inputs" in r.stderr


# -- layer 3: unified scheduling with a recording docker stub -------------------

@pytest.fixture()
def mini_unified(tmp_path):
    """A minimal sophon-tools repo whose build-all.sh is the real one.

    Every registered project gets a stub source directory with a no-op
    release.sh that just appends to a per-project log. The docker stub records
    (project, workdir, OUTPUT_DIR) instead of running the container payload.
    """
    root = tmp_path / "unified"
    (root / "docker").mkdir(parents=True)
    (root / "source").mkdir()
    (root / "output").mkdir()
    shutil.copy(TOOLS / "docker" / "build-all.sh", root / "docker" / "build-all.sh")
    # versions.env is sourced for the default image name.
    (root / "docker" / "versions.env").write_text('IMAGE_TAG="stub"\n')
    # The git-version helper build-all.sh sources at startup.
    (root / "docker" / "scripts").mkdir()
    shutil.copy(TOOLS / "docker" / "scripts" / "git-version.sh",
                root / "docker" / "scripts" / "git-version.sh")
    # Read the REAL registry out of the real build-all.sh so the fixture covers
    # exactly what production will drive (no drift between test and reality).
    registry = re.findall(r"DEFAULT_ARCH\[([^\]]+)\]=(\S+)",
                          (TOOLS / "docker" / "build-all.sh").read_text())
    projects = [p for p, _ in registry]
    for p in projects:
        src = root / "source" / p
        src.mkdir()
        (src / "release.sh").write_text(
            f"#!/usr/bin/env bash\necho \"{p} stub release arch=$1 out=$OUTPUT_DIR\"\n"
            f"echo '{p}' >> \"${{BUILD_CALL_LOG:-/dev/null}}\"\n")
    # Recording docker stub on PATH.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text("""#!/usr/bin/env bash
# Record the invocation (project = container -w basename); never run the payload.
workdir=""
outdir=""
while [ $# -gt 0 ]; do
  case "$1" in
    -w) workdir="$2"; shift 2 ;;
    -e) case "$2" in OUTPUT_DIR=*) outdir="${2#OUTPUT_DIR=}";; esac; shift 2 ;;
    *) shift ;;
  esac
done
project=$(basename "$workdir")
echo "$project|$workdir|$outdir" >> "$DOCKER_RECORD"
if [ "$project" = "pget_info" ]; then exit 3; fi
exit 0
""")
    (bindir / "docker").chmod(0o755)
    env = dict(os.environ,
               PATH=f"{bindir}:{os.environ['PATH']}",
               DOCKER_RECORD=str(tmp_path / "docker-record.log"),
               BUILD_CALL_LOG=str(tmp_path / "release-calls.log"))
    return root, projects, env


def test_full_distribution_drives_every_project_and_isolates_failure(mini_unified):
    root, projects, env = mini_unified
    r = subprocess.run(["bash", "docker/build-all.sh"], cwd=root, env=env,
                       capture_output=True, text=True)
    record = Path(env["DOCKER_RECORD"]).read_text().splitlines()
    driven = {line.split("|")[0] for line in record}
    # The entire real registry was driven, including the new project.
    assert driven == set(projects), f"missing: {set(projects) - driven}"
    assert PROJECT in driven
    # The designated failure was recorded, everything else continued.
    assert "pget_info" in driven
    status = (root / "output" / ".build-status.txt").read_text()
    assert "pget_info" in status and "fail:3" in status
    # Others (including the new project) are ok; failure is not silent.
    assert re.search(rf"{PROJECT}\s+ok", status)
    # Exit code must be non-zero because one project failed.
    assert r.returncode != 0
    # OUTPUT_DIR was passed per project into the container workdir.
    for line in record:
        _, _, out = line.split("|")
        assert out.endswith("/output/" + line.split("|")[0])


def test_single_project_selection_drives_only_that_project(mini_unified):
    root, projects, env = mini_unified
    r = subprocess.run(["bash", "docker/build-all.sh", "--project", PROJECT],
                       cwd=root, env=env, capture_output=True, text=True)
    record = Path(env["DOCKER_RECORD"]).read_text().splitlines()
    assert [line.split("|")[0] for line in record] == [PROJECT]
    assert r.returncode == 0, r.stderr
