"""dfss self-bootstrap: a board with pip but no dfss must still download.

Every test here drives a **real** interpreter, because the thing under test is
"does ``<python> -m dfss`` work now", and that answer lives in the exit code of a
subprocess, not in a mock. The fake interpreter is a small shell script on
``PATH``-free absolute paths that understands exactly the three invocations this
module makes:

    <fake> -m dfss --help     -> 0 once "installed", 1 with ModuleNotFoundError
    <fake> -m dfss --url=...  -> writes the "remote" file into the cwd
    <fake> -m pip install ... -> creates the marker the first two look at

That is enough to exercise the decisions: when pip runs, when it must not, what
happens when it fails, and that concurrent callers install once.
"""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest

from app.core import downloader
from app.core.downloader import (
    DFSS_BOOTSTRAP_ENV,
    DFSS_SPEC,
    DownloadManager,
    dfss_bootstrap_allowed,
    dfss_offline,
    ensure_dfss,
    reset_dfss_bootstrap_cache,
    run_dfss,
)

FAKE_PY = """#!/bin/sh
# A stand-in for the board's python3.10. $FAKE_STATE is its "site-packages".
state="${FAKE_STATE:?}"
cmd="$1"; shift

if [ "$cmd" = "-m" ]; then
  mod="$1"; shift
  case "$mod" in
    dfss)
      if [ ! -f "$state/dfss-installed" ]; then
        echo "Traceback (most recent call last):" >&2
        echo "ModuleNotFoundError: No module named 'dfss'" >&2
        exit 1
      fi
      case "$1" in
        --help)
          echo "dfss python tool, version: 1.10.8"
          if [ -f "$state/dfss-has-dflag" ]; then
            echo "usage: dfss [-h] [--url URL] [--user USER] [--dflag DFLAG]"
            echo "  --dflag DFLAG         using download flag to get file"
          else
            echo "usage: dfss [-h] [--url URL] [--user USER]"
          fi
          exit 0 ;;
        --url=*)
          url="${1#--url=}"
          name="${url##*/}"
          if [ -n "$FAKE_DFSS_FAIL" ]; then
            echo "ERROR main.cpp:1383: Cannot download $url from host"
            exit 1
          fi
          echo "data:$name" > "$name"
          echo "[3.10 KiB] 100% [====] 3.89 MiB/s"
          exit 0 ;;
      esac
      exit 0 ;;
    pip)
      # Argument order: install --user --upgrade ... <spec>
      echo "Requirement already satisfied: pip"
      if [ -n "$FAKE_PIP_FAIL" ]; then
        echo "ERROR: Could not find a version that satisfies the requirement dfss"
        echo "ERROR: No matching distribution found for dfss"
        exit 1
      fi
      : > "$state/dfss-installed"
      # The wheel this index serves: a modern one unless a test says otherwise.
      if [ -z "$FAKE_OLD_WHEEL" ]; then : > "$state/dfss-has-dflag"; fi
      echo "Successfully installed dfss-1.10.8"
      exit 0 ;;
  esac
fi
echo "unexpected invocation: $cmd $*" >&2
exit 2
"""


@pytest.fixture()
def fake_python(tmp_path, monkeypatch) -> Path:
    """A fake interpreter plus a clean environment for the bootstrap."""
    state = tmp_path / "site"
    state.mkdir()
    script = tmp_path / "python3.10"
    script.write_text(FAKE_PY)
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("FAKE_STATE", str(state))
    monkeypatch.delenv("FAKE_PIP_FAIL", raising=False)
    monkeypatch.delenv("FAKE_DFSS_FAIL", raising=False)
    monkeypatch.delenv("FAKE_OLD_WHEEL", raising=False)
    monkeypatch.delenv(downloader.DFSS_PYTHON_ENV, raising=False)
    monkeypatch.delenv(DFSS_BOOTSTRAP_ENV, raising=False)
    monkeypatch.delenv("CV84X6_AGENT_OFFLINE", raising=False)
    reset_dfss_bootstrap_cache()
    yield script
    reset_dfss_bootstrap_cache()


def install_marker(script: Path) -> Path:
    return Path(os.environ["FAKE_STATE"]) / "dfss-installed"


def dflag_marker() -> Path:
    """The marker the fake interpreter reports ``--dflag`` from."""
    return Path(os.environ["FAKE_STATE"]) / "dfss-has-dflag"


