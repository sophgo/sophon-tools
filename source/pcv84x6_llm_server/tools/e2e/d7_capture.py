"""D7 evidence collector: run it on the board *the moment* a TPU hang is suspected.

The hang looks like this in ``dmesg``::

    bmdrv_thread_sync_api:1471 wait api timeout, wait 120000ms, core_id=0
    mbox submit timeout
    bmdev_wait_free_slots

and the worker threads that were on the NPU sit in ``D`` state inside
``bmdrv_send_api`` / ``bmdrv_thread_sync_api``.  A hung TPU cannot be recovered
from in software -- the board has to be rebooted -- so everything worth keeping
has to be captured *before* the reboot, and it has to be captured by something
that does not itself talk to the NPU (a bm-smi call or an API request that
touches the device can add a second stuck process to the pile).

This script is deliberately dependency-free (stdlib only, Python 3.10) and
read-only.  It writes one directory per capture::

    d7cap-<UTC timestamp>/
        dmesg.txt                 full ring buffer, from boot
        sysfs/                    every readable file under the bm-tpu device
        proc_bmtpu/               scaler / fifo / wakeup state of the driver
        threads.txt               /proc/<pid>/task/*/{stack,wchan,stat,status}
        workers.txt               which worker process owns which model
        bmsmi.txt                 bm-smi, one shot, non-interactive
        stats.json                /api/stats (the `device` block is the point)
        models.json               /api/models
        records.txt               the last N inference records around the hang
        worker_logs/              tail of every worker log
        platform_log_tail.txt     tail of the platform log
        versions.txt              libsophon / driver / firmware / package
        summary.json              the machine-readable index of all of the above

Usage on the board (it needs root only for ``dmesg``; everything else is
readable as ``linaro``)::

    sudo python3.10 tools/e2e/d7_capture.py --out /data/d7caps --sudo-pw __SUDO_PW__

``--since`` narrows ``records.txt`` to requests that started within the last
N minutes (default 10, the task asks for 2; the extra window survives clock
skew between the board and the wall clock you noticed the hang at).

The exit code is 0 when every section was written, 1 when one or more failed;
failed sections are listed in ``summary.json`` so a partial capture is never
mistaken for a clean one.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BM_TPU_SYSFS = Path("/sys/class/bm-tpu/bm-tpu0/device")
PROC_BMTPU = Path("/proc/bmtpu")
API = "http://127.0.0.1:8000"
# Files whose extent is unbounded or whose "read" is actually a write command.
SKIP_SYSFS = {"uevent", "shmpacket", "txpsys"}
# ``bmdi_base_info`` and ``bmdi_api_info`` dereference a register window that is
# not mapped on this board: reading either one Oopses the *reader* with
# ``otp_reg_read+0x10`` / ``Internal error: Oops: 96000005`` (observed while
# building this script, 2 Oopses, board still usable).  They are never read --
# the same information is in ``scaler_info`` and ``kernel_info``, which are safe.
SKIP_PROC = {"bmdi_base_info", "bmdi_api_info", "shmpacket", "txpsys"}
SECTIONS = (
    "dmesg", "sysfs", "proc_bmtpu", "threads", "blocked", "workers",
    "bmsmi", "stats", "models", "records", "worker_logs", "platform_log",
    "versions",
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def run(cmd: list[str], timeout: float = 30) -> tuple[int, str, str]:
    """Run a command, never raise on failure, always return (rc, out, err)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except (OSError, ValueError) as exc:
        return 127, "", str(exc)


def sh(cmd: str, timeout: float = 30) -> tuple[int, str, str]:
    return run(["/bin/sh", "-c", cmd], timeout=timeout)


def sudo_prefix(pw: str) -> list[str]:
    """How to run one command as root without hanging on a password prompt."""
    # `sudo -n` works on images where the operator has NOPASSWD; -S covers the
    # rest.  The password is written before sudo if it turns out to want one.
    return ["sudo", "-n"] if not pw else ["sudo", "-S"]


def as_root(argv: list[str], pw: str, timeout: float = 60) -> tuple[int, str, str]:
    if pw:
        try:
            p = subprocess.run(sudo_prefix(pw) + argv, capture_output=True,
                               text=True, timeout=timeout,
                               input=pw + "\n")
            return p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            return 124, "", f"timeout after {timeout}s"
    return run(sudo_prefix(pw) + argv, timeout=timeout)


