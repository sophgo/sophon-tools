"""The acceptance gates themselves, on fakes that fail in the reviewed ways.

``fix_acceptance.py`` is the tool that decides whether the WeMM encoder may ship:
its verdict is the evidence a reviewer reads instead of re-running the board. So
the gates have to be tested against inputs that are wrong *in the specific ways
the acceptance review found*, not just against a happy path.

Each test below is a regression for a hole that was actually reported:

* the repeat matrix replayed shapes after bucket switches but compared nothing,
  so an encoder that answered differently only on revisits passed with zero
  failures;
* the numeric gate only asked ``cosine < 0.99``, and ``NaN < 0.99`` is False, so
  an all-zero reference produced six NaNs, ``compared = 1`` and no failures;
* required boundary cases that silently dropped out shrank the set the claim
  "every sample >= 0.99" was made over.

These run on a plain host with no NPU and no model: the fake stands in for the
encoder, exactly as the reviewer's reproduction did.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "vl_embed"))
import fix_acceptance as fa  # noqa: E402


class FakeEncoder:
    """An encoder whose answers a test can corrupt at a chosen point.

    ``mutate_revisits`` reproduces the reviewed hole precisely: every ordinary
    call returns the correct vector, and only a *revisit* (a call made after
    other shapes ran) returns a different one. The old tool compared nothing on
    revisits, so that fake passed.
    """

    def __init__(self, *, mutate_revisits=False, mutate_after=None,
                 bad_reference=False, fault_at=None):
        self.fault = False
        self.buckets = [128, 512, 1024, 2048]
        self.mutate_revisits = mutate_revisits
        self.mutate_after = mutate_after
        self.bad_reference = bad_reference
        self.fault_at = fault_at
        self.calls = 0
        self.revisits = 0
        self.seen_shapes: set[str] = set()
        self._current: str | None = None

    def _bucket_for(self, text, png):
        if text == fa.LONG_2048 or png == b"1280x1024":
            return 2048
        if text == fa.LONG_1024:
            return 1024
        if text == fa.LONG_512 or png:
            return 512
        return 128

    def encode(self, text="", png=None, keep_vector=False, ids=None):
        self.calls += 1
        if self.fault_at is not None and self.calls > self.fault_at:
            self.fault = True
            return dict(ok=False, finite=False, norm=0.0,
                        error="NPU engine faulted; reload required")
        if self.fault:
            return dict(ok=False, finite=False, norm=0.0,
                        error="NPU engine faulted; reload required")
        bucket = self._bucket_for(text, png)
        # A stable vector per distinct input, so "the same input" really is the
        # same input and a difference cannot be blamed on the fake.
        seed = (text or "") + "|" + (png.decode("latin-1") if png else "")
        base = 1.0 + (abs(hash(seed)) % 7)
        vec = [base, 0.0, 1.0, 0.0]
        # A revisit is a call for a shape this fake has already served, issued
        # after at least one other shape ran in between.
        if seed in self.seen_shapes and self._current is not None and self._current != seed:
            self.revisits += 1
            if self.mutate_revisits:
                vec = [0.0, base, 0.0, 1.0]  # a different vector, same input
        self.seen_shapes.add(seed)
        self._current = seed
        return dict(ok=True, finite=True, norm=base, tokens=bucket, bucket=bucket,
                    vec=vec if keep_vector else [0.0] * len(vec),
                    total_ms=1.0, embedding_ms=0.1, vision_ms=0.0,
                    encoder_ms=0.9)


def _patch_png(monkeypatch):
    """Keep the fixture cheap: the fake never decodes a picture."""
    monkeypatch.setattr(fa, "make_png", lambda h, w, seed: f"{h}x{w}".encode())


# -- gate 1: switch equality --------------------------------------------------

def test_revisit_equality_is_actually_compared(monkeypatch):
    """The reviewed hole: a wrong answer only on revisits must fail the gate.

    The reviewer's fake changed the vector from [1,0] to [0,1] on revisits only
    and ``repeat_matrix`` still returned no failures. This is that fake, made
    explicit about what a revisit is.
    """
    _patch_png(monkeypatch)
    enc = FakeEncoder(mutate_revisits=True)
    result = fa.repeat_matrix(enc, "revisit-mutation", 2)
    assert enc.revisits > 0, "the fixture never produced a revisit"
    assert result["failures"], "a changed vector on a revisit passed the gate"
    assert result["revisit_failures"] > 0
    assert any("revisit" in f and "differs" in f for f in result["failures"])
    assert any(not r["matches_baseline"] for r in result["revisits"])


def test_a_correct_encoder_passes_and_every_revisit_matches(monkeypatch):
    """The gate must not be a wall: a stable encoder passes, with revisits run."""
    _patch_png(monkeypatch)
    enc = FakeEncoder()
    result = fa.repeat_matrix(enc, "stable", 2)
    assert result["failures"] == []
    assert result["revisit_requests"] > 0
    assert result["revisit_failures"] == 0
    assert all(r["matches_baseline"] for r in result["revisits"])


def test_revisits_are_counted_as_real_requests(monkeypatch):
    """A revisit is a request, not free: it must appear in the accounting."""
    _patch_png(monkeypatch)
    enc = FakeEncoder()
    result = fa.repeat_matrix(enc, "accounting", 2)
    base_calls = sum(shape["calls"] for shape in result["shapes"])
    assert result["revisit_requests"] > 0
    assert result["valid_requests"] == base_calls + result["revisit_requests"]


def test_a_run_with_no_revisit_fails(monkeypatch):
    """Switch equality is untested without a revisit, and untested is not pass."""
    _patch_png(monkeypatch)
    monkeypatch.setattr(fa, "REVISIT_AFTER", ())
    enc = FakeEncoder()
    result = fa.repeat_matrix(enc, "no-revisit", 1)
    assert result["revisit_requests"] == 0
    assert any("no revisit was issued" in f for f in result["failures"])


def test_revisits_cover_images_after_text_and_bucket_returns(monkeypatch):
    """The revisit set must span the transitions the field failure needed.

    Concretely: an image revisited after text (image -> text -> image), a
    different-sized image revisited, and a return to an earlier bucket.
    """
    _patch_png(monkeypatch)
    enc = FakeEncoder()
    result = fa.repeat_matrix(enc, "coverage", 2)
    revisited = {r["shape"] for r in result["revisits"]}
    buckets = {r["bucket"] for r in result["revisits"]}
    assert {"short-en", "image", "image-alt"} <= revisited, revisited
    assert len(buckets) >= 2, f"revisits stayed in one bucket: {buckets}"
    # Every revisit happened after a *different* shape, which is the ordering
    # that makes it a switch rather than a repeat.
    assert all(r["after"] != r["shape"] for r in result["revisits"])


def test_an_engine_that_faults_mid_matrix_is_reported(monkeypatch):
    """A fault during the matrix is a failure, not a truncated pass."""
    _patch_png(monkeypatch)
    enc = FakeEncoder(fault_at=3)
    result = fa.repeat_matrix(enc, "fault", 2)
    assert result["failures"]


# -- gate 3: the numeric threshold --------------------------------------------

def _write_reference(tmp_path: Path, rows, name="ref.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps({"rows": rows}))
    return path


class NumericEncoder:
    def __init__(self, vec):
        self.vec = vec
        self.buckets = [128, 512, 1024, 2048]
        self.fault = False

    def encode(self, **kwargs):
        vec = list(self.vec)
        return dict(ok=True, finite=True, norm=math.sqrt(sum(x * x for x in vec)),
                    vec=vec, tokens=8, bucket=128)


def test_an_all_zero_reference_fails_instead_of_scoring_nan(tmp_path):
    """The reviewed hole: NaN cosines were counted as compared and as passing.

    A legal finite output against an all-zero reference gives six NaN cosines.
    ``NaN < 0.99`` is False, so the old gate recorded ``compared = 1`` and no
    failures. A broken reference must fail, and it must not be counted.
    """
    ref = _write_reference(tmp_path, [{
        "id": "invalid-zero-reference", "type": "text",
        "input_ids": [1], "vector": [0.0] * 2048}])
    result = fa.reference_comparison(NumericEncoder([1.0] * 2048), ref, None, None)
    assert result["failures"], "an all-zero reference passed the numeric gate"
    assert result["compared"] == 0, "an unusable reference was counted as compared"
    assert all(v is None for v in result["worst"].values())
    assert any("unusable" in f for f in result["failures"])


def test_a_nan_output_fails_instead_of_scoring_nan(tmp_path):
    """A non-finite *output* must fail too, for the same reason."""
    ref = _write_reference(tmp_path, [{
        "id": "ok-ref", "type": "text", "input_ids": [1],
        "vector": [1.0] + [0.0] * 2047}])
    vec = [float("nan")] * 2048
    result = fa.reference_comparison(NumericEncoder(vec), ref, None, None)
    assert result["failures"]
    assert result["compared"] == 0


def test_a_zero_output_fails(tmp_path):
    ref = _write_reference(tmp_path, [{
        "id": "ok-ref", "type": "text", "input_ids": [1],
        "vector": [1.0] + [0.0] * 2047}])
    result = fa.reference_comparison(NumericEncoder([0.0] * 2048), ref, None, None)
    assert result["failures"]
    assert result["compared"] == 0


def test_a_dimension_mismatch_fails(tmp_path):
    ref = _write_reference(tmp_path, [{
        "id": "ok-ref", "type": "text", "input_ids": [1],
        "vector": [1.0] + [0.0] * 2047}])
    result = fa.reference_comparison(NumericEncoder([1.0] * 1024), ref, None, None)
    assert result["failures"]
    assert result["compared"] == 0


def test_a_genuinely_close_vector_still_passes(tmp_path):
    """The gate must still accept a correct answer, or it proves nothing."""
    expected = [1.0] + [0.0] * 2047
    ref = _write_reference(tmp_path, [{
        "id": "ok-ref", "type": "text", "input_ids": [1], "vector": expected}])
    result = fa.reference_comparison(NumericEncoder(expected), ref, None, None)
    assert result["failures"] == []
    assert result["compared"] == 1
    assert all(v == pytest.approx(1.0) for v in result["worst"].values())


def test_a_distant_vector_still_fails_the_threshold(tmp_path):
    expected = [1.0] + [0.0] * 2047
    far = [0.0, 1.0] + [0.0] * 2046
    ref = _write_reference(tmp_path, [{
        "id": "ok-ref", "type": "text", "input_ids": [1], "vector": expected}])
    result = fa.reference_comparison(NumericEncoder(far), ref, None, None)
    assert any("cosine" in f and "< 0.99" in f for f in result["failures"])


def test_a_required_case_that_is_missing_fails_the_gate(tmp_path):
    """A dropped boundary case must fail, not shrink the set the claim covers."""
    ref = _write_reference(tmp_path, [{
        "id": "text-128", "type": "text", "input_ids": [1],
        "vector": [1.0] + [0.0] * 2047}])
    result = fa.reference_comparison(
        NumericEncoder([1.0] + [0.0] * 2047), ref, None, None,
        required=["text-128", "tiny-alpha"])
    assert "tiny-alpha" in result["required_missing"]
    assert any("required case was not compared" in f for f in result["failures"])


def test_required_cases_present_do_not_fail(tmp_path):
    ref = _write_reference(tmp_path, [{
        "id": "text-128", "type": "text", "input_ids": [1],
        "vector": [1.0] + [0.0] * 2047}])
    result = fa.reference_comparison(
        NumericEncoder([1.0] + [0.0] * 2047), ref, None, None,
        required=["text-128"])
    assert result["required_missing"] == []
    assert result["failures"] == []


def test_a_gate_that_compared_nothing_fails(tmp_path):
    """An empty reference set must never read as a pass."""
    ref = _write_reference(tmp_path, [])
    result = fa.reference_comparison(NumericEncoder([1.0] * 2048), ref, None, None)
    assert result["failures"]


def test_boundary_images_are_paired_from_the_fixture_manifest(tmp_path):
    """The picture attached to a boundary reference must come from its manifest.

    Guessing a filename from the case id would silently score the encoder
    against a different picture, which is worse than skipping the case.
    """
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "tiny-alpha.png").write_bytes(b"\x89PNG not really")
    (fixtures / "eval.json").write_text(json.dumps({"entries": [
        {"id": "tiny-alpha", "type": "image", "image": "tiny-alpha.png"}]}))
    mapping = fa._boundary_image_map(fixtures)
    assert mapping["tiny-alpha"] == fixtures / "tiny-alpha.png"
    assert fa._boundary_image_map(None) == {}
    assert fa._boundary_image_map(tmp_path / "nope") == {}
