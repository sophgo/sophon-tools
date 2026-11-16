#!/usr/bin/env python3
"""The acceptance run over HTTP: console download → load → `/v1/ocr`.

``board_acceptance.py`` drives the backend directly, which is the right way to
isolate the pipeline. This drives the *service*: a real worker process, the RPC
socket, the multipart and JSON bodies, and the recorded rows -- i.e. what a
client actually gets.

    python3 tools/ocr/board_http_acceptance.py \\
        --repo /data/ocr-test/repo --models /data/ocr-test/models \\
        --lib /data/ocr-test/native/build/libcv84x6_llm.so \\
        --port 8099 --json-out /data/ocr-test/http_result.json

It starts the service itself (``--backend native``), waits for it, loads the
model through the console API, posts every golden image, compares the answers
with the golden, and prints the same table plus the wall-clock per request.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--models", type=Path, default=None,
                    help="unused; the service derives models/ from --data-root")
    ap.add_argument("--lib", required=True, type=Path)
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    sys.path.insert(0, str(args.repo))
    sys.path.insert(0, "/opt/sophon/sophon-opencv-latest/opencv-python")
    # Absolute, because the worker is spawned with the repository as its cwd and
    # a relative --native-lib resolves against *that*, not against this script's
    # caller. The failure is a dlopen error in the worker log, which reads like
    # a missing library rather than a path that needs `resolve()`.
    args.lib = args.lib.resolve()
    args.repo = args.repo.resolve()

    import httpx

    from board_acceptance import BOX_TOLERANCE_PX, TEXT_AGREEMENT_MIN, VERTICAL
    from board_acceptance import (_bm_smi_used_mib, _box_deviation, _match_rate,
                                  _pair_by_text)

    repo = args.repo
    img_dir = repo / "tests" / "data" / "ocr" / "img"
    golden = json.loads((repo / "tests" / "data" / "ocr" / "golden.json")
                        .read_text(encoding="utf-8"))
    det_golden = {e["image"]: e for e in golden["ppocr"]["det"]["images"]}
    rec_golden = {e["image"]: e for e in golden["ppocr"]["rec"]["images"]}

    # --data-root makes the service derive models/ from the root, so the root
    # has to be the directory the bmodels are already in. Pointing it at a fresh
    # tree instead would start a service with no models, and the first assertion
    # below would report that rather than testing anything.
    data_root = Path("/data/ocr-test")
    log = open("/data/ocr-test/service.log", "wb")
    env = dict(os.environ)
    env["CV84X6_LLM_LIB"] = str(args.lib)
    env["PYTHONPATH"] = os.environ.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.main", "--backend", "native",
         "--port", str(args.port), "--host", "127.0.0.1",
         "--data-root", str(data_root), "--native-lib", str(args.lib)],
        cwd=str(repo), stdout=log, stderr=subprocess.STDOUT, env=env)
    base = f"http://127.0.0.1:{args.port}"
    try:
        with httpx.Client(timeout=120.0) as client:
            # -- wait for the service --
            for _ in range(120):
                try:
                    if client.get(f"{base}/healthz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                print("service did not start; see /data/ocr-test/service.log")
                return 1

            assert client.post(f"{base}/api/login",
                               json={"password": "admin"}).status_code == 200
            models = {m["id"]: m for m in
                      client.get(f"{base}/api/models").json()["models"]}
            assert "ppocrv6-medium" in models, (
                f"the model is not visible; models/ contains {sorted(models)}")
            assert models["ppocrv6-medium"]["kind"] == "ocr", models["ppocrv6-medium"]

            before = _bm_smi_used_mib()
            started = time.monotonic()
            r = client.post(f"{base}/api/models/ppocrv6-medium/load")
            load_seconds = time.monotonic() - started
            assert r.status_code == 200, r.text
            after_load = _bm_smi_used_mib()

            key = client.post(f"{base}/api/keys",
                              json={"name": "ocr-acceptance"}).json()["key"]
            auth = {"Authorization": f"Bearer {key}"}

            print(f"load {load_seconds:.1f}s; NPU {before} -> {after_load} MiB")
            header = (f"{'image':22s} {'lines':>5s} {'text':>8s} {'box±px':>7s} "
                      f"{'http':>9s}")
            print(header)
            print("-" * len(header))

            rows = []
            text_hits = text_total = 0
            per_box: list[float] = []
            for path in sorted(img_dir.glob("*.png")):
                name = path.name
                started = time.monotonic()
                resp = client.post(f"{base}/v1/ocr", headers=auth,
                                   files={"file": (name, path.read_bytes(),
                                                   "image/png")},
                                   data={"model": "ppocrv6-medium"})
                http_seconds = time.monotonic() - started
                assert resp.status_code == 200, f"{name}: {resp.text[:400]}"
                body = resp.json()

                want_lines = [ln["text"] for ln in rec_golden[name]["lines"]]
                hits, total = _match_rate([ln["text"] for ln in body["lines"]],
                                          want_lines)
                vertical = name in VERTICAL
                if not vertical:
                    text_hits += hits
                    text_total += total
                want_boxes = [(ln["text"],
                               det_golden[name]["boxes"][ln["box_index"]])
                              for ln in rec_golden[name]["lines"]]
                pairs, _unmatched = _pair_by_text(
                    [(ln["text"], ln["box"]) for ln in body["lines"]], want_boxes)
                devs = [max(max(abs(pa[0] - pb[0]), abs(pa[1] - pb[1]))
                            for pa, pb in zip(a, b)) for a, b in pairs]
                if not vertical:
                    per_box.extend(devs)
                worst = max(devs) if devs else None
                print(f"{name:22s} {len(body['lines']):5d} "
                      f"{hits:3d}/{total:<3d} "
                      f"{'n/a' if worst is None else f'{worst:.0f}':>7s} "
                      f"{http_seconds * 1000:8.0f}ms")
                rows.append({"image": name, "lines": len(body["lines"]),
                             "text_hits": hits, "text_total": total,
                             "box_max_deviation_px": worst,
                             "det_ms": body["usage"]["det_ms"],
                             "rec_ms": body["usage"]["rec_ms"],
                             "http_ms": round(http_seconds * 1000, 1)})

            agreement = text_hits / text_total if text_total else 0.0
            exact = sum(1 for d in per_box if d == 0.0)
            within = sum(1 for d in per_box if d <= BOX_TOLERANCE_PX)
            over = [d for d in per_box if d > BOX_TOLERANCE_PX]
            print()
            print(f"text agreement (horizontal): {text_hits}/{text_total} = "
                  f"{agreement:.1%} (bar {TEXT_AGREEMENT_MIN:.0%})")
            print(f"box deviation: {exact}/{len(per_box)} pixel-identical, "
                  f"{within}/{len(per_box)} within {BOX_TOLERANCE_PX:.0f} px; "
                  f"worst {max(per_box):.2f} px, "
                  f"median {statistics.median(per_box):.2f} px")
            print(f"peak NPU: {_bm_smi_used_mib()} MiB")
            ok = agreement >= TEXT_AGREEMENT_MIN and not over
            print()
            print("RESULT:", "PASS" if ok else "FAIL")

            if args.json_out is not None:
                args.json_out.write_text(json.dumps({
                    "load_seconds": round(load_seconds, 1),
                    "npu_used_before_mib": before,
                    "npu_used_after_load_mib": after_load,
                    "npu_used_peak_mib": _bm_smi_used_mib(),
                    "text_agreement": round(agreement, 4),
                    "boxes_total": len(per_box),
                    "boxes_exact": exact,
                    "boxes_within_budget": within,
                    "boxes_over_budget": len(over),
                    "images": rows,
                }, ensure_ascii=False, indent=1), encoding="utf-8")

            client.post(f"{base}/api/models/ppocrv6-medium/unload")
            time.sleep(0.5)
            print(f"NPU after unload: {_bm_smi_used_mib()} MiB")
            return 0 if ok else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