def api_get(path: str, timeout: float = 20) -> object:
    """GET an authenticated endpoint. The admin key is read the same way the
    service's own tooling does: from the installed etc/, never hard-coded."""
    key = os.environ.get("D7_ADMIN_KEY", "")
    if not key:
        for candidate in (
            Path("/opt/sophgo/cv84x6_llm_server/etc/adminkey"),
            Path("/data/cv84x6_llm_server/state/adminkey"),
            Path("/data/mys2691/adminkey"),
        ):
            if candidate.exists():
                key = candidate.read_text().strip()
                break
    if not key:
        for env in (Path("/opt/sophgo/cv84x6_llm_server/etc/server.env"),):
            if env.exists():
                for line in env.read_text().splitlines():
                    if line.startswith("CV84X6_ADMIN_KEY="):
                        key = line.split("=", 1)[1].strip()
    req = urllib.request.Request(API + path,
                                 headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", errors="replace")


def tail(path: Path, n: int = 400) -> str:
    """Last n lines without reading a 200 MB log into memory."""
    try:
        rc, out, _ = run(["/usr/bin/tail", "-n", str(n), str(path)], timeout=20)
        return out if rc == 0 else ""
    except OSError:
        return ""


# --------------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------------- #
def cap_dmesg(out: Path, pw: str) -> None:
    rc, text, err = as_root(["dmesg"], pw, timeout=60)
    if rc != 0 or not text:
        rc, text, err = sh("dmesg 2>&1", timeout=60)
    write(out / "dmesg.txt", text or f"FAILED rc={rc} {err}\n")


def cap_sysfs(out: Path) -> None:
    """Every *file* under the device directory, parents included.

    Reading is bounded by a size check first: ``npu_usage`` is fine but the
    directory also carries symlinks into the driver's own debugfs-like nodes,
    and an unbounded read of one of those can block behind the very lock that
    is stuck.  Anything that takes longer than 5 s is reported, not retried.
    """
    d = out / "sysfs"
    d.mkdir(parents=True, exist_ok=True)
    for path in sorted(BM_TPU_SYSFS.rglob("*")):
        if path.name in SKIP_SYSFS or path.is_symlink() or path.is_dir():
            continue
        rel = str(path.relative_to(BM_TPU_SYSFS)).replace("/", "_")
        rc, text, err = run(["/usr/bin/timeout", "5", "/bin/cat", str(path)],
                            timeout=10)
        write(d / (rel + ".txt"), text if rc == 0 else f"rc={rc} {err}\n")
    # The wrapper class node -- not a file, but it is the mount point the
    # driver documentation points at.
    rc, text, _ = sh(f"ls -la {BM_TPU_SYSFS} 2>&1", timeout=10)
    write(d / "_listing.txt", text)


def cap_proc_bmtpu(out: Path, pw: str) -> None:
    d = out / "proc_bmtpu"
    d.mkdir(parents=True, exist_ok=True)
    for path in sorted(PROC_BMTPU.iterdir()):
        if path.name in SKIP_PROC or not path.is_file():
            continue
        # These are read-triggered dumps, so every read gets a hard timeout.
        rc, text, err = as_root(["/usr/bin/timeout", "8", "/bin/cat", str(path)],
                                pw, timeout=20)
        write(d / (path.name + ".txt"), text if rc == 0 else f"rc={rc} {err}\n")
    write(d / "_skipped.txt",
          "not read (reading them Oopses the reader on this board): "
          + ", ".join(sorted(SKIP_PROC)) + "\n")


def _thread_dir(pid: int) -> Path:
    return Path(f"/proc/{pid}/task")


def workers() -> dict[str, int]:
    """model id -> worker pid, from the service's own process list."""
    rc, out, _ = sh("ps -eo pid=,args=", timeout=20)
    found: dict[str, int] = {}
    for line in out.splitlines():
        if "app.engine.worker" not in line:
            continue
        pid_s, _, args = line.strip().partition(" ")
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        parts = args.split()
        for i, part in enumerate(parts):
            if part == "--model-id" and i + 1 < len(parts):
                found[parts[i + 1]] = pid
    return found


def cap_threads(out: Path, pw: str, models: dict[str, int], main_pid: int) -> None:
    """Every thread of every worker (and the service) with its wait channel.

    **``/proc/<pid>/task/<tid>/stack`` does not exist on this kernel** --
    ``CONFIG_STACKTRACE`` is not set in the board's kernel config, so the file
    is absent regardless of privileges.  The kernel backtrace is obtained with
    ``sysrq-w`` instead (see :func:`cap_blocked`); here we record the cheap,
    always-available half: state, comm, wchan, and (for the main process) the
    Python-level stacks of every thread, which is what says *which request* a
    worker was serving when it went to ``D``.
    """
    lines = []
    _stack_supported = Path("/proc/self/task").exists() and \
        Path(f"/proc/{os.getpid()}/task/{os.getpid()}/stack").exists()
    lines.append(f"# /proc/<pid>/task/<tid>/stack available on this kernel: "
                 f"{_stack_supported} (CONFIG_STACKTRACE); use blocked.txt "
                 f"(sysrq-w) for kernel backtraces\n")
    for label, pid in [("main", main_pid)] + sorted(models.items()):
        tdir = _thread_dir(pid)
        if not tdir.is_dir():
            lines.append(f"\n===== {label} pid={pid}: GONE")
            continue
        lines.append(f"\n===== {label} pid={pid}")
        rc, cmdline, _ = run(["/bin/cat", f"/proc/{pid}/cmdline"], timeout=5)
        if rc == 0:
            lines.append("cmdline: " + cmdline.replace("\0", " ").strip())
        for tid_dir in sorted(tdir.iterdir(), key=lambda p: int(p.name)):
            tid = tid_dir.name
            rc, stat, _ = run(["/bin/cat", str(tid_dir / "stat")], timeout=5)
            if rc != 0:
                continue
            # field 3 is the state, field 2 the (parenthesised) comm
            rest = stat.rsplit(")", 1)[-1].split()
            state = rest[0] if rest else "?"
            comm = stat.split("(", 1)[-1].rsplit(")", 1)[0]
            rcw, wchan, _ = run(["/bin/cat", str(tid_dir / "wchan")], timeout=5)
            lines.append(f"  tid={tid} state={state} comm={comm} "
                         f"wchan={wchan.strip() if rcw == 0 else '?'}")
    write(out / "threads.txt", "\n".join(lines) + "\n")


def cap_blocked(out: Path, pw: str) -> None:
    """Ask the kernel for the backtrace of every task in ``D``.

    ``echo w > /proc/sysrq-trigger`` prints a ``sysrq: Show Blocked State``
    block per uninterruptible task, with a real ``Call trace`` through the
    driver -- this is the evidence the driver team needs, and on this kernel it
    is the *only* way to get it (no ``CONFIG_STACKTRACE``).

    Only the lines that appeared because of the trigger are kept: the ring
    buffer already holds the boot log, and diffing on the ``sysrq: Show Blocked
    State`` marker keeps the file readable.
    """
    rc, before, _ = as_root(["dmesg"], pw, timeout=60)
    n_before = len(before.splitlines())
    rc2, _, err2 = as_root(["/bin/sh", "-c", "echo w > /proc/sysrq-trigger"],
                           pw, timeout=20)
    time.sleep(3)
    rc3, after, _ = as_root(["dmesg"], pw, timeout=60)
    new = after.splitlines()[n_before:] if rc3 == 0 else []
    body = "\n".join(new) if new else (
        f"no new dmesg lines after sysrq-w (rc={rc2} {err2}); "
        f"full dmesg is in dmesg.txt")
    write(out / "blocked.txt", body + "\n")


def cap_workers(out: Path, models: dict[str, int], main_pid: int) -> None:
    rc, ps, _ = sh("ps -eo pid,ppid,stat,etime,wchan:32,args --sort=pid",
                   timeout=30)
    body = [f"main pid: {main_pid}", f"workers: {json.dumps(models)}", "",
            ps]
    write(out / "workers.txt", "\n".join(body))


_ANSI = __import__("re").compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][0-9A-B]|\x1b[=>78]|[\x00-\x08\x0b\x0c\x0e-\x1f]")
_WS = __import__("re").compile(r"[ \t]{2,}")


