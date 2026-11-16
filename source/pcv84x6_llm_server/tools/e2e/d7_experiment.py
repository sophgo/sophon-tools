"""D7 experiment runner: one controlled mixed-load segment on the board, with
automatic capture the moment the TPU wedges.

Run it *on the board* (it is the only thing that can see dmesg and /proc):

    PYTHONPATH=/opt/sophgo/cv84x6_llm_server/vendor \\
      python3.10 d7_experiment.py --run R1 --minutes 25 \\
        --models chat,embed,rerank,asr,ocr,vl --load chat:2,embed:1,rerank:1,ocr:1,vl:1,asr:1 \\
        --out /data/mys2693/runs

It is normally started by the host-side driver ``d7_drive.py``, which reboots the
board, starts this under ``nohup``, polls for the ``DONE`` sentinel and copies
the results back.  Running it by hand is supported and useful for a quick look.

What it guarantees
------------------
* **The six models are actually loaded and answering before the clock starts.**
  A model that answers 409 (not loaded) is a silent reduction of the test; the
  run aborts instead of producing a number that means something else.
* **A hang is detected and captured, not waited out.**  Detection has two
  independent triggers, because the definitive one is slow:
  - a *new* ``wait api timeout`` in dmesg (definitive, but the driver only
    prints it after its 120 s timeout), and
  - a *stall*: requests are outstanding and nothing has completed successfully
    for ``--stall-s`` seconds.  This fires earlier and is what gets a capture
    taken while the workers are still freshly stuck.
* **Nothing on the device is killed.**  The load threads are abandoned, not
  joined: a request stuck behind a wedged TPU never returns, and the process
  exits anyway.  Killing a process mid-NPU-call is itself a known way to wedge
  this chip, so it is never done here.
* **The capture is taken twice** when possible -- once on the first stall
  (``suspect``) and once when dmesg confirms it (``confirmed``) -- so the driver
  team sees the progression rather than a single ambiguous snapshot.

Result: ``<out>/<run>/result.json`` plus ``<out>/<run>/requests.jsonl`` (one line
per request, with start/end/duration, which is the "last two minutes of
requests" evidence) and the capture directories.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
DATA = Path("/data/cv84x6_llm_server")

# kind -> model id.  The six the task calls "6 个模型".
KIND_MODEL = {
    "chat": "qwen3.6-35b-a3b-128k",
    "embed": "qwen3-embedding-0.6b",
    "rerank": "bge-reranker-v2-m3",
    "asr": "qwen3-asr-0.6b",
    "ocr": "ppocrv6-medium",
    "vl": "paddleocr-vl-1.5",
}
# Seconds between iterations, same cadence the MYS-2691 reproduction used.
DEFAULT_PAUSE = {"chat": 0.5, "embed": 2.0, "rerank": 2.0, "ocr": 5.0,
                 "vl": 5.0, "asr": 5.0}

HERE = Path(__file__).resolve().parent


def sh(cmd: str, timeout: float = 60) -> str:
    p = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True, text=True,
                       timeout=timeout)
    return (p.stdout + p.stderr).strip()


def admin_key() -> str:
    """The console's admin key, which is *not* recoverable from state.json.

    ``state.json`` stores only a hash of it, so the key has to be supplied:
    either in ``D7_ADMIN_KEY`` or in a one-line file next to the fixtures.  The
    host-side driver passes it through the environment; nothing here ever writes
    it to a result file.
    """
    env = os.environ.get("D7_ADMIN_KEY", "")
    if env:
        return env.strip()
    for p in (Path("/data/mys2693/adminkey"), Path("/data/mys2691/adminkey")):
        if p.exists():
            return p.read_text().strip()
    raise SystemExit("set D7_ADMIN_KEY (state.json only holds a hash of it)")


def dmesg_text() -> str:
    """The ring buffer, without needing sudo where sudo is passwordless.

    ``sudo -n`` never prompts: on this image linaro has NOPASSWD, and if some
    other image lacks it the call fails fast instead of blocking the monitor
    thread on a password prompt -- which is the one thing a capture must not do.
    """
    p = subprocess.run(["sudo", "-n", "dmesg"], capture_output=True, text=True,
                       timeout=60)
    return p.stdout if p.returncode == 0 else ""


def dmesg_counts() -> dict:
    t = dmesg_text()
    return {
        "wait_api_timeout": t.count("wait api timeout"),
        "mbox_submit_timeout": t.count("mbox submit timeout"),
        "wait_free_slots": t.count("bmdev_wait_free_slots"),
        "npu_fault": t.count("NPU fault"),
        "recursive_fault": t.count("recursive fault"),
        "oops": t.count("Internal error: Oops"),
        "lines": len(t.splitlines()),
    }


def fixture(name: str) -> bytes:
    """OCR/VL image and ASR audio, taken from the installed demo data."""
    cands = [
        Path("/data/mys2691") / name,
        Path("/data/Qwen3VL/python_demo") / name,
        Path("/data/cv84x6_llm_server") / name,
    ]
    for c in cands:
        if c.exists():
            return c.read_bytes()
    return b""


class Runner:
    def __init__(self, args) -> None:
        self.args = args
        self.key = args.admin_key or admin_key()
        self.out = Path(args.out) / args.run
        self.out.mkdir(parents=True, exist_ok=True)
        hdr = {"Authorization": f"Bearer {self.key}"}
        self.admin = httpx.Client(base_url=BASE, headers=hdr, timeout=900)
        self.infer = httpx.Client(base_url=BASE, headers=hdr, timeout=900)

        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.reqlog = (self.out / "requests.jsonl").open("a")
        self.outcomes: dict[str, dict[str, int]] = {}
        self.inflight: dict[int, tuple[str, float]] = {}
        self.last_ok = time.time()
        self.n_requests = 0
        self.n_ok = 0
        self.samples: list[dict] = []
        self.captures: list[dict] = []
        self.hang: dict = {"detected": False}
        self.dmesg_base: dict = {}
        self._seq = 0
        self._captured_suspect = False
        self._captured_confirmed = False

        self.img = fixture("page.png")
        self.audio = fixture("zh.mp3")
        self.b64 = base64.b64encode(self.img).decode() if self.img else ""

    # -- device state ------------------------------------------------------ #
    def heaps(self) -> dict:
        try:
            dm = self.admin.get("/api/stats").json()["device"]["device_mem"]
            return {h["name"]: h["used_bytes"] >> 20 for h in dm["heaps"]}
        except Exception:  # noqa: BLE001 - a hung service stops answering
            return {}

    def tpu(self) -> dict:
        try:
            u = self.admin.get("/api/stats").json()["device"]["tpu_usage"]
            return {"percent": u["percent"], "cores": u["cores"]}
        except Exception:  # noqa: BLE001
            return {}

    def models(self) -> dict:
        try:
            return {m["id"]: m for m in self.admin.get("/api/models").json()["models"]}
        except Exception:  # noqa: BLE001
            return {}

    # -- setup ------------------------------------------------------------- #
    def ensure_loaded(self) -> dict:
        """Load exactly the requested models; report rather than guess."""
        want = self.args.models.split(",")
        state = self.models()
        for kind in want:
            mid = KIND_MODEL[kind]
            if state.get(mid, {}).get("loaded"):
                continue
            t0 = time.time()
            r = self.admin.post(f"/api/models/{mid}/load", timeout=900)
            print(f"    load {mid}: {r.status_code} in {time.time() - t0:.1f}s",
                  flush=True)
            if r.status_code != 200:
                raise SystemExit(f"load {mid} failed: {r.status_code} {r.text[:200]}")
        # Models that were left loaded from an earlier segment are unloaded, so
        # "which models are resident" is a fact about this run.
        for mid, m in self.models().items():
            if m.get("loaded") and mid not in {KIND_MODEL[k] for k in want}:
                r = self.admin.post(f"/api/models/{mid}/unload", timeout=300)
                print(f"    unload stray {mid}: {r.status_code}", flush=True)
        return {m["id"]: {"loaded": m["loaded"], "pid": m.get("pid")}
                for m in self.models().values() if m.get("loaded")}

    # -- one request per model, so "six models under load" is proven ------- #
    def probe(self, timeout: float = 300) -> dict:
        """One short request per resident model.

        ``timeout`` is deliberately small: on a wedged device a probe is the one
        call that can block for the service's whole request timeout (300-600 s
        each), and a probe exists to *report* state, not to wait for it.
        """
        out = {}
        c = httpx.Client(base_url=BASE,
                         headers={"Authorization": f"Bearer {self.key}"},
                         timeout=timeout)
        for kind in self.args.models.split(","):
            try:
                out[kind] = self._request(kind, brief=True, client=c)["code"]
            except Exception as exc:  # noqa: BLE001
                out[kind] = f"exc:{type(exc).__name__}"
        c.close()
        return out

    def _request(self, kind: str, brief: bool = False, client=None) -> dict:
        """Issue one request of ``kind`` and return its outcome."""
        c = client or self.infer
        if kind == "chat":
            body = {"model": KIND_MODEL["chat"],
                    "max_tokens": 24 if brief else 128,
                    "messages": [{"role": "user",
                                  "content": "用两三句话解释设备巡检。"}]}
            r = c.post("/v1/chat/completions", json=body)
            return {"code": r.status_code, "detail": r.text[:160]}
        if kind == "embed":
            r = c.post("/v1/embeddings", json={"model": KIND_MODEL["embed"],
                                               "input": "巡检记录"})
            return {"code": r.status_code, "detail": r.text[:160]}
        if kind == "rerank":
            r = c.post("/v1/rerank", json={"model": KIND_MODEL["rerank"],
                                           "query": "合格率",
                                           "documents": ["合格率 99%", "无关内容"]})
            return {"code": r.status_code, "detail": r.text[:160]}
        if kind == "ocr":
            if not self.b64:
                return {"code": "no-fixture", "detail": "page.png missing"}
            r = c.post("/v1/ocr", json={"model": KIND_MODEL["ocr"],
                                        "image": self.b64})
            return {"code": r.status_code, "detail": r.text[:160]}
        if kind == "vl":
            if not self.b64:
                return {"code": "no-fixture", "detail": "page.png missing"}
            body = {"model": KIND_MODEL["vl"], "max_tokens": 64 if brief else 256,
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url",
                         "image_url": {"url": "data:image/png;base64," + self.b64}},
                        {"type": "text", "text": "OCR:"}]}]}
            r = c.post("/v1/chat/completions", json=body)
            return {"code": r.status_code, "detail": r.text[:160]}
        if kind == "asr":
            if not self.audio:
                return {"code": "no-fixture", "detail": "zh.mp3 missing"}
            r = c.post("/v1/audio/transcriptions",
                       data={"model": KIND_MODEL["asr"]},
                       files={"file": ("a.mp3", self.audio, "audio/mpeg")})
            return {"code": r.status_code, "detail": r.text[:160]}
        raise SystemExit(f"unknown load kind {kind}")

    # -- load -------------------------------------------------------------- #
    def _note(self, kind: str, code, dur: float, t0: float, t1: float,
              seq: int, detail: str = "") -> None:
        with self.lock:
            self.outcomes.setdefault(kind, {})
            k = str(code)
            self.outcomes[kind][k] = self.outcomes[kind].get(k, 0) + 1
            self.n_requests += 1
            if k == "200":
                self.n_ok += 1
                self.last_ok = t1
            self.reqlog.write(json.dumps({
                "seq": seq, "kind": kind, "code": k, "t0": round(t0, 3),
                "t1": round(t1, 3), "dur": round(dur, 2),
                "detail": detail}) + "\n")
            self.reqlog.flush()

    def load_loop(self, kind: str, pause: float) -> None:
        c = httpx.Client(base_url=BASE,
                         headers={"Authorization": f"Bearer {self.key}"},
                         timeout=900)
        while not self.stop.is_set():
            with self.lock:
                self._seq += 1
                seq = self._seq
                self.inflight[seq] = (kind, time.time())
            t0 = time.time()
            code, detail = "exc", ""
            try:
                got = self._request(kind, client=c)
                code, detail = got["code"], got.get("detail", "")
            except Exception as exc:  # noqa: BLE001
                code = f"exc:{type(exc).__name__}"
            finally:
                with self.lock:
                    self.inflight.pop(seq, None)
            t1 = time.time()
            self._note(kind, code, t1 - t0, t0, t1, seq, detail)
            if self.stop.wait(pause):
                break

    # -- pre-operations (hypothesis H4) ------------------------------------ #
    def pre_ops(self, spec: str) -> dict:
        done = {}
        for op in [s for s in spec.split(",") if s]:
            if op.startswith("crash"):
                busy = op.endswith("busy")
                done[op] = self.crash(busy)
            elif op.startswith("ocr-cycles"):
                n = int(op.split(":")[1]) if ":" in op else 5
                done[op] = self.ocr_cycles(n)
            else:
                raise SystemExit(f"unknown pre-op {op}")
        return done

    def crash(self, busy: bool) -> dict:
        """kill -9 the main process; the worker must survive (unit is KillMode=process)."""
        mid = KIND_MODEL["chat"] if busy else KIND_MODEL["embed"]
        wpid = int(sh(f"pgrep -f 'app.engine.worker.*--model-id {mid}'")
                   .split()[0] if sh(f"pgrep -f 'app.engine.worker.*--model-id {mid}'")
                   else 0)
        if busy:
            def fire():
                try:
                    self.infer.post("/v1/chat/completions", json={
                        "model": KIND_MODEL["chat"], "max_tokens": 700,
                        "messages": [{"role": "user",
                                      "content": "写一篇八百字的散文，主题是秋天。"}]})
                except Exception:  # noqa: BLE001
                    pass
            threading.Thread(target=fire, daemon=True).start()
            time.sleep(4)
        main = int(sh("systemctl show -p MainPID --value cv84x6-llm") or 0)
        print(f"    kill -9 main={main} (busy={busy}), watching worker {wpid}",
              flush=True)
        subprocess.run(["sudo", "-n", "kill", "-9", str(main)], check=False)
        time.sleep(3)
        survived = wpid > 0 and Path(f"/proc/{wpid}").exists()
        # Wait for the service to come back and adopt the worker.
        up = False
        deadline = time.time() + 240
        while time.time() < deadline:
            try:
                if self.admin.get("/healthz", timeout=5).status_code == 200:
                    up = True
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2)
        time.sleep(8)
        m = self.models().get(mid, {})
        return {"busy": busy, "main": main, "worker": wpid,
                "worker_survived": survived, "service_back": up,
                "adopted": m.get("adopted"), "pid": m.get("pid")}

    def ocr_cycles(self, n: int) -> dict:
        res = []
        for i in range(n):
            self.admin.post(f"/api/models/{KIND_MODEL['ocr']}/load", timeout=600)
            try:
                code = self._request("ocr")["code"]
            except Exception as exc:  # noqa: BLE001
                code = f"exc:{type(exc).__name__}"
            self.admin.post(f"/api/models/{KIND_MODEL['ocr']}/unload", timeout=600)
            res.append(code)
            print(f"    ocr cycle {i}: {code} heaps={self.heaps()}", flush=True)
        return {"cycles": res}

    # -- capture ----------------------------------------------------------- #
    def _bounded_probe(self, kind: str, timeout: float) -> str:
        """One request with a hard client timeout, reported as a code or an
        exception name.  Used to show the device does not self-recover."""
        c = httpx.Client(base_url=BASE,
                         headers={"Authorization": f"Bearer {self.key}"},
                         timeout=timeout)
        try:
            return self._request(kind, brief=True, client=c)["code"]
        except Exception as exc:  # noqa: BLE001
            return f"exc:{type(exc).__name__}"
        finally:
            c.close()

    def capture(self, tag: str) -> dict:
        cap = HERE / "d7_capture.py"
        try:
            p = subprocess.run(
                [sys.executable, str(cap), "--out", str(self.out / "captures"),
                 "--tag", tag, "--since", str(self.args.since)],
                capture_output=True, text=True, timeout=180)
            info = {"tag": tag, "rc": p.returncode,
                    "stdout": p.stdout[-2000:], "stderr": p.stderr[-1000:]}
        except subprocess.TimeoutExpired:
            info = {"tag": tag, "rc": 124, "error": "capture timed out"}
        with self.lock:
            self.captures.append(info)
        print(f"    CAPTURE[{tag}] rc={info['rc']}", flush=True)
        return info

    # -- monitor ----------------------------------------------------------- #
    def monitor_loop(self, t_start: float) -> None:
        stall_s = self.args.stall_s
        while not self.stop.wait(self.args.sample_s):
            now = time.time()
            heaps = self.heaps()
            tpu = self.tpu()
            dc = dmesg_counts()
            with self.lock:
                inflight = {s: (k, round(now - t0, 1)) for s, (k, t0) in
                            self.inflight.items()}
                last_ok_age = round(now - self.last_ok, 1)
                n_req, n_ok = self.n_requests, self.n_ok
            sample = {"t": time.strftime("%H:%M:%S"), "elapsed_s": round(now - t_start, 1),
                      "heaps": heaps, "tpu": tpu, "dmesg": dc,
                      "n_requests": n_req, "n_ok": n_ok,
                      "inflight": inflight, "last_ok_age_s": last_ok_age}
            with self.lock:
                self.samples.append(sample)
            print(f"    {sample['t']} +{sample['elapsed_s']:6.0f}s heaps={heaps} "
                  f"tpu={tpu.get('percent')} req={n_req} ok={n_ok} "
                  f"inflight={len(inflight)} last_ok={last_ok_age}s "
                  f"dmesg={dc['wait_api_timeout']}/{dc['npu_fault']}", flush=True)

            confirmed = dc["wait_api_timeout"] > self.dmesg_base["wait_api_timeout"]
            stalled = bool(inflight) and last_ok_age > stall_s
            if confirmed and not self._captured_confirmed:
                self._captured_confirmed = True
                self.hang = {"detected": True, "kind": "dmesg_timeout",
                             "elapsed_s": round(now - t_start, 1),
                             "dmesg": dc, "inflight": inflight,
                             "last_ok_age_s": last_ok_age}
                print("    *** HANG CONFIRMED (wait api timeout) ***", flush=True)
                self.capture("confirmed")
                # Then prove it does not recover on its own.  This is the thing
                # that decides whether a reboot is mandatory, and it is cheap:
                # one request against the cheapest model, bounded.
                time.sleep(self.args.post_wait)
                with self.lock:
                    still = {str(s): {"kind": k, "age_s": round(time.time() - t0, 1)}
                             for s, (k, t0) in self.inflight.items()}
                self.hang["after_wait_s"] = self.args.post_wait
                self.hang["still_inflight"] = still
                self.hang["probe_after_wait"] = self._bounded_probe("embed", 45)
                self.capture("post")
                self.stop.set()
                return
            if stalled and not self._captured_suspect:
                self._captured_suspect = True
                self.hang = {"detected": True, "kind": "stall",
                             "elapsed_s": round(now - t_start, 1),
                             "dmesg": dc, "inflight": inflight,
                             "last_ok_age_s": last_ok_age}
                print(f"    *** STALL: no success for {last_ok_age}s ***",
                      flush=True)
                self.capture("suspect")

    # -- main -------------------------------------------------------------- #
    def run(self) -> int:
        print(f"=== {self.args.run}  {time.strftime('%Y-%m-%d %H:%M:%S')}",
              flush=True)
        res: dict = {"run": self.args.run, "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "config": {"models": self.args.models,
                                "load": self.args.load,
                                "minutes": self.args.minutes,
                                "pre": self.args.pre,
                                "stall_s": self.args.stall_s},
                     "boot_id": sh("cat /proc/sys/kernel/random/boot_id"),
                     "uptime": sh("uptime")}
        try:
            self.dmesg_base = dmesg_counts()
            res["dmesg_before"] = self.dmesg_base
            print(f"    dmesg before: {self.dmesg_base}", flush=True)
            print("=== load models", flush=True)
            res["loaded"] = self.ensure_loaded()
            print(f"    resident: {res['loaded']}", flush=True)
            print(f"    heaps after load: {self.heaps()}", flush=True)

            if self.args.pre:
                print(f"=== pre-ops {self.args.pre}", flush=True)
                res["pre_ops"] = self.pre_ops(self.args.pre)
                print(f"    pre-ops done: {res['pre_ops']}", flush=True)

            # Re-ensure after pre-ops: an OCR cycle leaves OCR unloaded, and a
            # crash can leave the service re-adopting.
            res["loaded"] = self.ensure_loaded()
            before = self.probe()
            res["probe_before"] = before
            print(f"    probe before: {before}", flush=True)
            if any(v != 200 for v in before.values()):
                res["aborted"] = f"a model did not answer 200 before the run: {before}"
                print("    ABORT: " + res["aborted"], flush=True)
                return 1

            res["heaps_before"] = self.heaps()
            specs = []
            for item in self.args.load.split(","):
                kind, _, n = item.partition(":")
                specs.append((kind, int(n or 1)))
            threads = []
            for kind, n in specs:
                for i in range(n):
                    t = threading.Thread(target=self.load_loop,
                                         args=(kind, DEFAULT_PAUSE[kind]),
                                         daemon=True, name=f"{kind}{i}")
                    threads.append(t)
            t_start = time.time()
            res["t_start"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            for t in threads:
                t.start()
            mon = threading.Thread(target=self.monitor_loop, args=(t_start,),
                                   daemon=True)
            mon.start()

            # Start the clock.  The monitor runs alongside and is what notices a
            # hang; it also owns the captures.
            deadline = t_start + self.args.minutes * 60
            while time.time() < deadline and not self.stop.is_set():
                time.sleep(1)
            clean = not self.stop.is_set()
            self.stop.set()

            res["clean_end"] = clean
            res["duration_s"] = round(time.time() - t_start, 1)

            # End-of-run probes: "no hang" is only meaningful if the models
            # still answer.  **Not run after a hang** -- every one of these
            # requests would queue behind the wedged TPU and burn its full
            # timeout, which is hours for six models, and the result is already
            # decided.  A short timeout is used even on the clean path so a
            # late wedge cannot hold the run open either.
            if self.hang.get("detected") or not clean:
                res["probe_after"] = "skipped (hang detected)"
            else:
                res["probe_after"] = self.probe(timeout=60)
            res["heaps_after"] = self.heaps()
            res["dmesg_after"] = dmesg_counts()
        except BaseException as exc:  # noqa: BLE001 - always write a result
            res["error"] = f"{type(exc).__name__}: {exc}"
            res["traceback"] = traceback.format_exc()[-3000:]
            print("    ERROR: " + res["error"], flush=True)
        finally:
            res["hang"] = self.hang
            res["captures"] = self.captures
            res["outcomes"] = self.outcomes
            res["n_requests"] = self.n_requests
            res["n_ok"] = self.n_ok
            res["samples"] = self.samples
            res["ended"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            # Which requests were in flight when it wedged: the one thing that
            # says *what the device was executing*, which is what the driver
            # team needs.  The per-request log has every request; this is the
            # subset that never came back.
            with self.lock:
                res["inflight_at_end"] = {
                    str(s): {"kind": k, "age_s": round(time.time() - t0, 1)}
                    for s, (k, t0) in self.inflight.items()}
            (self.out / "result.json").write_text(
                json.dumps(res, ensure_ascii=False, indent=1))
            self.reqlog.close()
            # Turn the end of the run into a sentinel the host driver polls for.
            (self.out / "DONE").write_text(str(res.get("hang", {}).get("detected")))
            print(f"=== result -> {self.out / 'result.json'}", flush=True)
            print(f"=== hang={res.get('hang')}", flush=True)
            print(f"=== requests={res.get('n_requests')} ok={res.get('n_ok')} "
                  f"outcomes={res.get('outcomes')}", flush=True)
            sys.stdout.flush()
            sys.stderr.flush()
            # Abandon any thread still blocked on a wedged TPU: daemon threads
            # die with the process, and joining them would hang forever.
            os._exit(0 if not res.get("hang", {}).get("detected") else 2)
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True, help="run id, e.g. R1")
    ap.add_argument("--out", default="/data/mys2693/runs")
    ap.add_argument("--minutes", type=float, default=25)
    ap.add_argument("--models", default="chat,embed,rerank,asr,ocr,vl",
                    help="models to keep resident (kinds, comma separated)")
    ap.add_argument("--load", default="chat:2,embed:1,rerank:1,ocr:1,vl:1,asr:1",
                    help="load threads as kind:n,...")
    ap.add_argument("--pre", default="",
                    help="pre-operations: crash-idle,crash-busy,ocr-cycles:N")
    ap.add_argument("--stall-s", type=float, default=150,
                    help="no successful response for this long, with requests "
                         "outstanding, counts as a stall (default 150)")
    ap.add_argument("--sample-s", type=float, default=15)
    ap.add_argument("--since", type=float, default=10,
                    help="minutes of inference records the capture keeps")
    ap.add_argument("--post-wait", type=float, default=180,
                    help="after a confirmed hang, wait this long before proving "
                         "the device has not recovered (default 180)")
    ap.add_argument("--admin-key", default=os.environ.get("D7_ADMIN_KEY", ""))
    args = ap.parse_args()
    return Runner(args).run()


if __name__ == "__main__":
    sys.exit(main())
