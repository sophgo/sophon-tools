"""D7 driver: run the experiment segments on the board one after another, over SSH.

The board is a scarce, single-tenant resource during this task, and every
segment can end in a wedged TPU that only a reboot clears.  So the driver owns
the whole cycle instead of a human:

    reboot  ->  wait for :8000  ->  start d7_experiment.py under nohup
            ->  poll for DONE   ->  copy the result dir back
            ->  if the segment hung, capture the pre-reboot evidence and reboot
            ->  next segment

It is deliberately a *foreground* loop.  Each step blocks; there is no queue and
no background job, because a run that outlives this process is a run whose
result is lost.

Usage (13.24):

    E2E_SUDO_PW=... python3 tools/e2e/d7_drive.py --plan plan.json

``plan.json`` is a list of segments::

    [{"run": "R1", "minutes": 25, "models": "chat,embed,rerank,asr,ocr,vl",
      "load": "chat:2,embed:1,rerank:1,ocr:1,vl:1,asr:1", "pre": ""},
     ...]

State lives in ``<out>/driver.json`` so an interrupted driver picks up where it
stopped instead of replaying finished segments.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Everything ssh may print about the host key, from the banner beginning to the
# end of its sentence, so what was glued to it survives.
_BANNER = re.compile(
    r"Warning: Permanently added '[^']*'(?: \([^)]*\))? to the list of known"
    r" hosts\.\s*|Connection to [\w.\-]+ closed\.\s*")
DEFAULT_BOARD_SH = os.environ.get(
    "E2E_BOARD_SH", "/home/zzt/workspace/cv84x6-demo-run/s155n.sh")
BOARD_DIR = "/data/mys2693/d7rt"
HANG_RC = 2  # d7_experiment.py exits 2 when it captured a hang


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Driver:
    def __init__(self, args) -> None:
        self.args = args
        self.out = Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.sh = args.board_sh
        self.pw = args.sudo_pw
        self.state_path = self.out / "driver.json"
        self.state = (json.loads(self.state_path.read_text())
                      if self.state_path.exists() else {"segments": {}})

    # -- board plumbing ---------------------------------------------------- #
    def board(self, cmd: str, timeout: float = 300) -> str:
        cmd = cmd.replace("__SUDO_PW__", self.pw)
        p = subprocess.run([self.sh, cmd], capture_output=True, text=True,
                           timeout=timeout)
        raw = p.stdout + p.stderr
        # ssh writes its "Permanently added ..." banner to stderr *without* a
        # trailing newline, so when stdout does not end in one either, the two
        # end up glued onto a single line: ``{"ok":true}Warning: Permanently
        # added ...``.  Splitting on "known hosts." and keeping the last part
        # (the obvious fix) throws away the payload; dropping whole lines
        # (the other obvious fix) throws away the whole answer.  Remove just the
        # banner text and leave whatever it was glued to.
        raw = _BANNER.sub("", raw)
        return raw.strip()

    def scp_up(self, local: Path, remote: str) -> None:
        p = subprocess.run([self.sh, "scp", str(local), f"linaro@172.26.166.96:{remote}"],
                           capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            raise RuntimeError(f"scp up {local} failed: {p.stderr[-300:]}")

    def scp_down(self, remote: str, local: str) -> bool:
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        p = subprocess.run([self.sh, "scp", "-r", f"linaro@172.26.166.96:{remote}",
                            local], capture_output=True, text=True, timeout=900)
        return p.returncode == 0

    # -- lifecycle --------------------------------------------------------- #
    def boot_id(self) -> str:
        """The kernel's boot id, or "" when the board is not answering yet.

        Parsed strictly: during the reboot the SSH banner and the timeout text
        can land in the same response, and a loose ``set(...)`` would happily
        return the string "ssh: con" as a new boot id.
        """
        out = self.board("cat /proc/sys/kernel/random/boot_id", timeout=60)
        for line in out.splitlines():
            line = line.strip()
            # boot_id is a 36-char UUID; anything else is ssh noise
            if len(line) == 36 and line.count("-") == 4:
                return line
        return ""

    def reboot(self) -> bool:
        """Force-reboot, the only thing that clears a wedged TPU on this chip.

        ``systemctl reboot --force --force`` also evicts the D-state threads
        that a plain ``reboot`` waits on; a plain reboot returning without the
        boot_id changing is the failure mode this avoids.
        """
        before = self.boot_id()
        log(f"reboot (boot_id before {before[:8]})")
        # The connection drops the moment the kernel goes down, so a non-zero
        # ssh exit here is expected, not an error -- boot_id below decides.
        try:
            self.board("echo __SUDO_PW__ | sudo -S systemctl reboot --force "
                       "--force", timeout=60)
        except subprocess.TimeoutExpired:
            pass
        deadline = time.time() + self.args.reboot_timeout
        while time.time() < deadline:
            time.sleep(10)
            try:
                after = self.boot_id()
            except subprocess.TimeoutExpired:
                continue
            if after and after != before:
                # Different boot id: the kernel really went down and came back.
                # (Waiting to *observe* the down window first does not work --
                # sshpass keeps answering across it on this network, so the one
                # signal available is the id changing.)
                log(f"boot_id now {after[:8]}")
                return self._wait_service()
        log("!! boot_id never changed; board may still be wedged")
        return False

    def _wait_service(self) -> bool:
        """Wait until :8000 answers -- a boot id alone does not mean usable."""
        deadline = time.time() + self.args.boot_timeout
        while time.time() < deadline:
            out = self.board("curl -s -m 5 http://127.0.0.1:8000/healthz",
                             timeout=60)
            if '"ok":true' in out:
                log(f"service back: {out.strip()}")
                return True
            time.sleep(10)
        log("!! service did not come back")
        return False

    def prep(self, admin_key: str) -> None:
        """Push the two scripts and the key file to the board."""
        self.board(f"mkdir -p {BOARD_DIR} /data/mys2693/runs", timeout=60)
        for name in ("d7_experiment.py", "d7_capture.py"):
            self.scp_up(HERE / name, f"{BOARD_DIR}/{name}")
        # The admin key goes to a 0600 file, never into a result.
        Path("/tmp/d7_adminkey").write_text(admin_key + "\n")
        self.scp_up(Path("/tmp/d7_adminkey"), f"{BOARD_DIR}/adminkey")
        Path("/tmp/d7_adminkey").unlink(missing_ok=True)
        self.board(f"chmod 600 {BOARD_DIR}/adminkey; "
                   f"python3.10 -m py_compile {BOARD_DIR}/d7_experiment.py "
                   f"{BOARD_DIR}/d7_capture.py && echo COMPILE_OK", timeout=120)

    # -- one segment ------------------------------------------------------- #
    def run_segment(self, seg: dict) -> dict:
        run = seg["run"]
        done = self.state["segments"].get(run, {})
        if done.get("status") in ("ok", "hang") and not self.args.force:
            log(f"{run}: already {done['status']}, skipping (use --force to redo)")
            return done

        # Start from a clean boot: the previous segment may have left the TPU
        # wedged, and a segment that starts on a dirty device proves nothing.
        if not self.reboot():
            self.state["segments"][run] = {"status": "boot_failed"}
            self.save()
            return self.state["segments"][run]

        remote_out = "/data/mys2693/runs"
        self.board(f"rm -rf {remote_out}/{run}", timeout=60)
        # Started through an on-board wrapper script, not as a long command
        # line: the wrapper sets everything up and then execs the runner with
        # all three streams detached.  Without the redirect-and-close the ssh
        # session waits for the *grandchild's* stdout to close and the start
        # call blocks until the whole segment is over.
        self.board(
            f"mkdir -p {BOARD_DIR} && cat > {BOARD_DIR}/start_{run}.sh <<'EOS'\n"
            f"#!/bin/sh\n"
            f"cd {BOARD_DIR} || exit 1\n"
            f"export D7_ADMIN_KEY=\"$(cat {BOARD_DIR}/adminkey)\"\n"
            f"export PYTHONPATH=/opt/sophgo/cv84x6_llm_server/vendor\n"
            f"exec python3.10 d7_experiment.py --run {run} --out {remote_out} "
            f"--minutes {seg['minutes']} --models {seg['models']} "
            f"--load {seg['load']} --pre '{seg.get('pre', '')}' "
            f"--stall-s {seg.get('stall_s', 150)}\n"
            f"EOS\n"
            f"chmod +x {BOARD_DIR}/start_{run}.sh", timeout=120)
        log(f"{run}: starting ({seg['minutes']} min, models={seg['models']}, "
            f"load={seg['load']}, pre={seg.get('pre') or '-'})")
        self.board(f"setsid nohup {BOARD_DIR}/start_{run}.sh "
                   f"< /dev/null >> {remote_out}/{run}.log 2>&1 & "
                   f"echo STARTED $!", timeout=120)

        # Poll for the sentinel.  The extra budget covers load time and the
        # final probe; a run that never writes DONE is a failure of its own.
        deadline = time.time() + seg["minutes"] * 60 + self.args.grace
        status = "timeout"
        while time.time() < deadline:
            time.sleep(self.args.poll)
            out = self.board(
                f"test -f {remote_out}/{run}/DONE && cat {remote_out}/{run}/DONE "
                f"|| echo PENDING", timeout=120)
            if out.strip() in ("True", "False"):
                status = "hang" if out.strip() == "True" else "ok"
                break
            if not out.strip():
                continue
        log(f"{run}: {status}")

        # Pull everything back before touching the board again.
        local = self.out / run
        if local.exists():
            import shutil
            shutil.rmtree(local)
        # `scp -r remote:dir <parent>/` lands the directory *as* <parent>/dir,
        # which is what we want; passing the final path instead would nest it.
        if not self.scp_down(f"{remote_out}/{run}", str(self.out) + "/"):
            log(f"{run}: !! could not copy results back")
        local.mkdir(parents=True, exist_ok=True)
        if not self.scp_down(f"{remote_out}/{run}.log", str(local / "run.log")):
            log(f"{run}: !! could not copy the run log")

        result = {}
        rp = local / "result.json"
        if rp.exists():
            result = json.loads(rp.read_text())
        summary = {
            "status": status,
            "hang": result.get("hang", {}),
            "n_requests": result.get("n_requests"),
            "n_ok": result.get("n_ok"),
            "outcomes": result.get("outcomes"),
            "duration_s": result.get("duration_s"),
            "heaps_before": result.get("heaps_before"),
            "heaps_after": result.get("heaps_after"),
            "dmesg_before": result.get("dmesg_before"),
            "dmesg_after": result.get("dmesg_after"),
            "probe_before": result.get("probe_before"),
            "probe_after": result.get("probe_after"),
            "pre_ops": result.get("pre_ops"),
            "captures": [c.get("tag") for c in result.get("captures", [])],
            "config": result.get("config"),
        }
        self.state["segments"][run] = summary
        self.save()
        return summary

    def save(self) -> None:
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False,
                                              indent=1))

    # -- main -------------------------------------------------------------- #
    def run(self) -> int:
        plan = json.loads(Path(self.args.plan).read_text())
        if self.args.only:
            want = {s.strip() for s in self.args.only.split(",")}
            plan = [s for s in plan if s["run"] in want]
        key = os.environ.get("D7_ADMIN_KEY", "")
        if not key:
            raise SystemExit("set D7_ADMIN_KEY")
        self.prep(key)
        for seg in plan:
            try:
                s = self.run_segment(seg)
            except subprocess.TimeoutExpired as exc:
                log(f"{seg['run']}: ssh timeout: {exc}")
                self.state["segments"][seg["run"]] = {"status": "ssh_timeout"}
                self.save()
                continue
            log(f"{seg['run']}: {json.dumps({k: s.get(k) for k in ('status', 'n_requests', 'n_ok', 'duration_s')}, ensure_ascii=False)}")
        # Leave the board clean: reboot after the last segment if it hung.
        last = plan[-1]["run"] if plan else None
        if last and self.state["segments"].get(last, {}).get("status") == "hang":
            self.reboot()
        log("driver done: " + json.dumps(
            {k: v.get("status") for k, v in self.state["segments"].items()},
            ensure_ascii=False))
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", default="/home/zzt/workspace/cv84x6-e2e/d7runs")
    ap.add_argument("--only", default="", help="comma separated run ids to run")
    ap.add_argument("--force", action="store_true", help="redo finished segments")
    ap.add_argument("--board-sh", default=DEFAULT_BOARD_SH)
    ap.add_argument("--sudo-pw", default=os.environ.get("E2E_SUDO_PW", ""))
    ap.add_argument("--reboot-timeout", type=float, default=420)
    ap.add_argument("--boot-timeout", type=float, default=420)
    ap.add_argument("--grace", type=float, default=900,
                    help="seconds past the nominal duration before a run is "
                         "called a timeout (covers loading and the last probe)")
    ap.add_argument("--poll", type=float, default=30)
    args = ap.parse_args()
    if not args.sudo_pw:
        raise SystemExit("set E2E_SUDO_PW (the board's sudo password)")
    return Driver(args).run()


if __name__ == "__main__":
    sys.exit(main())
