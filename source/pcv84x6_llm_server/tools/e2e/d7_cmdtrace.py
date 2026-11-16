"""Align the engine's command trace with the driver's kernel_fifo, and name the
command that never came back (MYS-2703 step 1).

Two independent records of the same NPU work exist after a hang:

* ``LLM_CMD_TRACE`` (``native/src/llm_engine.cpp``): one line per command,
  written *before* the call. Launches carry an ordinal ``L<n>`` that counts the
  launches of one process, and every line has a timestamp on
  ``CLOCK_MONOTONIC`` -- the clock ``dmesg`` uses. It includes d2d and memset,
  which is the whole point: ``kernel_fifo`` does not.
* ``/proc/bmtpu/kernel_fifo``: the driver's record, keyed by an ``api_seq``
  that increments per launch, with the ``block``/``send_core_num`` of the
  outbox packet.

Neither is a complete account on its own -- the fifo cannot see the copies,
the trace cannot see the driver's ``api_seq`` or core layout -- so this tool
puts them side by side on the timestamp both share.

What "the stuck command" means here, stated so the answer cannot be read as
something stronger than it is:

* A launch that was **submitted** and never retired is invisible to the
  engine's own ``done`` lines only if the engine's thread is inside
  ``bm_thread_sync``; the launch call itself is asynchronous and returns.
* So the trace's last unmatched ``see`` is the command whose *issue* the
  process never got past, and the fifo's ``seq`` is the last one the driver
  accepted. ``dmesg``'s ``last=<seq> cpl=<seq-1>`` then says which of those
  the firmware never answered.

Usage::

    python3 d7_cmdtrace.py --trace /data/mys2703/trace/cmd.log \\
        --pid 80724 --fifo kernel_fifo-tail.txt --dmesg dmesg-at-hang.txt
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path


def parse_trace(path: Path) -> list[dict]:
    """One dict per line. Fields: t, pid, tid, n, launch_ord, phase, what."""
    out = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        parts = line.split(" ", 6)
        if len(parts) < 7:
            continue
        try:
            t = float(parts[0])
            pid = int(parts[1])
            tid = int(parts[2])
            n = int(parts[3])
        except ValueError:
            continue
        rest = parts[4:]
        # rest is [<ord>, phase, what...] where <ord> is "" or "L<n>"
        ord_s, phase = rest[0], rest[1]
        what = rest[2] if len(rest) > 2 else ""
        out.append({
            "t": t, "pid": pid, "tid": tid, "n": n,
            "ord": int(ord_s[1:]) if ord_s.startswith("L") else None,
            "phase": phase, "what": what,
        })
    return out


_FIFO_REC = re.compile(r"^\s*\[(\d+)\]\s+seq=(\d+)\s+age=(\d+)ms\s+api=(\S+?)\((\w+)\).*?hwq=(\d+)",
                       re.M)
_FIFO_DETAIL = re.compile(r"block=(\d+).*?send_core_num=(\d+)", re.S)


def parse_fifo(path: Path) -> list[dict]:
    text = path.read_text(errors="replace")
    head = re.search(r"total=(\d+) showing=(\d+) capacity=(\d+)", text)
    recs = []
    matches = list(_FIFO_REC.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        detail = _FIFO_DETAIL.search(text, m.end(), end)
        recs.append({
            "idx": int(m.group(1)), "seq": int(m.group(2)), "age_ms": int(m.group(3)),
            "api": m.group(5), "hwq": int(m.group(6)),
            "block": int(detail.group(1)) if detail else None,
            "send_core_num": int(detail.group(2)) if detail else None,
        })
    meta = {"total": int(head.group(1))} if head else {}
    return recs, meta


_DMESG_TO = re.compile(
    r"wait api timeout, wait (\d+)ms, core_id=(\d+), inflight=(\d+), "
    r"last=(\d+), cpl=(\d+)")


def parse_dmesg(path: Path) -> dict:
    m = _DMESG_TO.search(path.read_text(errors="replace"))
    if not m:
        return {}
    return {"timeout_ms": int(m.group(1)), "core_id": int(m.group(2)),
            "inflight": int(m.group(3)), "last": int(m.group(4)),
            "cpl": int(m.group(5))}


def unmatched(lines: list[dict]) -> list[dict]:
    """``see`` lines with no ``done`` from the same thread, in order.

    Per (pid, tid) and per command label: a thread that launches, is asked to
    sync, and returns has a done for each. The ones left over are what it was
    inside when the process stopped.
    """
    open_: dict[tuple, list[dict]] = {}
    for ln in lines:
        key = (ln["pid"], ln["tid"])
        stack = open_.setdefault(key, [])
        if ln["phase"] == "see":
            stack.append(ln)
        elif ln["phase"] == "done":
            label = ln["what"].split(" rc=")[0]
            for j in range(len(stack) - 1, -1, -1):
                if stack[j]["what"].split(" ")[0] == label.split(" ")[0]:
                    stack.pop(j)
                    break
    return [x for s in open_.values() for x in s]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trace", required=True)
    ap.add_argument("--pid", type=int, default=0, help="worker pid to analyse")
    ap.add_argument("--fifo", default="")
    ap.add_argument("--dmesg", default="")
    ap.add_argument("--tail", type=int, default=40)
    args = ap.parse_args()

    lines = parse_trace(Path(args.trace))
    if args.pid:
        lines = [ln for ln in lines if ln["pid"] == args.pid]
    if not lines:
        raise SystemExit(f"no trace lines for pid {args.pid}")

    print(f"== trace: {len(lines)} lines, pids={sorted({l['pid'] for l in lines})}")
    kinds = Counter(l["what"].split(" ")[0] for l in lines if l["phase"] == "see")
    print("   commands seen: " + ", ".join(f"{k}={v}" for k, v in kinds.most_common()))

    # Single-core launches: the class the task points at.
    single = [l for l in lines if l["phase"] == "see" and l["what"].startswith("launch")
              and "core=1" in l["what"]]
    multi = [l for l in lines if l["phase"] == "see" and l["what"].startswith("launch")
             and "core=4" in l["what"]]
    others = [l for l in lines if l["phase"] == "see" and l["what"].startswith("launch")
              and "core=1" not in l["what"] and "core=4" not in l["what"]]
    print(f"   launches: core=4 {len(multi)}, core=1 {len(single)}, other {len(others)}")
    if single:
        print("   single-core graphs: " +
              ", ".join(f"{k}={v}" for k, v in
                        Counter(l["what"].split(" ")[1] for l in single).most_common()))

    print("\n== last commands before the stop (last %d lines)" % args.tail)
    for ln in lines[-args.tail:]:
        ord_s = f"L{ln['ord']}" if ln["ord"] is not None else "  "
        print(f"   {ln['t']:14.6f} {ord_s:>6} {ln['phase']:4} {ln['what']}")

    stuck = unmatched(lines)
    print(f"\n== commands with no matching 'done': {len(stuck)}")
    for ln in stuck:
        ord_s = f"L{ln['ord']}" if ln["ord"] is not None else "-"
        print(f"   {ln['t']:.6f} tid={ln['tid']} {ord_s} {ln['what']}")

    if args.fifo:
        recs, meta = parse_fifo(Path(args.fifo))
        print(f"\n== kernel_fifo: total={meta.get('total')} shown={len(recs)}")
        if recs:
            last = recs[-1]
            print(f"   first seq={recs[0]['seq']} last seq={last['seq']} "
                  f"hwq={last['hwq']} block={last['block']} "
                  f"send_core_num={last['send_core_num']} age={last['age_ms']}ms")
            blocks = Counter((r["block"], r["send_core_num"]) for r in recs)
            print("   (block, send_core_num) in the window: " +
                  ", ".join(f"{k}={v}" for k, v in blocks.most_common()))
            # The last record the driver accepted is the one dmesg's `last=`
            # names; anything after it is the next submit.
            print(f"   tail records: " + ", ".join(str(r["seq"]) for r in recs[-6:]))

    if args.dmesg:
        d = parse_dmesg(Path(args.dmesg))
        if d:
            print(f"\n== dmesg timeout: last={d['last']} cpl={d['cpl']} "
                  f"inflight={d['inflight']} core_id={d['core_id']} "
                  f"wait={d['timeout_ms']}ms")
            print(f"   unanswered api_seq = {d['last']} "
                  f"(cpl={d['cpl']} means everything up to cpl retired)")
        else:
            print("\n== dmesg: no 'wait api timeout' found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
