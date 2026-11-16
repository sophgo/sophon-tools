"""The memory-limit arithmetic (MYS-2675), without a service around it.

Two properties matter and they pull in opposite directions, which is why they
are pinned here rather than only through the API:

* the derived default must be **reachable** -- large enough for every model this
  release ships, so nobody has to raise a limit to load something that works;
* it must be **tight enough to mean something** -- a default of "the whole card"
  would make the per-model ceiling decorative.

The estimate itself (`bmrt_get_bmodel_info` minus its over-declared dynamic IO)
is what these tests can check off-device; the measured replacement is pinned in
`test_model_settings.py` and was validated on the board.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import mem_limit
from app.core.mem_limit import (
    DEFAULT_MAX_TOKENS, DEFAULT_PROMPT_TOKENS, DEFAULT_ROUND_BYTES, RUNTIME_HEADROOM,
)


class Info:
    """The subset of ``ModelInfo`` the arithmetic reads."""

    def __init__(self, kind: str = "chat", size_bytes: int = 1024,
                 context_length: int = 8192, bmodel_files=None, path: str = "/nonexistent"):
        self.model_id = "m"
        self.kind = kind
        self.size_bytes = size_bytes
        self.context_length = context_length
        self.bmodel_files = list(bmodel_files or [])
        self.path = path


def test_the_rounding_is_up_to_64_mib():
    assert mem_limit.round_up(0) == DEFAULT_ROUND_BYTES
    assert mem_limit.round_up(1) == DEFAULT_ROUND_BYTES
    assert mem_limit.round_up(DEFAULT_ROUND_BYTES) == DEFAULT_ROUND_BYTES
    assert mem_limit.round_up(DEFAULT_ROUND_BYTES + 1) == 2 * DEFAULT_ROUND_BYTES


def test_the_static_estimate_falls_back_to_the_file_size(tmp_path: Path):
    """No bmodel_files is the "files vanished" case; the recorded size stands in."""
    info = Info(size_bytes=12345)
    assert mem_limit.estimate_static_bytes(info) == 12345


def test_the_static_estimate_reads_the_files_it_has(tmp_path: Path):
    model = tmp_path / "m"
    model.mkdir()
    (model / "a.bmodel").write_bytes(b"\x00" * 1000)
    info = Info(bmodel_files=["a.bmodel"], path=str(model), size_bytes=999999)
    # libbmrt is absent on a host, so this is the file-size fallback -- which is
    # the branch that has to work in CI.
    assert mem_limit.estimate_static_bytes(info) == 1000


def test_the_default_is_static_plus_runtime_rounded_up():
    info = Info(kind="embedding", size_bytes=1000)
    default = mem_limit.default_limit_bytes(info, max_concurrent=1)
    static = mem_limit.estimate_static_bytes(info)
    runtime = mem_limit.runtime_allowance_bytes(info, max_concurrent=1)
    assert default == mem_limit.round_up(static + runtime)
    assert default >= static + runtime


def test_a_chat_default_scales_with_concurrency():
    """Two sessions cost more than one, and the default has to say so."""
    info = Info(kind="chat", size_bytes=1000, context_length=131072)
    one = mem_limit.default_limit_bytes(info, max_concurrent=1)
    two = mem_limit.default_limit_bytes(info, max_concurrent=2)
    assert two > one
    # The difference is exactly one more session's KV, rounded.
    delta = two - one
    assert delta == mem_limit.round_up(
        mem_limit.runtime_allowance_bytes(info, max_concurrent=2)
        - mem_limit.runtime_allowance_bytes(info, max_concurrent=1))


def test_an_auxiliary_default_does_not_scale_with_concurrency():
    """Those engines hold no cross-request KV: one call is one forward."""
    info = Info(kind="rerank", size_bytes=1000)
    assert (mem_limit.default_limit_bytes(info, max_concurrent=1)
            == mem_limit.default_limit_bytes(info, max_concurrent=3))


def test_the_prompt_budget_is_capped_by_the_context():
    """Budgeting 2560 tokens for a 512-token model would over-state it 5x."""
    small = Info(kind="asr", context_length=512)
    assert mem_limit.prompt_completion_tokens(small) == 512
    big = Info(kind="chat", context_length=131072)
    assert mem_limit.prompt_completion_tokens(big) == (
        DEFAULT_PROMPT_TOKENS + DEFAULT_MAX_TOKENS)


def test_the_allowance_carries_ten_percent_headroom():
    info = Info(kind="ocr", size_bytes=1000)
    raw = mem_limit.AUX_WORKING_BYTES["ocr"]
    allowance = mem_limit.runtime_allowance_bytes(info, max_concurrent=1)
    assert allowance == int(raw * (1.0 + RUNTIME_HEADROOM))


def test_the_default_of_a_shipped_model_is_within_the_board():
    """Sanity against the real figures, so a typo in a constant is caught here.

    The 128k 35B build is 19.7 GiB as a file and holds ~22.2 GiB once loaded
    (measured on `.155`, 2026-11-07). Its derived default must be at least the
    file size (a smaller one would refuse the load outright) and comfortably
    under the card's 34 GiB, or it would be unreachable. The exact figure moves
    between the estimate (before the first load) and the measurement (after),
    which is why this is a band rather than a number.
    """
    file_bytes = 19682 * 2**20
    info = Info(kind="chat", size_bytes=file_bytes, context_length=131072)
    default = mem_limit.default_limit_bytes(info, max_concurrent=2)
    assert default >= file_bytes
    assert default < 30 * 2**30


def test_the_default_with_the_measured_static_figure_covers_the_35b():
    """Once loaded, the static figure is the measurement: 22.2 GiB on `.155`.

    The default that comes out must still hold the model plus two sessions,
    which is what "existing cases keep working" means for the largest build.
    """
    measured = 22752 * 2**20
    info = Info(kind="chat", size_bytes=19682 * 2**20, context_length=131072)
    default = mem_limit.default_limit_bytes(info, max_concurrent=2, static=measured)
    assert default >= measured
    assert default < 30 * 2**30


def test_the_runtime_budget_is_the_limit_minus_static():
    assert mem_limit.runtime_budget_bytes(1000, 300) == 700


def test_the_runtime_budget_floors_at_zero():
    """A limit under the static footprint leaves nothing; the load check refuses it."""
    assert mem_limit.runtime_budget_bytes(100, 300) == 0


def test_a_kind_with_no_table_entry_still_gets_a_buffer():
    """A future kind must not derive a default of zero."""
    info = Info(kind="something-new", size_bytes=1000)
    allowance = mem_limit.runtime_allowance_bytes(info, max_concurrent=1)
    assert allowance > 0


def test_the_fallback_session_cost_matches_the_engine():
    """The 35B's real figures, read off `llm_engine_kv_bytes_per_token` on `.155`.

    40 layers, of which 10 are full attention: 20 KiB per token of KV and a
    fixed 31.9 MiB linear state. Deriving "35B at bf16 => 2 MiB/token" would
    over-budget the default by two orders of magnitude.
    """
    per_tok, linear = mem_limit._FALLBACK_SESSION["chat"]
    assert per_tok == 20480
    assert linear == 33423360


def test_bmodel_info_reports_none_without_the_library():
    """A host has no libbmrt; that is an answer, not an exception."""
    assert mem_limit.bmodel_info("/does/not/exist.bmodel") is None