# -- the import probe and the install decision -----------------------------

async def test_an_interpreter_that_already_has_dfss_never_runs_pip(fake_python):
    """No pip on every download: the common case must be a single probe."""
    install_marker(fake_python).touch()
    lines: list[str] = []
    got = await ensure_dfss(str(fake_python), lines.append)
    assert got == str(fake_python)
    # Nothing was announced, because nothing had to happen.
    assert lines == []


async def test_a_missing_dfss_is_installed_and_then_imports(fake_python):
    """The actual bug: pip is there, dfss is not, and the download must proceed."""
    lines: list[str] = []
    got = await ensure_dfss(str(fake_python), lines.append)
    assert got == str(fake_python)
    assert install_marker(fake_python).is_file()
    joined = "\n".join(lines)
    # The operator sees the install happen, with the spec and pip's own words.
    assert DFSS_SPEC in joined
    assert "Successfully installed dfss-1.10.8" in joined


async def test_the_bootstrap_runs_pip_through_the_same_interpreter(fake_python, monkeypatch):
    """--user into the *running* interpreter's site, not whatever pip is on PATH."""
    seen: list[list[str]] = []
    real = downloader._pip_install

    async def spy(argv, on_line=None):
        seen.append(argv)
        return await real(argv, on_line)

    monkeypatch.setattr(downloader, "_pip_install", spy)
    await ensure_dfss(str(fake_python))
    assert seen, "pip was never invoked"
    argv = seen[0]
    assert argv[0] == str(fake_python)
    assert argv[1:4] == ["-m", "pip", "install"]
    assert "--user" in argv
    assert DFSS_SPEC in argv


async def test_a_second_caller_reuses_the_first_install(fake_python, monkeypatch):
    """A model and an agent downloading together must not race two pip runs."""
    calls = [0]
    real = downloader._pip_install

    async def counting(argv, on_line=None):
        calls[0] += 1
        # A real pip takes seconds; this makes the overlap certain.
        await asyncio.sleep(0.05)
        return await real(argv, on_line)

    monkeypatch.setattr(downloader, "_pip_install", counting)
    await asyncio.gather(
        ensure_dfss(str(fake_python)), ensure_dfss(str(fake_python)),
        ensure_dfss(str(fake_python)),
    )
    assert calls[0] == 1
    assert install_marker(fake_python).is_file()


async def test_concurrent_callers_do_not_both_install(fake_python):
    """Same as above without the sleep: the lock, not luck, is what serialises."""
    marker = install_marker(fake_python)
    results = await asyncio.gather(
        *[ensure_dfss(str(fake_python)) for _ in range(5)], return_exceptions=True,
    )
    assert all(r == str(fake_python) for r in results), results
    assert marker.is_file()


# -- refusals, each with a reason an operator can act on --------------------

async def test_offline_refuses_to_reach_pypi(fake_python, monkeypatch):
    """CV84X6_AGENT_OFFLINE=1 means no network, so pip must not be tried."""
    monkeypatch.setenv("CV84X6_AGENT_OFFLINE", "1")
    installed: list[int] = []
    monkeypatch.setattr(downloader, "_pip_install",
                        lambda *a, **k: installed.append(1))
    with pytest.raises(RuntimeError) as excinfo:
        await ensure_dfss(str(fake_python))
    message = str(excinfo.value)
    assert "离线" in message
    # It says how to fix it offline rather than just refusing.
    assert "wheel" in message
    assert "CV84X6_DFSS_PYTHON" in message
    assert installed == []
    assert not install_marker(fake_python).exists()


async def test_offline_does_nothing_when_dfss_is_already_there(fake_python, monkeypatch):
    """Offline is a constraint on installing, not on using what is present."""
    install_marker(fake_python).touch()
    monkeypatch.setenv("CV84X6_AGENT_OFFLINE", "1")
    assert await ensure_dfss(str(fake_python)) == str(fake_python)


async def test_bootstrap_can_be_turned_off(fake_python, monkeypatch):
    monkeypatch.setenv(DFSS_BOOTSTRAP_ENV, "0")
    with pytest.raises(RuntimeError) as excinfo:
        await ensure_dfss(str(fake_python))
    assert "CV84X6_DFSS_BOOTSTRAP" in str(excinfo.value)
    assert "pip install --user" in str(excinfo.value)
    assert not install_marker(fake_python).exists()