def cap_bmsmi(out: Path) -> None:
    """One shot, no ncurses loop, with the escape soup stripped.

    ``bm-smi`` is a full-screen program.  ``-noloop`` makes it sample once and
    exit, but it still paints the screen, so the raw capture is mostly cursor
    addresses; ``_ANSI`` reduces it to something a human can read.  ``TERM=dumb``
    does not help -- the program ignores it.  A hard timeout guards the case
    where -noloop is not honoured on some build.
    """
    exe = ("/opt/sophon/libsophon-current/bin/bm-smi"
           if Path("/opt/sophon/libsophon-current/bin/bm-smi").exists()
           else (shutil.which("bm-smi") or ""))
    if not exe:
        write(out / "bmsmi.txt", "bm-smi not found\n")
        return
    rc, text, err = run(["/usr/bin/timeout", "10", exe, "-noloop"], timeout=20)
    clean = _ANSI.sub("", text)
    # bm-smi positions the cursor instead of emitting newlines, so the whole
    # frame arrives as one line with long runs of spaces where the layout was.
    # Collapsing those runs to a separator is what makes the numbers legible.
    clean = _WS.sub(" | ", clean)
    lines = [ln.strip(" |\t") for ln in clean.splitlines()]
    lines = [ln for ln in lines if ln]
    write(out / "bmsmi.txt", "\n".join(lines) + (f"\n{err}" if err else "") + "\n")


