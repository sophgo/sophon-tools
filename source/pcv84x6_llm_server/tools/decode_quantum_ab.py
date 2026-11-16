"""A/B the decode quantum on real hardware: q=1 against q=8.

    python3 tools/decode_quantum_ab.py --python /data/venv/bin/python \
        --model /data/cv84x6_llm_server/models/qwen3.6-35b-a3b-128k/....bmodel \
        --tokenizer /opt/sophgo/cv84x6_llm_server/model-config/qwen3_5/tokenizer.json \
        --lib /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \
        --order 1 8 1 8 --sessions 1 2 3 --decode 32

Why this harness rather than `analysis/agg_probe.py`: agg_probe's `--quantum` loop
is a model of the scheduler, not the scheduler. This drives the real worker
(`app.engine.worker`, the process the service runs) over its JSON-lines socket,
so the numbers include the production path: prefill, admission, per-token
bookkeeping, the token sink, and the quantum as the loop actually implements it.
The quantum is switched with the console's own `configure` op on one loaded
process, which is also how a live settings change reaches the board -- so the
reconfiguration path gets exercised too, and the 20.6 GB bmodel is loaded once.

`--order 1 8 1 8` measures each setting twice, interleaved: if the second q=8 run
reproduces the first and both beat both q=1 runs, the difference is the quantum
rather than warm-up drift. Every request creates a new session and the prefix
cache is off (`--no-prefix-cache`), so no run inherits state from an
earlier one.

Per (quantum, prompt length) it reports, for 1/2/3 concurrent sessions:
aggregate tok/s, per-session tok/s, and time-to-first-token; then it compares
the streamed chunks of every q=8 run with the q=1 runs chunk by chunk. The sink
is called once per token, so equal chunk lists mean equal token streams.

One worker at a time, sequential runs -- two decode processes on the same TPU
contend for the whole device and the numbers become meaningless (see
analysis/README.md).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SHORT_PROMPT = (
    "Write a continuous stream of at least 200 words about how a harbour archive "
    "catalogues its ledgers, maps and photographs. Do not stop early, do not use "
    "a list, and do not end with a summary: keep writing in full sentences."
)
# Past the 2048 boundary where the long-context decode stage and the exact tail
# switch on, and long enough to reach ~2000+ tokens through the chat template.
#
# The paragraphs are *varied on purpose*: a prompt built by repeating one
# paragraph made the model emit its stop token on the very first step, so a run
# finished with zero tokens and compared nothing. Distinct sentences also keep
# the model from noticing it is being fed a loop.
LONG_PARAGRAPHS = [
    "The maintenance log for the northern cluster begins in March, when the second "
    "shelf was rebuilt after a fan failure. The engineer on call replaced the fan "
    "tray, cleaned the filters, and left a note that the intake duct had been "
    "partially blocked by dust since the previous winter.",
    "Storage was laid out in two pools: a small mirrored pool for the catalogue "
    "database and a larger parity pool for scans. The mirrored pool was chosen "
    "because the catalogue is written constantly and parity writes were measurably "
    "slower, while scans are written once and read rarely.",
    "Every outage taught the operators something. After the first one they added "
    "an out-of-band console, because the network stack had taken eleven minutes to "
    "come back and nobody could see why. After the second they began photographing "
    "the cabling before touching it.",
    "The verification procedure changed most of all. Originally a reboot was "
    "considered successful once the login prompt appeared. Later the operator had "
    "to read the sensor table, confirm both pools were clean, and run one write "
    "and one read against each pool before closing the ticket.",
    "Power was the recurring worry. The building supply sagged during summer "
    "afternoons when the air conditioning cycled, and the smaller units would "
    "restart rather than ride through it. A line-interactive unit was added for "
    "the controllers only, which was cheaper than protecting the whole rack.",
    "Documentation lived in a wiki that nobody updated during an incident. The "
    "team eventually split it in two: a short card taped inside the rack door with "
    "the six commands that actually get used, and the long wiki page with the "
    "history, which is read afterwards rather than during.",
    "Monitoring was deliberately boring. Instead of a dashboard nobody watched, "
    "two alerts were kept: one for a pool that has not scrubbed on schedule, and "
    "one for a drive that has logged a corrected error more than three times in a "
    "day. Everything else was moved to a weekly review.",
    "The change the operators consider most valuable was the handover sheet. Each "
    "shift writes four lines: what is running, what is degraded, what was touched, "
    "and what the next person should check first. The sheet lives next to the "
    "console, not in the ticket system, because during an incident nobody logs in.",
]
LONG_PROMPT = (
    "You are a careful operations engineer reading a maintenance report about a "
    "small cluster. Read the following notes and then write at least 200 words "
    "describing, in full sentences, how the operators changed their procedure and "
    "why each change was made. Do not use a list.\n\n"
    + "\n\n".join(LONG_PARAGRAPHS * 4)
)


class Worker:
    """One worker process and one socket, enough to drive real requests.

    Events are dispatched to a queue per ``req_id``: concurrent lanes share the
    socket, and one shared queue would let a lane consume another lane's deltas.
    """

    def __init__(self, argv: list[str], port: int, args) -> None:
        self.argv = argv
        self.port = port
        self.args = args
        self.proc = None
        self.reader = None
        self.writer = None
        self._queues: dict[str, asyncio.Queue] = {}

    def _queue(self, req_id: str) -> asyncio.Queue:
        q = self._queues.get(req_id)
        if q is None:
            q = self._queues[req_id] = asyncio.Queue()
        return q

    async def __aenter__(self) -> "Worker":
        cfg = self.args
        # The 20.6 GB bmodel needs almost the whole NPU heap, so a load fails
        # cleanly ("bm_alloc_gmem failed") if another probe still holds memory
        # from a previous slot. That is not a measurement result, so retry for a
        # couple of minutes instead of burning the run.
        last = ""
        for attempt in range(1, cfg.load_attempts + 1):
            self.proc = await asyncio.create_subprocess_exec(
                *self.argv, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=HERE,
            )
            # The model load is 60 s+ on the 35B; the worker prints its ready
            # banner only after the weights are in the NPU heap.
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=900)
            try:
                ready = json.loads(line)
            except json.JSONDecodeError:
                err = (await self.proc.stderr.read()).decode()[-800:]
                last = f"{line!r} / {err.strip().splitlines()[-1] if err.strip() else ''}"
                if attempt < cfg.load_attempts:
                    print(f"    worker load failed ({last}); retry in 30 s "
                          f"[{attempt}/{cfg.load_attempts}]", flush=True)
                    await asyncio.sleep(30)
                    continue
                raise SystemExit(f"worker did not start after {attempt} attempts: {last}")
            if ready.get("event") != "ready":
                raise SystemExit(f"unexpected worker banner: {ready}")
            break
        self.reader, self.writer = await asyncio.open_connection(
            "127.0.0.1", self.port, limit=64 * 1024 * 1024)
        self._pump = asyncio.create_task(self._read())
        return self

    async def __aexit__(self, *exc) -> None:
        try:
            self.writer.write(b'{"op":"shutdown"}\n')
            await self.writer.drain()
        except Exception:
            pass
        self._pump.cancel()
        try:
            await asyncio.wait_for(self.proc.wait(), timeout=120)
        except asyncio.TimeoutError:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=30)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()

    async def _read(self) -> None:
        while True:
            line = await self.reader.readline()
            if not line:
                for q in self._queues.values():
                    await q.put({"op": "eof"})
                return
            msg = json.loads(line)
            rid = msg.get("req_id")
            if rid:
                await self._queue(rid).put(msg)

    async def send(self, obj: dict) -> None:
        self.writer.write((json.dumps(obj) + "\n").encode())
        await self.writer.drain()

    async def _next(self, req_id: str, timeout: float) -> dict:
        msg = await asyncio.wait_for(self._queue(req_id).get(), timeout=timeout)
        if msg.get("op") == "eof":
            raise SystemExit(f"worker closed the connection during {req_id}")
        return msg

    async def stats(self) -> dict:
        req_id = "__q_ab_stats__"
        await self.send({"op": "stats", "req_id": req_id})
        return await self._next(req_id, 60)

    async def one(self, req_id: str, prompt: str, max_tokens: int) -> dict:
        """Run one request to completion; return its timing and chunks."""
        await self.send({"op": "generate", "req_id": req_id, "prompt": prompt,
                         "params": {"max_tokens": max_tokens}})
        t0 = time.perf_counter()
        chunks: list[str] = []
        first_at = None
        while True:
            msg = await self._next(req_id, 1800)
            op = msg.get("op")
            if op == "delta":
                if first_at is None:
                    first_at = time.perf_counter()
                chunks.append(msg["text"])
            elif op == "meta":
                if first_at is None:
                    first_at = time.perf_counter()
            elif op in ("done", "error"):
                return {"chunks": chunks, "done": msg,
                        "start": t0, "first": first_at, "end": time.perf_counter()}

    async def cancel_after(self, req_id: str, prompt: str, max_tokens: int,
                           after: int) -> dict:
        """Cancel once `after` chunks have streamed; report how it ended.

        ``chunks_after_cancel`` counts deltas that arrive after the cancel was
        sent, which includes whatever was already in the socket buffer. The
        number that actually shows the quantum's cancellation granularity is
        ``worker_tokens`` from the done event against what the client got: the
        worker stops generating within one step of the cancel, so its token
        count must not run to ``max_tokens``.
        """
        await self.send({"op": "generate", "req_id": req_id, "prompt": prompt,
                         "params": {"max_tokens": max_tokens}})
        chunks: list[str] = []
        cancel_at = None
        cancel_worker_tokens = None
        busy_before = (await self.stats())["completion_tokens"]
        while True:
            msg = await self._next(req_id, 600)
            if msg.get("op") == "delta":
                chunks.append(msg["text"])
                if len(chunks) == after and cancel_at is None:
                    cancel_at = time.perf_counter()
                    await self.send({"op": "cancel", "req_id": req_id})
                    # How much the worker had actually generated at the moment
                    # the cancel landed: the gap to `after` is what the socket
                    # and the client's own loop already had in hand, not extra
                    # work the scheduler did.
                    cancel_worker_tokens = (await self.stats())["completion_tokens"] - busy_before
            elif msg.get("op") in ("done", "error"):
                end = time.perf_counter()
                stats = await self.stats()
                return {
                    "chunks_after_cancel": max(0, len(chunks) - after),
                    "chunks_total": len(chunks),
                    "cancel_to_done_s": None if cancel_at is None else end - cancel_at,
                    "worker_tokens": stats["completion_tokens"] - busy_before,
                    "worker_tokens_at_cancel": cancel_worker_tokens,
                    "done": msg,
                }


COMPETITOR_PROGRAMS = {
    # Binaries that load a bmodel and drive the TPU. Two decode processes
    # contend for the whole device, so a run started next to one of these
    # measures the contention, not the quantum (analysis/README.md, "Only one
    # probe at a time").
    "queue_model", "queue_scope", "queue_threads", "queue_occupancy",
    "tpu_busy", "token_shape", "graph_tpu", "graph_probe", "token_probe",
    "bw_probe", "probe_lm", "overlap",
}
COMPETITOR_MODULES = {
    # Python entry points that end up in the same bmodel / TPU.
    "app.engine.worker", "tools.decode_bench", "tools.engine_check",
    "tools.cache_check", "tools.session_bench", "tools.decode_quantum_ab",
    "analysis.agg_probe",
}
# A shell carries whatever it was told to run in its own argv; it drives nothing
# itself, and the actual probe shows up as its own (child) process.
SHELLS = {"bash", "sh", "dash", "zsh", "timeout", "nohup", "setsid", "env"}


def _program(argv: list[str]) -> tuple[str, str]:
    """(executable name, module or script) of a process, as it drives the TPU."""
    exe = os.path.basename(argv[0].decode(errors="replace"))
    args = [a.decode(errors="replace") for a in argv[1:]]
    if exe.startswith("python"):
        if "-m" in args:
            i = args.index("-m")
            if i + 1 < len(args):
                return exe, args[i + 1]
        for a in args:
            if a.endswith(".py"):
                return exe, a
    return exe, ""


def competitors(port: int) -> list[str]:
    """Other processes currently able to drive the TPU, this run aside."""
    me = os.getpid()
    out = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == me:
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                argv = [a for a in f.read().split(b"\x00") if a]
        except OSError:
            continue
        if not argv:
            continue
        exe, target = _program(argv)
        if exe in SHELLS:
            continue
        # This harness's own worker lives on `port` and is expected.
        cmd = " ".join(a.decode(errors="replace") for a in argv)
        if f"--port {port}" in cmd:
            continue
        if exe in COMPETITOR_PROGRAMS or target in COMPETITOR_MODULES:
            out.append(f"{entry}: {cmd.strip()[:120]}")
    return out


async def wait_for_a_quiet_tpu(port: int, timeout_s: float) -> None:
    """Block until nobody else can drive the TPU, or give up with a clear error."""
    deadline = time.monotonic() + timeout_s
    said = False
    while True:
        busy = competitors(port)
        if not busy:
            return
        if not said:
            print(f"    another process is using the TPU, waiting (up to "
                  f"{timeout_s:.0f}s): {busy[0]}", flush=True)
            said = True
        if time.monotonic() > deadline:
            raise SystemExit("TPU still busy after waiting: " + "; ".join(busy))
        await asyncio.sleep(20)


def summarise(runs: list[dict]) -> dict:
    """Aggregate decode rate over the window in which every lane was decoding.

    Prefill is excluded on purpose. The first streamed token comes out of the
    prefill call, not out of a decode step, and prefill cost differs with the
    prompt (and, with chunking, with how the lanes interleave) -- including it
    would mix the thing under test with something the quantum does not touch.
    So the window starts at the last lane's first token and ends at the last
    lane's finish, and the token count drops each lane's first token.
    """
    starts = [r["first"] for r in runs if r["first"] is not None]
    if not starts:
        return {"aggregate_tps": 0.0, "per_session_tps": 0.0, "first_token_s": None,
                "tokens": 0, "decode_s": 0.0}
    window_start = max(starts)
    window_end = max(r["end"] for r in runs)
    span = max(0.0, window_end - window_start)
    decoded = sum(max(0, len(r["chunks"]) - 1) for r in runs)
    per = [(max(0, len(r["chunks"]) - 1) / (r["end"] - r["first"]))
           for r in runs if r["end"] > r["first"]]
    return {
        "aggregate_tps": decoded / span if span > 0 else 0.0,
        "per_session_tps": statistics.mean(per) if per else 0.0,
        # Time to first token, measured from the request being sent: this is
        # what a user waits for, so it keeps prefill in.
        "first_token_s": statistics.mean(starts[i] - runs[i]["start"]
                                         for i in range(len(runs))
                                         if runs[i]["first"] is not None),
        "tokens": decoded,
        "decode_s": span,
    }


async def measure(worker: Worker, prompt: str, sessions: int, decode: int,
                  tag: str) -> dict:
    # Identical prompt in every lane, so all lanes are directly comparable and
    # a lane's own output can be checked against another lane's.
    runs = await asyncio.gather(*(
        worker.one(f"{tag}-s{i}", prompt, decode) for i in range(sessions)
    ))
    out = summarise(runs)
    out["chunks"] = [r["chunks"] for r in runs]
    out["done"] = [r["done"] for r in runs]
    for i, r in enumerate(runs):
        if r["done"].get("op") != "done":
            raise SystemExit(f"{tag}: session {i} failed: {r['done']}")
        if r["done"].get("completion_tokens", 0) < decode // 2:
            # A run the model ended on its own compares nothing: the point of
            # the A/B is many decode steps, and a 0-3 token answer exercises
            # prefill. Fail loudly instead of reporting a meaningless ratio.
            raise SystemExit(
                f"{tag}: session {i} produced only "
                f"{r['done'].get('completion_tokens')} of {decode} tokens "
                f"(finish_reason={r['done'].get('finish_reason')}); the prompt or "
                f"the max_tokens setting has to keep the model generating for the "
                f"comparison to mean anything")
    return out


async def main_async(args) -> int:
    argv = [
        args.python, "-m", "app.engine.worker",
        "--model-id", args.model_id, "--port", str(args.port),
        "--backend", args.backend,
        "--max-concurrent", str(max(args.sessions)),
        # No prefix cache: a second run of the same prompt must not restore a
        # snapshot, or the two settings would see different prefill costs.
        # The explicit switch, not the deprecated MB value: since MYS-2785 the
        # latter is a cap on the model's budget rather than an override, so
        # relying on it here would silently re-enable the cache if the order of
        # precedence ever changed again -- which is exactly what happened.
        "--no-prefix-cache",
        "--exact-tail", str(args.exact_tail),
        "--decode-quantum", str(args.order[0]),
    ]
    if args.backend == "native":
        argv += [
            "--model-path", args.model,
            "--tokenizer-path", args.tokenizer,
            "--native-lib", args.lib,
        ]
    else:
        # The mock backend only needs a context window and a per-token delay;
        # it exists so this harness can be validated on x86 before spending a
        # board reboot on it.
        argv += ["--context-length", str(args.mock_context),
                 "--decode-delay-ms", str(args.mock_delay_ms)]
    report: dict[str, dict] = {}
    failures: list[str] = []
    # Every run of a setting gets its own key; the later ones are compared with
    # the earlier ones to show the difference is the setting, not drift.
    seen: dict[int, int] = {}

    print(f"=== loading {args.model_id} (first quantum {args.order[0]}) ...", flush=True)
    if args.backend == "native":
        await wait_for_a_quiet_tpu(args.port, args.wait_tpu_s)
    async with Worker(argv, args.port, args) as w:  # noqa: SIM117
        # One throwaway request before any measurement: the first decode after a
        # load pays page faults and lazy graph setup that nobody would see in
        # steady state, and whichever quantum ran first would absorb it.
        print("    warm-up ...", flush=True)
        await w.one("__warmup__", SHORT_PROMPT, 16)
        for quantum in args.order:
            applied = None
            if (seen.get(quantum, 0) > 0 or quantum != args.order[0]):
                # The console's own path: this is what a settings change does to
                # a running worker, and it keeps one 20.6 GB model load for the
                # whole A/B.
                await w.send({"op": "configure", "req_id": "__q_ab_cfg__",
                              "decode_quantum": quantum})
                applied = await w._next("__q_ab_cfg__", 60)
            stats = await w.stats()
            got = stats.get("decode_quantum")
            if got != quantum:
                failures.append(f"worker reported quantum {got}, asked for {quantum}")
            print(f"\n=== run {seen.get(quantum, 0) + 1} at decode-quantum {got}"
                  + (f" (configure reply {applied.get('decode_quantum')})" if applied else ""),
                  flush=True)

            for label, prompt in (("short", SHORT_PROMPT), ("long", LONG_PROMPT)):
                for sessions in args.sessions:
                    tag = f"q{quantum}-{label}-{sessions}"
                    if tag in report:
                        tag = f"{tag}#{seen[quantum] + 1}"
                    # Only on the board: elsewhere "another worker" is just
                    # the test suite, and the mock does not touch a TPU.
                    other = competitors(args.port) if args.backend == "native" else []
                    if other:
                        raise SystemExit(
                            f"{tag}: another process started using the TPU mid-run, "
                            f"these numbers are not comparable: {other[0]}")
                    m = await measure(w, prompt, sessions, args.decode, tag)
                    report[tag] = m
                    print(f"    {label:5s} {sessions} session(s): "
                          f"aggregate {m['aggregate_tps']:6.2f} tok/s, "
                          f"each {m['per_session_tps']:6.2f} tok/s, "
                          f"first {m['first_token_s']:.3f}s, "
                          f"{m['tokens']} tok in {m['decode_s']:.2f}s", flush=True)
            cancel = await w.cancel_after(f"q{quantum}-cancel-{seen.get(quantum, 0) + 1}",
                                          SHORT_PROMPT, 100_000, args.cancel_after)
            report[f"q{quantum}-cancel#{seen.get(quantum, 0) + 1}"] = cancel
            print(f"    cancel after {args.cancel_after} tokens: "
                  f"{cancel['chunks_after_cancel']} more token(s), "
                  f"done in {cancel['cancel_to_done_s']:.3f}s, "
                  f"reason {cancel['done'].get('finish_reason')}", flush=True)
            seen[quantum] = seen.get(quantum, 0) + 1
        await w.send({"op": "shutdown"})

    # -- comparison ------------------------------------------------------
    print("\n=== q=1 vs q=8 aggregate throughput", flush=True)
    head = (f"{'case':22s} {'q=1 agg':>9s} {'q=8 agg':>9s} {'ratio':>7s} "
            f"{'q=1 1st':>9s} {'q=8 1st':>9s}  tokens")
    print(head, flush=True)
    print("-" * len(head), flush=True)

    def pick(quantum: int, label: str, sessions: int) -> list[dict]:
        """Every measured run of (quantum, label, sessions), in measurement order."""
        out = []
        i = 1
        while True:
            tag = f"q{quantum}-{label}-{sessions}" if i == 1 else \
                  f"q{quantum}-{label}-{sessions}#{i}"
            if tag not in report:
                break
            out.append(report[tag])
            i += 1
        return out

    for label in ("short", "long"):
        for sessions in args.sessions:
            ones = pick(1, label, sessions)
            eights = pick(8, label, sessions)
            if not ones or not eights:
                continue
            a = statistics.mean(x["aggregate_tps"] for x in ones)
            b = statistics.mean(x["aggregate_tps"] for x in eights)
            fa = statistics.mean(x["first_token_s"] for x in ones)
            fb = statistics.mean(x["first_token_s"] for x in eights)
            ratio = b / a if a else 0.0
            print(f"{label + ' ' + str(sessions) + ' sess':22s} "
                  f"{a:9.2f} {b:9.2f} {ratio:6.2f}x {fa:9.3f} {fb:9.3f}  "
                  f"{ones[0]['tokens']}/{eights[0]['tokens']}", flush=True)
            if sessions > 1 and ratio < args.min_gain:
                failures.append(f"{label} {sessions} sessions: q=8 only {ratio:.2f}x q=1 "
                                f"(wanted >= {args.min_gain:.2f}x)")
            # Single stream must not regress: with one active request the loop
            # never rotates, so the quantum cannot help or hurt.
            if sessions == 1 and ratio < args.solo_floor:
                failures.append(f"{label} single stream: q=8 {ratio:.3f}x q=1 "
                                f"(wanted >= {args.solo_floor:.3f}x)")

    if len(args.order) > 1:
        print("\n=== repeatability (same setting measured twice)", flush=True)
        for label in ("short", "long"):
            for sessions in args.sessions:
                ones = pick(1, label, sessions)
                eights = pick(8, label, sessions)
                for name, runs in (("q=1", ones), ("q=8", eights)):
                    if len(runs) > 1:
                        vals = [r["aggregate_tps"] for r in runs]
                        spread = (max(vals) - min(vals)) / statistics.mean(vals)
                        print(f"  {name} {label:5s} {sessions} sess: "
                              + ", ".join(f"{v:.2f}" for v in vals)
                              + f" tok/s (spread {spread * 100:.1f}%)", flush=True)

    print("\n=== output equality (chunk by chunk, sink is per token)", flush=True)
    for label in ("short", "long"):
        for sessions in args.sessions:
            ones = pick(1, label, sessions)
            eights = pick(8, label, sessions)
            if not ones or not eights:
                continue
            for lane in range(sessions):
                want = ones[0]["chunks"][lane]
                for run_i, run in enumerate(eights, start=1):
                    got = run["chunks"][lane]
                    ok = got == want
                    print(f"  {label:5s} {sessions} sess lane {lane} q=8 run {run_i}: "
                          f"{'identical' if ok else 'DIFFERENT'} ({len(got)} chunks)",
                          flush=True)
                    if not ok:
                        at = next((j for j, (x, y) in enumerate(zip(want, got))
                                   if x != y), min(len(want), len(got)))
                        failures.append(f"{label} {sessions}s lane {lane} q=8 run {run_i}: "
                                        f"output differs from q=1 at chunk {at}: "
                                        f"{want[at:at + 4]} vs {got[at:at + 4]}")
                # Lanes share one prompt, so the lanes themselves must agree:
                # a divergence here would mean session isolation broke, not that
                # the quantum did.
                for other in range(1, sessions):
                    if ones[0]["chunks"][other] != want:
                        failures.append(f"{label} {sessions}s: lane {other} differs from "
                                        f"lane 0 at q=1 (session isolation)")

    print("\n=== cancel", flush=True)
    for quantum in dict.fromkeys(args.order):
        i = 1
        while f"q{quantum}-cancel#{i}" in report:
            c = report[f"q{quantum}-cancel#{i}"]
            print(f"  q={quantum} run {i}: worker generated {c['worker_tokens']} token(s) "
                  f"({c['chunks_after_cancel']} delta(s) reached the client after the "
                  f"cancel), done {c['cancel_to_done_s']:.3f}s later, "
                  f"reason {c['done'].get('finish_reason')}", flush=True)
            if c["done"].get("finish_reason") != "cancelled":
                failures.append(f"q={quantum}: cancel did not end the request as cancelled")
            # The client asks for max_tokens=100000, so anything that ends near
            # `cancel_after` proves the cancel landed. What the socket cannot
            # distinguish is "the loop yields per token" from "the loop blocks
            # for one slice": the cancel message reaches the worker while it is
            # already inside a step, and stats is sampled over the same socket.
            # So the bound here is the quantum itself (the client round trip can
            # cost at most one slice), and the per-token granularity is asserted
            # precisely in tests/test_decode_quantum.py, where the sink can call
            # cancel() from inside a slice.
            limit = args.cancel_after + quantum + args.cancel_slack
            if c["worker_tokens"] > limit:
                failures.append(
                    f"q={quantum}: worker generated {c['worker_tokens']} tokens after a "
                    f"cancel sent at {args.cancel_after} (bound {limit}); the cancel "
                    f"did not take effect promptly")
            # The stream must not run on: this is the user-visible half.
            if c["chunks_after_cancel"] > quantum + args.cancel_slack:
                failures.append(
                    f"q={quantum}: {c['chunks_after_cancel']} deltas arrived after the "
                    f"cancel (bound {quantum + args.cancel_slack})")
            i += 1

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        print(f"\nwrote {args.json}", flush=True)

    if failures:
        print("\nFAIL", flush=True)
        for f in failures:
            print(f"  - {f}", flush=True)
        return 1
    print("\nPASS", flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--backend", default="native", choices=["native", "mock"])
    p.add_argument("--model", default="")
    p.add_argument("--tokenizer", default="")
    p.add_argument("--lib", default="")
    p.add_argument("--mock-context", type=int, default=12288)
    p.add_argument("--mock-delay-ms", type=float, default=0.0)
    p.add_argument("--model-id", default="qwen3.6-35b-a3b-128k")
    p.add_argument("--port", type=int, default=19100)
    p.add_argument("--wait-tpu-s", type=float, default=3600,
                   help="how long to wait for other TPU users to finish before starting")
    p.add_argument("--load-attempts", type=int, default=6,
                   help="retries when another process still holds NPU memory, 30 s apart")
    p.add_argument("--order", type=int, nargs="+", default=[1, 8, 1, 8],
                   help="quantum settings to measure, in this order; alternating "
                        "1 8 1 8 shows the gap is the setting and not warm-up drift")
    p.add_argument("--sessions", type=int, nargs="+", default=[1, 2, 3])
    p.add_argument("--decode", type=int, default=32,
                   help="tokens per request; equal for both quanta")
    p.add_argument("--cancel-after", type=int, default=4,
                   help="tokens to stream before sending cancel")
    p.add_argument("--exact-tail", type=int, default=64)
    p.add_argument("--cancel-slack", type=int, default=2,
                   help="extra tokens the worker may produce after the cancel was "
                        "sent (one in-flight step, plus the client-to-worker round trip)")
    p.add_argument("--min-gain", type=float, default=1.15,
                   help="required aggregate gain for 2+ sessions")
    p.add_argument("--solo-floor", type=float, default=0.99,
                   help="a single stream may not regress below this ratio")
    p.add_argument("--json", default="", help="write the raw report here")
    args = p.parse_args()
    if args.backend == "native" and not (args.model and args.tokenizer and args.lib):
        p.error("--model, --tokenizer and --lib are required for the native backend")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