async def test_a_failed_pip_install_reports_pip_and_dfss_reasons(fake_python, monkeypatch):
    """A failure must not be reported as a successful model download.

    The message carries pip's own rejection *and* the fact that the module still
    does not import, which is what distinguishes "no wheel for this arch" from
    "installed but broken".
    """
    monkeypatch.setenv("FAKE_PIP_FAIL", "1")
    with pytest.raises(RuntimeError) as excinfo:
        await ensure_dfss(str(fake_python))
    message = str(excinfo.value)
    assert "dfss 自动安装失败" in message
    assert "pip 退出码 1" in message
    assert "No matching distribution" in message
    assert "ModuleNotFoundError" in message


async def test_a_burst_of_failures_costs_one_pip_attempt(fake_python, monkeypatch):
    """Three jobs started together must not each run pip against a dead index."""
    monkeypatch.setenv("FAKE_PIP_FAIL", "1")
    calls = [0]
    real = downloader._pip_install

    async def counting(argv, on_line=None):
        calls[0] += 1
        return await real(argv, on_line)

    monkeypatch.setattr(downloader, "_pip_install", counting)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await ensure_dfss(str(fake_python))
    assert calls[0] == 1
    assert downloader.DFSS_FAILURE_COOLDOWN_S > 0


async def test_a_stale_failure_is_retried(fake_python, monkeypatch):
    """Fixing the network must be enough; a restart cannot be the remedy.

    Without an expiry, one flaky index lookup would keep downloads broken for
    the life of the process -- and the operator has no reason to connect the two.
    """
    monkeypatch.setenv("FAKE_PIP_FAIL", "1")
    calls = [0]
    real = downloader._pip_install

    async def counting(argv, on_line=None):
        calls[0] += 1
        return await real(argv, on_line)

    monkeypatch.setattr(downloader, "_pip_install", counting)
    with pytest.raises(RuntimeError):
        await ensure_dfss(str(fake_python))
    assert calls[0] == 1

    # Pretend the cooldown expired, then let pip succeed this time.
    installed, message, _at = downloader._dfss_install_result
    downloader._dfss_install_result = (installed, message, -1e9)
    monkeypatch.delenv("FAKE_PIP_FAIL")
    assert await ensure_dfss(str(fake_python)) == str(fake_python)
    assert calls[0] == 2
    assert install_marker(fake_python).is_file()


async def test_a_missing_interpreter_says_so_instead_of_crashing(fake_python, tmp_path):
    ghost = tmp_path / "does-not-exist" / "python3"
    with pytest.raises(RuntimeError) as excinfo:
        await ensure_dfss(str(ghost))
    assert "找不到" in str(excinfo.value) or "dfss" in str(excinfo.value)


# -- wiring: the download path and the env helpers -------------------------

async def test_run_dfss_bootstraps_first_so_the_transfer_can_start(fake_python, tmp_path,
                                                                 monkeypatch):
    """One call: dfss was missing, and the file still arrives.

    This is the shape of the real bug -- ``run_dfss`` used to invoke
    ``<python> -m dfss`` against an interpreter with no dfss and fail with a
    bare exit code. Now the bootstrap happens inside the same call.
    """
    monkeypatch.setenv(downloader.DFSS_PYTHON_ENV, str(fake_python))
    dest = tmp_path / "out"
    rc, tail = await run_dfss("open@sophgo.com:/x/model.bmodel", dest)
    assert rc == 0, tail
    assert (dest / "model.bmodel").read_text().strip() == "data:model.bmodel"
    assert install_marker(fake_python).is_file()


async def test_run_dfss_with_the_fake_interpreter(fake_python, tmp_path, monkeypatch):
    monkeypatch.setenv(downloader.DFSS_PYTHON_ENV, str(fake_python))
    install_marker(fake_python).touch()
    dest = tmp_path / "out"
    rc, tail = await run_dfss("open@sophgo.com:/x/model.bmodel", dest)
    assert rc == 0, tail
    assert (dest / "model.bmodel").read_text().strip() == "data:model.bmodel"


async def test_run_dfss_can_skip_the_bootstrap(fake_python, tmp_path, monkeypatch):
    """bootstrap=False is what the manager uses after installing dfss itself."""
    monkeypatch.setenv(downloader.DFSS_PYTHON_ENV, str(fake_python))
    rc, _tail = await run_dfss("open@sophgo.com:/x/m.bmodel", tmp_path / "o",
                               bootstrap=False)
    # The fake has no dfss yet, so this is a clean failure rather than an install.
    assert rc == 1
    assert not install_marker(fake_python).exists()