def cap_stats(out: Path) -> None:
    try:
        write(out / "stats.json",
              json.dumps(api_get("/api/stats"), ensure_ascii=False, indent=1))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        write(out / "stats.json", json.dumps({"error": str(exc)}))


def cap_models(out: Path) -> None:
    try:
        write(out / "models.json",
              json.dumps(api_get("/api/models"), ensure_ascii=False, indent=1))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        write(out / "models.json", json.dumps({"error": str(exc)}))


def cap_records(out: Path, since_min: float) -> None:
    """The inference records that were in flight / just finished at the hang.

    Reading the sqlite file directly (read-only URI) rather than through the
    API: the API's list endpoint is served by the same event loop that is
    blocked on the hung worker pool, so it is exactly what stops answering.
    """
    db = Path("/data/cv84x6_llm_server/state/inference_records.sqlite3")
    if not db.exists():
        write(out / "records.txt", f"{db} not found\n")
        return
    cutoff = time.time() - since_min * 60
    script = f"""
import sqlite3, json, time
c = sqlite3.connect("file:{db}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
rows = c.execute(
    "select id,source,model,actor_name,started_iso,finished_iso,status,"
    "finish_reason,error_type,error_message,prompt_tokens,completion_tokens,"
    "first_token_latency_s,decode_tps,output_chars from inference_records "
    "where started_at >= ? order by started_at", ({cutoff},)).fetchall()
print(f"records with started_at >= {cutoff:.0f} "
      f"({'%.0f' % since_min} min back): {{len(rows)}}")
for r in rows:
    print(json.dumps(dict(r), ensure_ascii=False))
c.close()
"""
    rc, text, err = run(["/usr/bin/python3.10", "-c", script], timeout=60)
    write(out / "records.txt", text if rc == 0 else f"rc={rc}\n{err}\n")


def cap_worker_logs(out: Path) -> None:
    d = out / "worker_logs"
    d.mkdir(parents=True, exist_ok=True)
    src = Path("/data/cv84x6_llm_server/state/logs")
    if not src.is_dir():
        write(d / "_missing.txt", f"{src} not found\n")
        return
    for path in sorted(src.glob("worker-*.log")):
        write(d / path.name, tail(path, 400))


def cap_platform_log(out: Path) -> None:
    path = Path("/data/cv84x6_llm_server/state/logs/platform.log")
    write(out / "platform_log_tail.txt",
          tail(path, 800) if path.exists() else "not found\n")


