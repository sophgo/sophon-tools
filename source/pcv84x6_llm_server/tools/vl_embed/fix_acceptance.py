#!/usr/bin/env python3
"""MYS-2914: the 0.6.38 fix's board acceptance matrix, one encoder handle deep.

This is the *fixed* engine's acceptance run, not a diagnostic. It answers the
three questions the delivery has to answer with numbers:

1. **No failures.** A repeat matrix over text (short and long), pictures, and
   picture+text, across every compiled bucket, with the same input repeated and
   a return to an earlier bucket. Every vector must be finite, non-zero and
   reproducible; nothing may fault.
2. **The numbers are still right.** The same inputs are compared against the
   pinned official FP32 reference (``WeMM-evidence-FP32-reference``), sample by
   sample, at all six MRL widths. A fix that made the engine deterministic but
   wrong would pass (1) and fail here.
3. **What the sync costs.** Per-shape p50/p95 after warm-up, so the price of
   the completion-order fix is a number rather than a claim.

Everything runs through the public ``cv_vle_*`` C API on the library under
test, in this process, with the model opened read-only. It never talks to the
production service.

Usage::

    python3 tools/vl_embed/fix_acceptance.py \\
        --library <pkg>/lib/libcv84x6_llm.so \\
        --config <pkg>/model-config/wemm_embedding \\
        --model /data/.../wemm-embedding-2b_....bmodel \\
        --reference wemm-fp32-216.json \\
        --reference-boundary wemm-fp32-boundary.json \\
        --out fix-acceptance.json

Exit codes: 0 every gate held; 1 a gate failed (the report says which); 2 the
run could not be set up (missing file, bad arguments) -- never conflated with a
finding.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repeat_probe import Encoder, make_png  # noqa: E402

# The six official MRL widths. WeMM's head is trained for exactly these.
MRL = (64, 128, 256, 512, 1024, 2048)
# The acceptance threshold from docs/wemm-embedding.md: every sample, every
# width, cosine >= 0.99 against the FP32 reference.
MIN_COSINE = 0.99

SHORT_EN = "A photograph of a meal on a wooden table."
SHORT_ZH = "一只猫趴在窗台上晒太阳。"
# One sentence is ~10 tokens with this tokenizer, so these repeat counts land in
# 512 / 1024 / 2048 respectively. The run prints each shape's real token count
# and asserts every compiled bucket was exercised: a length that silently lands
# in the wrong bucket would leave a graph untested while looking exercised,
# which is exactly what the first draft of this file did.
_SENTENCE = "The quick brown fox jumps over the lazy dog."
LONG_512 = " ".join([_SENTENCE] * 20)     # ~205 tokens
LONG_1024 = " ".join([_SENTENCE] * 70)    # ~707 tokens
LONG_2048 = " ".join([_SENTENCE] * 190)   # ~1920 tokens

# (name, HxW) -- deliberately varied aspect ratios and pixel counts, so the ViT
# sees more than one patch grid and the buckets are reached from both sides.
# The last one is at the compiled maximum of 1310720 pixels: 1280 image tokens
# push the request into the 2048 bucket through the *image* path, which is the
# path the field failure took.
IMAGES = [
    ("img-384x512", 384, 512),
    ("img-512x384", 512, 384),
    ("img-256x256", 256, 256),
    ("img-352x480", 352, 480),
    ("img-max-1280x1024", 1280, 1024),
]


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else float("nan")


def vec_digest(vec) -> str:
    return hashlib.sha256(struct.pack("<%df" % len(vec), *vec)).hexdigest()[:16]


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    # Nearest-rank, which is what the earlier reports used; documented so a
    # reader can reproduce the figure from the raw list in the report.
    k = max(0, min(len(ordered) - 1, int(math.ceil(p / 100.0 * len(ordered))) - 1))
    return ordered[k]


def ok(rec) -> bool:
    return bool(rec.get("ok")) and rec.get("finite", False) and rec.get("norm", 0) > 0


# ---------------------------------------------------------------------------
# 1. the repeat matrix
# ---------------------------------------------------------------------------
def repeat_matrix(enc: Encoder, processes_note: str, per_shape: int) -> dict:
    """Every shape, every bucket, repeats and a return to an earlier bucket.

    The order is deliberate: text -> picture -> picture+text -> long text, then
    the *same* inputs again, so a request can land on a bucket an earlier one
    used and a later one can come back to it. The field failure showed up on
    exactly those transitions.
    """
    png = {name: make_png(h, w, 20261116 + i)
           for i, (name, h, w) in enumerate(IMAGES)}
    shapes = [
        ("short-en", {"text": SHORT_EN}),
        ("short-zh", {"text": SHORT_ZH}),
        ("image", {"png": png["img-384x512"]}),
        ("image-alt", {"png": png["img-512x384"]}),
        ("image-square", {"png": png["img-256x256"]}),
        ("image+text", {"text": SHORT_EN, "png": png["img-352x480"]}),
        ("image-max", {"png": png["img-max-1280x1024"]}),
        ("long-512", {"text": LONG_512}),
        ("long-1024", {"text": LONG_1024}),
        ("long-2048", {"text": LONG_2048}),
    ]
    result = {"note": processes_note, "per_shape": per_shape, "shapes": [],
              "failures": [], "buckets_seen": []}
    first_digest: dict[str, str] = {}
    first_vector: dict[str, list] = {}
    for name, item in shapes:
        latencies, digests, vectors = [], [], []
        entry = {"shape": name, "tokens": None, "bucket": None, "calls": 0}
        for index in range(per_shape):
            if enc.fault:
                result["failures"].append(f"{name}: engine faulted before call {index}")
                break
            rec = enc.encode(text=item.get("text", ""), png=item.get("png"),
                             keep_vector=True)
            entry["calls"] += 1
            if entry["tokens"] is None:
                entry["tokens"] = rec.get("tokens")
                entry["bucket"] = rec.get("bucket")
                if rec.get("bucket") not in result["buckets_seen"]:
                    result["buckets_seen"].append(rec.get("bucket"))
            if not ok(rec):
                result["failures"].append(
                    f"{name}[{index}]: {rec.get('error') or 'not ok'} "
                    f"norm={rec.get('norm')} finite={rec.get('finite')}")
                continue
            vec = rec["vec"]
            latencies.append(rec["total_ms"])
            digests.append(vec_digest(vec))
            vectors.append(vec)
            if name not in first_digest:
                first_digest[name] = digests[-1]
                first_vector[name] = vec
            elif name in first_vector and len(first_vector[name]) == len(vec):
                c = cosine(first_vector[name], vec)
                if c < MIN_COSINE:
                    result["failures"].append(
                        f"{name}[{index}]: repeat cosine {c:.9f} < {MIN_COSINE}")
        entry["distinct_digests"] = len(set(digests))
        # The digest itself, so a second process can check that the same input
        # produced the same bytes across a fresh handle, not just within one.
        entry["digest"] = digests[0] if digests else None
        entry["norm"] = round(math.sqrt(sum(x * x for x in vectors[0])), 9) if vectors else None
        entry["p50_ms"] = percentile(latencies, 50)
        entry["p95_ms"] = percentile(latencies, 95)
        entry["latencies_ms"] = [round(x, 1) for x in latencies]
        # Repeat equality is asserted on the exact bytes, not a tolerance: the
        # same input on the same model must reproduce, and "close enough" would
        # hide the defect this release fixes.
        if entry["distinct_digests"] > 1:
            result["failures"].append(
                f"{name}: {entry['distinct_digests']} distinct vectors over "
                f"{entry['calls']} identical requests")
        result["shapes"].append(entry)
        # Return to an earlier bucket: replay every shape already seen, so the
        # last request of this block re-enters a bucket it left.
        if name in ("image-max", "long-1024"):
            for earlier, earlier_item in shapes[:shapes.index((name, item)) + 1]:
                if enc.fault:
                    break
                rec = enc.encode(text=earlier_item.get("text", ""),
                                 png=earlier_item.get("png"))
                if not ok(rec):
                    result["failures"].append(
                        f"return-to-{earlier}: {rec.get('error') or 'not ok'}")
    # Every compiled graph must have been exercised, or "the buckets all pass"
    # would be a claim about graphs the run never touched. The expectation is
    # read from the engine, not hard-coded: 128/512/1024/2048 for a model with
    # the middle bucket, and whatever subset the bmodel actually compiled.
    expected = {str(b) for b in enc.buckets}
    seen = {str(b) for b in result["buckets_seen"]}
    if seen != expected:
        result["failures"].append(
            f"buckets exercised {sorted(seen)} != compiled {sorted(expected)}")
    return result


# ---------------------------------------------------------------------------
# 2. the FP32 reference comparison
# ---------------------------------------------------------------------------
def _reference_rows(path: Path) -> list[dict]:
    payload = json.loads(path.read_text())
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"{path} has no rows list")
    return rows


def reference_comparison(enc: Encoder, reference: Path, boundary: Path | None,
                         image_dir: Path | None) -> dict:
    """Re-embed each reference case and compare at all six MRL widths.

    The reference rows carry the exact token ids the official processor
    produced, and the engine is fed those ids verbatim, so this compares *the
    encoder* rather than a tokenizer or prompt-rendering difference. The image
    is still preprocessed by this engine; the engine itself then rejects the
    request if its grid disagrees with the ids' image_pad span, which is how a
    preprocessing drift surfaces instead of being silently compared.

    A row whose image file is not available is reported as skipped, never as
    passed.
    """
    out = {"reference": str(reference), "rows": 0, "compared": 0,
           "by_type": {}, "skipped": [], "worst": {str(d): None for d in MRL},
           "worst_case": {}, "failures": []}
    for path in [p for p in (reference, boundary) if p]:
        if not path.exists():
            out["skipped"].append(f"{path}: missing")
            continue
        for row in _reference_rows(path):
            out["rows"] += 1
            kind = row.get("type") or "?"
            ids = row.get("input_ids")
            expected = row.get("vector")
            case = row.get("id")
            if not expected:
                out["skipped"].append(f"{case}: no reference vector")
                continue
            if not ids:
                out["skipped"].append(f"{case}: no reference token ids")
                continue
            png = None
            if kind in ("image", "mixed"):
                # COCO rows are identified by their image id, which is the
                # `group` the reference kept; the file is the zero-padded name.
                group = row.get("group")
                candidate = (image_dir / f"{int(group):012d}.jpg") if (
                    image_dir and group is not None) else None
                if not candidate or not candidate.exists():
                    out["skipped"].append(f"{case}: image {group} unavailable")
                    continue
                png = candidate.read_bytes()
            rec = enc.encode(png=png, keep_vector=True, ids=ids)
            if not ok(rec):
                out["failures"].append(f"{case}: {rec.get('error') or 'not ok'}")
                continue
            vec = rec["vec"]
            if len(vec) != len(expected):
                out["failures"].append(
                    f"{case}: dimension {len(vec)} != {len(expected)}")
                continue
            out["compared"] += 1
            out["by_type"][kind] = out["by_type"].get(kind, 0) + 1
            for dim in MRL:
                c = cosine(vec[:dim], expected[:dim])
                if out["worst"][str(dim)] is None or c < out["worst"][str(dim)]:
                    out["worst"][str(dim)] = c
                    out["worst_case"][str(dim)] = case
                if c < MIN_COSINE:
                    out["failures"].append(
                        f"{case} @{dim}: cosine {c:.6f} < {MIN_COSINE}")
    return out


# ---------------------------------------------------------------------------
# 3. performance
# ---------------------------------------------------------------------------
def performance(enc: Encoder, warmup: int, rounds: int) -> dict:
    png = make_png(384, 512, 20261116)
    shapes = [("short-text", {"text": SHORT_EN}), ("long-text", {"text": LONG_1024}),
              ("image", {"png": png}), ("image+text", {"text": SHORT_EN, "png": png})]
    result = {"warmup": warmup, "rounds": rounds, "shapes": [], "failures": []}
    for name, item in shapes:
        for _ in range(warmup):
            if not ok(enc.encode(text=item.get("text", ""), png=item.get("png"))):
                result["failures"].append(f"{name}: warm-up call failed")
                break
        latencies = {"total": [], "embedding": [], "vision": [], "encoder": []}
        for _ in range(rounds):
            rec = enc.encode(text=item.get("text", ""), png=item.get("png"))
            if not ok(rec):
                # A failed round is not a latency sample; it is a finding.
                result["failures"].append(f"{name}: {rec.get('error') or 'not ok'}")
                continue
            latencies["total"].append(rec["total_ms"])
            latencies["embedding"].append(rec.get("embedding_ms", 0))
            latencies["vision"].append(rec.get("vision_ms", 0))
            latencies["encoder"].append(rec.get("encoder_ms", 0))
        result["shapes"].append({
            "shape": name,
            "n": len(latencies["total"]),
            **{f"{key}_p50_ms": percentile(values, 50)
               for key, values in latencies.items()},
            **{f"{key}_p95_ms": percentile(values, 95)
               for key, values in latencies.items()},
            "total_ms": [round(x, 1) for x in latencies["total"]],
        })
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--library", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--reference", type=Path)
    p.add_argument("--reference-boundary", type=Path)
    p.add_argument("--image-dir", type=Path,
                   help="directory holding the reference set's images")
    p.add_argument("--per-shape", type=int, default=10)
    p.add_argument("--rounds", type=int, default=30)
    p.add_argument("--warmup", type=int, default=2)
    p.add_argument("--process", type=int, default=0,
                   help="which fresh process this is (0-based); its report is "
                        "written beside --out and named for the index")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--skip-reference", action="store_true")
    a = p.parse_args()

    for required in (a.library, a.config, a.model):
        if not Path(required).exists():
            print(f"missing input: {required}", file=sys.stderr)
            return 2
    if not a.skip_reference and (not a.reference or not a.reference.exists()):
        print("--reference is required unless --skip-reference", file=sys.stderr)
        return 2

    report: dict = {"library": a.library, "library_sha256": _sha(a.library),
                    "model": a.model, "model_sha256": _sha(a.model),
                    "process": a.process,
                    "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    started = time.perf_counter()
    try:
        enc = Encoder(a.library, a.model, a.config)
    except Exception as exc:  # noqa: BLE001 - a load failure is a setup error
        print(f"encoder load failed: {exc}", file=sys.stderr)
        return 2
    report["load_s"] = round(enc.load_s, 2)
    report["seq"], report["hidden"], report["max_patches"] = (
        enc.seq, enc.hidden, enc.max_patches)
    report["compiled_buckets"] = enc.buckets
    try:
        report["repeat"] = repeat_matrix(enc, f"process {a.process}", a.per_shape)
        if not a.skip_reference:
            report["numeric"] = reference_comparison(
                enc, a.reference, a.reference_boundary, a.image_dir)
        report["performance"] = performance(enc, a.warmup, a.rounds)
        report["faulted_at_end"] = enc.fault
    finally:
        enc.close()
    report["elapsed_s"] = round(time.perf_counter() - started, 1)

    failures = list(report["repeat"]["failures"])
    if "numeric" in report:
        failures += report["numeric"]["failures"]
        if report["numeric"]["compared"] == 0:
            failures.append("no reference row could be compared")
    failures += report["performance"]["failures"]
    if report.get("faulted_at_end"):
        failures.append("engine faulted at the end of the run")
    report["failures"] = failures
    report["passed"] = not failures
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")

    print(f"buckets: {report['repeat']['buckets_seen']}")
    for shape in report["repeat"]["shapes"]:
        # A shape whose first call failed has no token/bucket figure; printing
        # the failure is the point of the row, so it must not crash the report.
        tokens = shape["tokens"] if shape["tokens"] is not None else "?"
        bucket = shape["bucket"] if shape["bucket"] is not None else "?"
        timing = (f"p50={shape['p50_ms']:.1f}ms p95={shape['p95_ms']:.1f}ms"
                  if shape["p50_ms"] is not None else "no successful call")
        print(f"  {shape['shape']:<14} tokens={tokens} bucket={bucket} "
              f"n={shape['calls']} distinct={shape['distinct_digests']} {timing}")
    if "numeric" in report:
        numeric = report["numeric"]
        print(f"reference: {numeric['compared']}/{numeric['rows']} compared, "
              f"{len(numeric['skipped'])} skipped")
        for dim in MRL:
            print(f"  MRL {dim:>4}: worst cosine {numeric['worst'][str(dim)]} "
                  f"({numeric['worst_case'].get(str(dim))})")
    for shape in report["performance"]["shapes"]:
        p50 = shape["total_p50_ms"]
        p95 = shape["total_p95_ms"]
        timing = (f"p50={p50}ms p95={p95}ms" if p50 is not None
                  else "no successful round")
        print(f"  perf {shape['shape']:<12} n={shape['n']} {timing}")
    if failures:
        print(f"FAILED ({len(failures)}):", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("PASS")
    return 0


def _sha(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