async def test_the_download_job_reports_the_bootstrap_failure_as_its_message(
        fake_python, tmp_path, monkeypatch):
    """A bootstrap failure is the job's error text, not an opaque exit code."""
    monkeypatch.setenv(downloader.DFSS_PYTHON_ENV, str(fake_python))
    monkeypatch.setenv("CV84X6_AGENT_OFFLINE", "1")
    mgr = DownloadManager(tmp_path / "models")
    job = mgr.start_dfss("open@sophgo.com:/x/m.bmodel", "qwen-test")
    assert mgr._tasks[job.id] is not None
    await mgr._tasks[job.id]
    assert job.state == "error"
    assert "离线" in job.message
    assert "Traceback" not in job.message


async def test_a_successful_dfss_download_through_the_manager(fake_python, tmp_path,
                                                             monkeypatch):
    """End to end on the model path: install, transfer, job done."""
    monkeypatch.setenv(downloader.DFSS_PYTHON_ENV, str(fake_python))
    mgr = DownloadManager(tmp_path / "models")
    job = mgr.start_dfss("open@sophgo.com:/x/model.bmodel", "qwen-test")
    await mgr._tasks[job.id]
    assert job.state == "done", job.message
    assert (tmp_path / "models" / "qwen-test" / "model.bmodel").is_file()


def test_offline_flag_accepts_the_same_spellings_as_the_agent_installer(monkeypatch):
    """One env var, one meaning; the agent code already spells these five ways."""
    for value in ("1", "true", "True", "yes", "on"):
        monkeypatch.setenv("CV84X6_AGENT_OFFLINE", value)
        assert dfss_offline() is True, value
    for value in ("", "0", "false", "False", "no", "off"):
        monkeypatch.setenv("CV84X6_AGENT_OFFLINE", value)
        assert dfss_offline() is False, value


def test_bootstrap_is_on_by_default(monkeypatch):
    monkeypatch.delenv(DFSS_BOOTSTRAP_ENV, raising=False)
    assert dfss_bootstrap_allowed() is True
    for value in ("0", "false", "OFF"):
        monkeypatch.setenv(DFSS_BOOTSTRAP_ENV, value)
        assert dfss_bootstrap_allowed() is False, value


async def test_the_agent_installer_gets_the_same_bootstrap(fake_python, tmp_path, monkeypatch):
    """Both consumers share ``run_dfss``, so the agent path self-heals too.

    ``download_dfss_file`` is what ``AgentManager._download_dfss`` calls; if the
    bootstrap were only wired into the model path, an agent install on a fresh
    board would still die with "ModuleNotFoundError". Driven with the real fake
    interpreter, so the evidence is a file on disk and not a mock call.
    """
    from app.core.downloader import download_dfss_file

    monkeypatch.setenv(downloader.DFSS_PYTHON_ENV, str(fake_python))
    lines: list[str] = []
    dest = tmp_path / "opencode-linux-arm64.tar.gz"
    tail = await download_dfss_file(
        "open@sophgo.com:/tools/cv84x6_llm_server/agents/opencode-linux-arm64.tar.gz",
        dest, lines.append,
    )
    assert dest.is_file()
    assert install_marker(fake_python).is_file()
    # The install was visible to the agent's job log, not only to the service log.
    assert any(DFSS_SPEC in line for line in lines)
    assert tail, "dfss output was not returned"


# -- download tags: does this dfss understand ``--dflag``? -----------------
# The check is the tool's own ``--help`` listing, not a version string: the
# vendor's wrapper prints the option list, and that is authoritative for the
# wheel actually installed. A board imaged before tags existed has a dfss that
# rejects the option outright, so asking it rather than assuming is the whole
# point.

async def test_a_modern_dfss_is_reported_as_tag_capable(fake_python):
    """Already-present dfss with the option: no pip, capability recorded."""
    install_marker(fake_python).touch()
    dflag_marker().touch()
    calls: list[list[str]] = []
    real = downloader._pip_install

    async def spy(argv, on_line=None):
        calls.append(argv)
        return await real(argv, on_line)

    monkey_list = downloader._pip_install
    downloader._pip_install = spy
    try:
        assert await ensure_dfss(str(fake_python), require_dflag=True) == str(fake_python)
        assert downloader.dfss_dflag_supported(str(fake_python)) is True
    finally:
        downloader._pip_install = monkey_list
    assert calls == [], "a capable dfss must not trigger an upgrade"


