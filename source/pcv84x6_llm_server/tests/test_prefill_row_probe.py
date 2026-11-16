"""The prefill row probe: the parts that can be checked without an NPU.

MYS-2405's report has to show, for each case, the prefill width ``L`` the engine
actually ran and how many rows it replayed one at a time, to test the claim that
first-token cost tracks *replayed rows*, not prompt length. The probe gets those
two numbers by counting graph launches in the engine's ``LLM_TRACE`` output, and
trusts the layer count and ``max_input`` the engine reports at load. Every one of
those steps is arithmetic or parsing, so it is pinned here:

  * the classifier splits ``block_<i>`` / ``block_kv_<i>`` (dynamic prefill) from
    ``block_cache_<i>`` (single-row decode) and drops the per-chunk fixed costs,
    because a mis-split would silently inflate or deflate both row counts;
  * the division by layer count is what turns a launch count into a row count,
    so a trace with two layers must not read as one row per two launches;
  * ``predict()`` must agree with ``Session::prefill_impl``. It is deliberately
    a separate implementation: the report prints it *next to* the measured
    numbers so a mismatch is visible, which only works if the two are computed
    independently.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")
sys.path.insert(0, TOOLS)

import prefill_row_probe as probe  # noqa: E402


# --------------------------------------------------------------------------
# The launch classifier
# --------------------------------------------------------------------------
def test_prefill_and_decode_launches_are_counted_apart():
    """A 2-layer model: layer 0 uses ``block_``, layer 1 is an FA layer and uses
    ``block_kv_`` -- the engine picks one per layer, never both -- so two
    prefill launches is one row, and two ``block_cache_`` launches is one row."""
    launches = [("embedding", 1.0),
                ("block_0", 10.0), ("block_kv_1", 12.0),
                ("block_cache_0", 2.0), ("block_cache_1", 3.0),
                ("lm_head", 4.0)]
    c = probe.classify(launches)
    assert c["prefill_launches"] == 2, "block_/block_kv_ are both prefill graphs"
    assert c["decode_launches"] == 2
    assert c["prefill_layers"] == 2 and c["decode_layers"] == 2
    assert probe.rows_of(c, layers=2) == {"L": 1, "replay": 1,
                                          "prefill_ms": 22.0, "replay_ms": 5.0,
                                          "other_ms": 5.0}


def test_rows_divide_launches_by_the_layer_count_in_the_trace():
    """Two layers, 6 prefill launches, 2 decode launches -> L=3, replay=1."""
    launches = [("block_0", 1.0), ("block_1", 1.0)] * 3 + \
               [("block_cache_0", 1.0), ("block_cache_1", 1.0)]
    row = probe.rows_of(probe.classify(launches), layers=2)
    assert row["L"] == 3
    assert row["replay"] == 1


def test_a_missing_layer_index_does_not_divide_by_zero():
    """A trace with no layer 0 (an error path) still has to produce a number:
    fall back to the layer count the engine reported at load."""
    row = probe.rows_of(probe.classify([]), layers=40)
    assert row["L"] == 0 and row["replay"] == 0


def test_other_graphs_are_not_mistaken_for_layers():
    """``embedding`` / ``embedding_cache`` / ``lm_head`` are not layers; if they
    were counted as prefill rows the width would come out wrong for every case."""
    launches = [("block_0", 1.0), ("block_1", 1.0),
                ("embedding", 1.0), ("embedding_cache", 1.0), ("lm_head", 1.0)]
    c = probe.classify(launches)
    assert c["prefill_launches"] == 2
    assert c["decode_launches"] == 0


def test_parse_trace_reads_name_and_milliseconds():
    text = ("[engine] layers=40\n"
            "[launch] block_0 10.5 ms @1.000\n"
            "[launch] block_cache_0 2.25 ms (queued) @1.010\n"
            "noise that is not a launch\n")
    got = probe.parse_trace(text)
    assert got == [("block_0", 10.5), ("block_cache_0", 2.25)]


# --------------------------------------------------------------------------
# The formula the probe compares against
# --------------------------------------------------------------------------
def test_align_16_with_a_tail_replays_only_the_gap():
    """align=16, tail=8, n=67: L=64 (67//16*16=64, and 64 <= 59? no -- see
    below), replay=3. This is the case the card reasons about."""
    # 67 // 16 * 16 = 64; exact_from = 67-8 = 59; 64 > 59 so L = 59//16*16 = 48.
    assert probe.predict(67, 16, 8, 2048) == {"L": 48, "replay": 19}


def test_align_16_without_a_tail_is_the_plain_floor():
    assert probe.predict(67, 16, 0, 2048) == {"L": 64, "replay": 3}
    assert probe.predict(128, 16, 0, 2048) == {"L": 128, "replay": 0}


def test_align_16_tail_16_on_a_128_row_prompt():
    """exact_from = 112, 112//16*16 = 112 -> L=112, replay=16: the tail is exactly
    16 rows, which is the whole point of the combination the card asks about."""
    assert probe.predict(128, 16, 16, 2048) == {"L": 112, "replay": 16}


def test_align_64_tail_16_replays_64_rows_for_a_short_prompt():
    """The MYS-2403 measurement this stage is trying to beat: n=67 under
    align=64 + tail=16 gives L=0, i.e. all 67 rows replayed."""
    assert probe.predict(67, 64, 16, 2048) == {"L": 0, "replay": 67}


def test_a_prompt_longer_than_one_chunk_is_split():
    """max_input=64 here: 70 rows is a 64-row chunk then a 6-row chunk. The
    second chunk is shorter than the alignment, so all of it is replayed."""
    assert probe.predict(70, 16, 0, 64) == {"L": 64, "replay": 6}


def test_exact_tail_never_replays_more_than_the_prompt():
    got = probe.predict(10, 16, 100, 2048)
    assert got == {"L": 0, "replay": 10}


@pytest.mark.parametrize("n", [64, 65, 67, 128, 320, 452])
@pytest.mark.parametrize("align", [16, 64])
@pytest.mark.parametrize("tail", [0, 8, 16])
def test_L_plus_replay_is_always_the_prompt(n, align, tail):
    """The two counts have to add up: a table that reports L and replayed rows
    is claiming they partition the prompt, so this is the invariant to pin."""
    got = probe.predict(n, align, tail, 2048)
    assert got["L"] + got["replay"] == n
    assert got["L"] % align == 0
    assert min(got["L"], got["replay"]) >= 0


@pytest.mark.parametrize("tail", [0, 8, 16])
def test_align_16_replay_is_always_a_whole_number_of_aligned_rows_or_the_gap(tail):
    """With align=16 the replayed rows are the remainder under the *effective*
    floor, so replay < 2*align: at most one align-block plus one remainder.
    This is the mechanism the card says should make align 16 cheap."""
    for n in range(64, 500):
        got = probe.predict(n, 16, tail, 2048)
        assert got["replay"] < 32, (n, tail, got)