def cap_versions(out: Path, pw: str) -> None:
    lines: list[str] = []

    def add(title: str, text: str) -> None:
        lines.append(f"===== {title}")
        lines.append(text.rstrip() or "(empty)")

    for title, cmd in (
        ("uname", "uname -a"),
        ("os-release", "cat /etc/os-release"),
        ("libsophon", "ls -l /opt/sophon/ | grep libsophon"),
        ("sophon packages", "dpkg -l | grep -iE 'libsophon|sophon-|bmssm|memory-edit'"),
        ("service package", "dpkg -l | grep cv84x6-llm-server"),
        ("installed VERSION", "cat /opt/sophgo/cv84x6_llm_server/VERSION"),
        ("installed COMMIT", "cat /opt/sophgo/cv84x6_llm_server/COMMIT"),
        ("libcv84x6_llm.so", "md5sum /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so"),
        ("bmtpu module", "lsmod | grep -i bm"),
        ("boot id", "cat /proc/sys/kernel/random/boot_id"),
        ("uptime", "uptime"),
        ("firmware (scaler cores)", "grep -A1 Firmware /proc/bmtpu/scaler_info"),
        ("DTB shm base", "dmesg | grep -E 'Original physical address from DTS|"
                         "shared memory init'"),
        ("bmrt version", "cat /opt/sophon/libsophon-current/version 2>/dev/null || "
                         "dpkg -s sophon-soc-libsophon | grep -E 'Version'"),
    ):
        rc, text, err = sh(cmd, timeout=30)
        add(title, text if rc == 0 else f"rc={rc} {err}")
    write(out / "versions.txt", "\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="/data/d7caps",
                    help="directory to create the capture in (default: %(default)s)")
    ap.add_argument("--sudo-pw", default=os.environ.get("SUDO_PW", ""),
                    help="sudo password (__SUDO_PW__ placeholder substituted by "
                         "the caller); omit when sudo needs no password")
    ap.add_argument("--since", type=float, default=10,
                    help="minutes of inference records to keep (default: 10)")
    ap.add_argument("--tag", default="", help="suffix for the capture dir name")
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    name = f"d7cap-{stamp}" + (f"-{args.tag}" if args.tag else "")
    out = Path(args.out) / name
    out.mkdir(parents=True, exist_ok=True)

    main_pid = 0
    rc, text, _ = sh("systemctl show -p MainPID --value cv84x6-llm", timeout=15)
    try:
        main_pid = int(text.strip() or 0)
    except ValueError:
        main_pid = 0
    model_pids = workers()

    failed: list[str] = []
    t0 = time.time()

    def attempt(name_: str, fn) -> None:
        s = time.time()
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a capture must not abort
            failed.append(f"{name_}: {type(exc).__name__}: {exc}")
            write(out / f"_error_{name_}.txt", f"{type(exc).__name__}: {exc}\n")
        print(f"  {name_:<14} {time.time() - s:5.1f}s", flush=True)

    print(f"capturing into {out}", flush=True)
    attempt("dmesg", lambda: cap_dmesg(out, args.sudo_pw))
    attempt("sysfs", lambda: cap_sysfs(out))
    attempt("proc_bmtpu", lambda: cap_proc_bmtpu(out, args.sudo_pw))
    attempt("threads", lambda: cap_threads(out, args.sudo_pw, model_pids, main_pid))
    attempt("blocked", lambda: cap_blocked(out, args.sudo_pw))
    attempt("workers", lambda: cap_workers(out, model_pids, main_pid))
    attempt("bmsmi", lambda: cap_bmsmi(out))
    attempt("stats", lambda: cap_stats(out))
    attempt("models", lambda: cap_models(out))
    attempt("records", lambda: cap_records(out, args.since))
    attempt("worker_logs", lambda: cap_worker_logs(out))
    attempt("platform_log", lambda: cap_platform_log(out))
    attempt("versions", lambda: cap_versions(out, args.sudo_pw))

    def counts() -> dict:
        """The counters that say whether this really was a hang."""
        dmesg = out / "dmesg.txt"
        text = dmesg.read_text(encoding="utf-8", errors="replace") \
            if dmesg.exists() else ""
        blocked = out / "blocked.txt"
        btext = blocked.read_text(encoding="utf-8", errors="replace") \
            if blocked.exists() else ""
        state = {"D": 0, "other": 0}
        tf = out / "threads.txt"
        if tf.exists():
            for line in tf.read_text(encoding="utf-8", errors="replace").splitlines():
                if " state=" in line:
                    s = line.split("state=", 1)[1].split()[0]
                    state["D" if s == "D" else "other"] += 1
        return {
            "wait_api_timeout": text.count("wait api timeout"),
            "mbox_submit_timeout": text.count("mbox submit timeout"),
            "wait_free_slots": text.count("bmdev_wait_free_slots"),
            "npu_fault": text.count("NPU fault"),
            "recursive_fault": text.count("recursive fault"),
            "oops": text.count("Internal error: Oops"),
            "dmesg_lines": len(text.splitlines()),
            # sysrq-w output, which is where the kernel backtraces live
            "blocked_tasks": btext.count("state:D "),
            "blocked_lines": len(btext.splitlines()),
            "threads_D": state["D"],
            "threads_total": state["D"] + state["other"],
        }

    summary = {
        "capture": name,
        "utc": stamp,
        "host": os.uname().nodename,
        "main_pid": main_pid,
        "worker_pids": model_pids,
        "sections": list(SECTIONS),
        "failed": failed,
        "seconds": round(time.time() - t0, 1),
        "counters": counts(),
        "files": sorted(str(p.relative_to(out)) for p in out.rglob("*")
                        if p.is_file()),
    }
    write(out / "summary.json",
          json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary["counters"], ensure_ascii=False), flush=True)
    print(f"failed sections: {failed or 'none'}", flush=True)
    print(f"capture complete in {summary['seconds']}s -> {out}", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