async def test_an_old_dfss_is_upgraded_when_a_tag_is_needed(fake_python):
    """1.10.8 has no ``--dflag``; the tag path must not silently fail on it."""
    install_marker(fake_python).touch()   # present, but pre-tag
    assert dflag_marker().exists() is False
    lines: list[str] = []
    assert await ensure_dfss(str(fake_python), lines.append,
                             require_dflag=True) == str(fake_python)
    assert dflag_marker().is_file(), "the wheel was not upgraded"
    assert downloader.dfss_dflag_supported(str(fake_python)) is True
    # The upgrade is announced, with the floor it is going to.
    assert any("--dflag" in line and downloader.DFSS_DFLAG_MIN in line for line in lines)


async def test_an_old_dfss_is_left_alone_when_no_tag_is_needed(fake_python):
    """A plain URL pull has no reason to upgrade a working tool."""
    install_marker(fake_python).touch()
    assert await ensure_dfss(str(fake_python)) == str(fake_python)
    assert downloader.dfss_dflag_supported(str(fake_python)) is False
    assert not dflag_marker().exists()


async def test_an_index_that_still_serves_an_old_wheel_falls_back(fake_python, monkeypatch):
    """Upgrading succeeded but the option is still missing: report, do not raise.

    The download can still proceed over the fixed URL, so failing here would
    turn a mirror that lags behind into a board that cannot download at all.
    """
    install_marker(fake_python).touch()
    monkeypatch.setenv("FAKE_OLD_WHEEL", "1")
    lines: list[str] = []
    assert await ensure_dfss(str(fake_python), lines.append,
                             require_dflag=True) == str(fake_python)
    assert downloader.dfss_dflag_supported(str(fake_python)) is False
    assert any("仍不支持 --dflag" in line for line in lines)


async def test_a_disabled_bootstrap_does_not_fail_a_tag_pull(fake_python, monkeypatch):
    """Bootstrap off + old dfss: fall back to the URL rather than refusing."""
    install_marker(fake_python).touch()
    monkeypatch.setenv(DFSS_BOOTSTRAP_ENV, "0")
    lines: list[str] = []
    assert await ensure_dfss(str(fake_python), lines.append,
                             require_dflag=True) == str(fake_python)
    assert downloader.dfss_dflag_supported(str(fake_python)) is False
    assert any("固定地址" in line for line in lines)


def test_the_capability_is_read_from_the_help_text():
    """Both spellings the tool has used count as support."""
    assert downloader.help_has_dflag(["usage: dfss [-h] [--dflag DFLAG]"]) is True
    assert downloader.help_has_dflag(["  --dflag DFLAG   using download flag"]) is True
    assert downloader.help_has_dflag(["usage: dfss [-h] [--url URL]"]) is False
    assert downloader.help_has_dflag([]) is False


def test_an_unprobed_interpreter_counts_as_unsupported(monkeypatch):
    """Unknown must mean "use the fixed URL", never "try an option blindly"."""
    downloader.reset_dfss_caps()
    monkeypatch.setenv(downloader.DFSS_PYTHON_ENV, "/nonexistent/python3")
    assert downloader.dfss_dflag_supported() is False


async def test_run_dfss_flag_invokes_the_option(fake_python, tmp_path, monkeypatch):
    """The argv the tool actually receives, rather than a mock of our own code."""
    monkeypatch.setenv(downloader.DFSS_PYTHON_ENV, str(fake_python))
    install_marker(fake_python).touch()
    dflag_marker().touch()

    seen: list[list[str]] = []

    async def spy(argv, cwd, on_line=None):
        seen.append(argv)
        return 0, ["ok"]

    monkeypatch.setattr(downloader, "_run_dfss_process", spy)
    await downloader.run_dfss_flag("cv84x6_llm_test", tmp_path / "o")
    assert seen and seen[0][-1] == "--dflag=cv84x6_llm_test"


