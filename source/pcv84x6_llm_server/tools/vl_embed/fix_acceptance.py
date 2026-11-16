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
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repeat_probe import Encoder, make_png  # noqa: E402

# The six official MRL widths. WeMM's head is trained for exactly these.
MRL = (64, 128, 256, 512, 1024, 2048)
# The acceptance threshold from docs/wemm-embedding.md: every sample, every
# width, cosine >= 0.99 against the FP32 reference.
MIN_COSINE = 0.99
# After these shapes, replay every shape seen so far. Two points, not one, so a
# revisit happens while the encoder sits in a mid-sized bucket and again while
# it sits in the largest -- the transitions the field failure needed. Revisit
# equality is compared against the baseline vector, not merely re-run.
REVISIT_AFTER = ("image-max", "long-1024")

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


def max_abs(a, b) -> float:
    return max((abs(x - y) for x, y in zip(a, b)), default=float("nan"))


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
    """Every shape, every bucket, repeats and verified returns to earlier buckets.

    Two different questions, both answered on exact bytes:

    * **Repeat equality** -- the same input issued back to back must reproduce.
    * **Switch equality** -- the same input issued *after* the encoder has run
      other shapes (other buckets, other image sizes, images in between texts)
      must still reproduce. The field failure lived here: a bucket switch left
      the next request reading another request's buffer. A run that only repeats
      each shape consecutively cannot see that, because nothing intervenes.

    Every revisit therefore keeps its vector and compares it against the
    baseline recorded for that exact input. Revisits count as real requests in
    ``calls`` and in the failure accounting -- a revisit that silently skipped
    the comparison would be worse than no revisit at all.
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
              "failures": [], "buckets_seen": [], "revisits": [],
              "valid_requests": 0, "revisit_requests": 0,
              "revisit_failures": 0}
    # The baseline vector of every input, by shape name. Every later issue of
    # the same input -- repeat or revisit -- is compared against it.
    baseline: dict[str, list] = {}

    def compare(name: str, where: str, vec: list) -> None:
        """Assert ``vec`` equals the baseline recorded for ``name``."""
        reference = baseline.get(name)
        if reference is None:
            baseline[name] = vec
            return
        if len(vec) != len(reference):
            result["failures"].append(
                f"{where}: dimension {len(vec)} != baseline {len(reference)}")
            return
        if vec == reference:
            return
        # Not bit-identical: report how far off, so the reader can tell a
        # rounding difference from the defect this release fixes (which is a
        # completely different vector, not a last-bit one).
        c = cosine(reference, vec)
        result["failures"].append(
            f"{where}: vector differs from the baseline for the same input "
            f"(cosine {c:.9f}, max_abs {max_abs(reference, vec):.3e})")

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
            result["valid_requests"] += 1
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
            compare(name, f"{name}[{index}]", vec)
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
        # Return to every *earlier* shape once this block has moved the encoder
        # through other buckets and other image sizes. The current shape is
        # excluded on purpose: replaying it here would be another repeat, and a
        # repeat in place is exactly what this section exists to go beyond. The
        # revisit is issued after an intervening request, which is the ordering
        # the field failure needed.
        if name in REVISIT_AFTER:
            for earlier, earlier_item in shapes[:shapes.index((name, item))]:
                if enc.fault:
                    result["failures"].append(
                        f"revisit {earlier}: engine faulted before the revisit")
                    break
                rec = enc.encode(text=earlier_item.get("text", ""),
                                 png=earlier_item.get("png"), keep_vector=True)
                result["valid_requests"] += 1
                result["revisit_requests"] += 1
                if not ok(rec):
                    result["revisit_failures"] += 1
                    result["failures"].append(
                        f"revisit {earlier}: {rec.get('error') or 'not ok'} "
                        f"norm={rec.get('norm')} finite={rec.get('finite')}")
                    continue
                if earlier not in baseline:
                    result["revisit_failures"] += 1
                    result["failures"].append(
                        f"revisit {earlier}: no baseline to compare against")
                    continue
                before = len(result["failures"])
                compare(earlier, f"revisit {earlier} after {name}", rec["vec"])
                if len(result["failures"]) > before:
                    result["revisit_failures"] += 1
                result["revisits"].append({
                    "shape": earlier, "after": name,
                    "tokens": rec.get("tokens"), "bucket": rec.get("bucket"),
                    "digest": vec_digest(rec["vec"]),
                    "matches_baseline": len(result["failures"]) == before,
                })
    # Every compiled graph must have been exercised, or "the buckets all pass"
    # would be a claim about graphs the run never touched. The expectation is
    # read from the engine, not hard-coded: 128/512/1024/2048 for a model with
    # the middle bucket, and whatever subset the bmodel actually compiled.
    expected = {str(b) for b in enc.buckets}
    seen = {str(b) for b in result["buckets_seen"]}
    if seen != expected:
        result["failures"].append(
            f"buckets exercised {sorted(seen)} != compiled {sorted(expected)}")
    # A revisit that never happened is not a pass. This is the gate the first
    # version of this file lacked: it replayed shapes but compared nothing, so a
    # fake that changed its answer only on revisits passed with zero failures.
    if result["revisit_requests"] == 0:
        result["failures"].append("no revisit was issued; switch equality is untested")
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


def _finite_nonzero(vec) -> tuple[bool, str]:
    """Whether ``vec`` is a usable vector, and why not when it is not.

    A cosine is only meaningful between two finite vectors of non-zero norm.
    Without this check an all-zero reference, a NaN output or a length mismatch
    all turn into ``cosine = NaN``, and ``NaN < 0.99`` is False -- so the sample
    would be counted as compared *and* as passing. That is the exact hole the
    acceptance review found: a legal finite output scored against an all-zero
    reference produced six NaNs, ``compared = 1`` and no failures.
    """
    if not vec:
        return False, "empty vector"
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vec):
        return False, "non-finite component"
    norm = math.sqrt(sum(float(x) * float(x) for x in vec))
    if norm <= 0:
        return False, "zero norm"
    return True, ""


def _cosine_or_none(a, b) -> float | None:
    """Cosine, or None when the pair cannot produce a meaningful one."""
    usable_a, _ = _finite_nonzero(a)
    usable_b, _ = _finite_nonzero(b)
    if not usable_a or not usable_b or len(a) != len(b):
        return None
    c = cosine(a, b)
    return c if math.isfinite(c) else None


def _boundary_image_map(fixtures: Path | None) -> dict[str, Path]:
    """case id -> image file, from the boundary fixture set's own ``eval.json``.

    The reference rows keep the *token ids* and the vector but not the filename:
    the fixture set's ``eval.json`` is what pairs an id with its image. Reading
    that pairing from the fixtures keeps the association the generator wrote
    instead of guessing from the id, which would silently attach a different
    picture to a reference vector.
    """
    if not fixtures:
        return {}
    manifest = fixtures / "eval.json"
    if not manifest.exists():
        return {}
    entries = json.loads(manifest.read_text()).get("entries") or []
    return {entry["id"]: fixtures / entry["image"]
            for entry in entries if entry.get("image")}


def reference_comparison(enc: Encoder, reference: Path, boundary: Path | None,
                         image_dir: Path | None,
                         boundary_dir: Path | None = None,
                         required: Sequence[str] = ()) -> dict:
    """Re-embed each reference case and compare at all six MRL widths.

    The reference rows carry the exact token ids the official processor
    produced, and the engine is fed those ids verbatim, so this compares *the
    encoder* rather than a tokenizer or prompt-rendering difference. The image
    is still preprocessed by this engine; the engine itself then rejects the
    request if its grid disagrees with the ids' image_pad span, which is how a
    preprocessing drift surfaces instead of being silently compared.

    A row whose image file is not available is reported as skipped, never as
    passed. ``required`` names cases that must be compared for the run to claim
    the numeric gate passed at all: a boundary case that silently dropped out
    would otherwise leave "all samples >= 0.99" true over a smaller set.
    """
    out = {"reference": str(reference), "rows": 0, "compared": 0,
           "by_type": {}, "skipped": [], "worst": {str(d): None for d in MRL},
           "worst_case": {}, "failures": [], "rejected": [],
           "compared_cases": [], "required_missing": []}
    boundary_images = _boundary_image_map(boundary_dir)
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
            # The reference itself must be a usable vector. A broken reference
            # is a finding about the reference, not a pass for the engine.
            usable, why = _finite_nonzero(expected)
            if not usable:
                out["rejected"].append(f"{case}: reference vector unusable ({why})")
                out["failures"].append(
                    f"{case}: reference vector unusable ({why}); "
                    f"this sample cannot be compared")
                continue
            png = None
            if kind in ("image", "mixed"):
                # Two reference sets, two ways to name the picture. A COCO row
                # is identified by its image id, which the reference kept as
                # `group`, and the file is the zero-padded name. A boundary row
                # has no group, so its file comes from the fixture set's own
                # eval.json -- the pairing the generator wrote.
                candidate = None
                group = row.get("group")
                if image_dir and group is not None:
                    candidate = image_dir / f"{int(group):012d}.jpg"
                elif boundary_dir:
                    candidate = boundary_images.get(case)
                if not candidate or not candidate.exists():
                    out["skipped"].append(f"{case}: image unavailable")
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
            usable, why = _finite_nonzero(vec)
            if not usable:
                out["rejected"].append(f"{case}: output vector unusable ({why})")
                out["failures"].append(
                    f"{case}: output vector unusable ({why})")
                continue
            out["compared"] += 1
            out["compared_cases"].append(case)
            out["by_type"][kind] = out["by_type"].get(kind, 0) + 1
            for dim in MRL:
                c = _cosine_or_none(vec[:dim], expected[:dim])
                if c is None:
                    # Unreachable for a usable pair of equal length, but a
                    # silent None here would be the same hole in a new place.
                    out["failures"].append(
                        f"{case} @{dim}: cosine is not a finite number")
                    continue
                if out["worst"][str(dim)] is None or c < out["worst"][str(dim)]:
                    out["worst"][str(dim)] = c
                    out["worst_case"][str(dim)] = case
                if c < MIN_COSINE:
                    out["failures"].append(
                        f"{case} @{dim}: cosine {c:.6f} < {MIN_COSINE}")
    # Required coverage. "Every compared sample passed" says nothing about the
    # samples that never got compared, so the cases the gate is supposed to
    # cover are named and checked by name. A missing required case fails the
    # gate; it does not quietly shrink the set the claim is made over.
    compared_cases = set(out.get("compared_cases") or ())
    for case in required:
        if case not in compared_cases:
            out["required_missing"].append(case)
            out["failures"].append(
                f"{case}: required case was not compared "
                f"(no reference row, or its image was unavailable)")
    # A gate that compared nothing must never read as a pass.
    if out["compared"] == 0:
        out["failures"].append("no reference sample could be compared")
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
    p.add_argument("--boundary-dir", type=Path,
                   help="directory holding the boundary fixture set "
                        "(its eval.json pairs case ids with image files)")
    p.add_argument("--require", action="append", default=[], metavar="CASE",
                   help="a case id that MUST be compared for the numeric gate "
                        "to pass; repeatable")
    p.add_argument("--require-file", type=Path,
                   help="file listing required case ids, one per line "
                        "(blank lines and # comments ignored)")
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
            required = list(a.require)
            if a.require_file:
                for line in a.require_file.read_text().splitlines():
                    line = line.split("#", 1)[0].strip()
                    if line:
                        required.append(line)
            report["numeric"] = reference_comparison(
                enc, a.reference, a.reference_boundary, a.image_dir,
                boundary_dir=a.boundary_dir, required=required)
            report["numeric"]["required"] = required
            # Record what the reference was, so a reader can tell which files
            # produced these numbers rather than trusting a path string.
            report["numeric"]["reference_sha256"] = _sha(a.reference)
            if a.reference_boundary and a.reference_boundary.exists():
                report["numeric"]["reference_boundary_sha256"] = _sha(a.reference_boundary)
            report["numeric"]["boundary_fixtures"] = (
                str(a.boundary_dir) if a.boundary_dir else None)
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