async def test_the_upgrade_asks_for_a_spec_that_actually_moves_pip(fake_python):
    """``--upgrade 'dfss>=1.10.0'`` on an installed 1.10.8 installs nothing.

    pip calls that "already satisfied", so the option would still be missing
    after a successful-looking upgrade and every tag download would keep falling
    back. The requirement has to name the release that has the feature.
    """
    install_marker(fake_python).touch()
    seen: list[list[str]] = []
    real = downloader._pip_install

    async def spy(argv, on_line=None):
        seen.append(argv)
        return await real(argv, on_line)

    downloader._pip_install = spy
    try:
        await ensure_dfss(str(fake_python), require_dflag=True)
    finally:
        downloader._pip_install = real
    assert seen, "no upgrade was attempted"
    assert downloader.DFSS_DFLAG_SPEC in seen[0]
    assert downloader.DFSS_SPEC not in seen[0]


# -- "needs tags" is a preference, never a precondition --------------------
# A board whose dfss is too old for ``--dflag`` can still download over
# ``--url``. Every way the *upgrade* can be unavailable -- offline, bootstrap
# disabled, pip failing, pip timing out -- therefore has to leave that working
# tool alone and let the caller fall back to the fixed address. Raising instead
# would turn "no upgrade prompt" into "cannot download at all", which is worse
# than the state the card found the board in.

async def test_offline_with_an_old_dfss_falls_back_instead_of_failing(fake_python, monkeypatch):
    """``CV84X6_AGENT_OFFLINE=1`` forbids pip -- but dfss itself still works."""
    install_marker(fake_python).touch()   # present, pre-tag
    monkeypatch.setenv("CV84X6_AGENT_OFFLINE", "1")
    lines: list[str] = []
    assert await ensure_dfss(str(fake_python), lines.append,
                             require_dflag=True) == str(fake_python)
    assert downloader.dfss_dflag_supported(str(fake_python)) is False
    assert any("离线" in line and "固定地址" in line for line in lines)


async def test_a_failing_pip_during_the_upgrade_falls_back(fake_python, monkeypatch):
    """An unreachable index must cost the upgrade prompt, not the download."""
    install_marker(fake_python).touch()
    monkeypatch.setenv("FAKE_PIP_FAIL", "1")
    lines: list[str] = []
    assert await ensure_dfss(str(fake_python), lines.append,
                             require_dflag=True) == str(fake_python)
    assert downloader.dfss_dflag_supported(str(fake_python)) is False
    assert any("固定地址" in line for line in lines)


async def test_a_failing_pip_is_still_fatal_when_dfss_is_missing(fake_python, monkeypatch):
    """The baseline rule stands: no dfss and no pip means no way to download."""
    monkeypatch.setenv("FAKE_PIP_FAIL", "1")
    with pytest.raises(RuntimeError) as excinfo:
        await ensure_dfss(str(fake_python), require_dflag=True)
    assert "自动安装失败" in str(excinfo.value)


async def test_a_pip_timeout_during_the_upgrade_falls_back(fake_python, monkeypatch):
    """pip hanging on a dead index must not hang (or fail) the download."""
    install_marker(fake_python).touch()
    real = downloader._pip_install

    async def hang(argv, on_line=None):
        raise RuntimeError("pip install dfss 超过 300 秒未完成")

    monkeypatch.setattr(downloader, "_pip_install", hang)
    lines: list[str] = []
    assert await ensure_dfss(str(fake_python), lines.append,
                             require_dflag=True) == str(fake_python)
    assert downloader.dfss_dflag_supported(str(fake_python)) is False
    assert any("固定地址" in line for line in lines)
    monkeypatch.setattr(downloader, "_pip_install", real)


async def test_a_remembered_upgrade_failure_does_not_fail_the_next_download(
        fake_python, monkeypatch):
    """The bootstrap cache holds failures for 30 s; an upgrade's must not leak.

    A second download inside the cooldown window would otherwise be refused with
    the *first* one's upgrade error, on a box whose dfss is perfectly usable.
    """
    install_marker(fake_python).touch()
    monkeypatch.setenv("FAKE_PIP_FAIL", "1")
    await ensure_dfss(str(fake_python), require_dflag=True)   # records a failure
    monkeypatch.delenv("FAKE_PIP_FAIL")
    # Inside the cooldown, so the cached failure is what answers.
    assert await ensure_dfss(str(fake_python), require_dflag=True) == str(fake_python)
    assert downloader.dfss_dflag_supported(str(fake_python)) is False
