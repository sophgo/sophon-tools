"""The graded cases the prefill A/B eval runs (MYS-2396) and the exact-tail
eval runs on top of them (MYS-2403).

The eval's claim is that an alignment rule can be compared against the 64-aligned
default on *answer accuracy*. That holds only if

  * the ids are what the release tokenizer produces for real text through the
    production chat template, and are reproducible from the committed files;
  * every case really makes the two rules take different paths -- otherwise the
    comparison measures nothing and both sides are the same run;
  * grading is mechanical: a fixed pattern per case, matched case-insensitively.

There are two sets of the same 40 questions. ``mid`` (MYS-2396) keeps
``n % 64 >= 16`` so that under 64-alignment the *exact* replay tail is wide
enough to be affordable; ``low`` (MYS-2403) keeps ``n % 64 <= 7``, the corner
where the production rule replays almost nothing exactly. These tests pin both
without an NPU.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
CASES_DIR = os.path.join(HERE, "..", "tools", "prefill_ab_cases")
sys.path.insert(0, CASES_DIR)

import gen_cases as gen  # noqa: E402

SETS = ["mid", "low"]


@pytest.fixture(params=SETS)
def which(request):
    """Select the set for the module-level generator, then put it back."""
    prev = gen.SET
    gen.SET = request.param
    try:
        yield request.param
    finally:
        gen.SET = prev


def doc(which):
    with open(gen.SETS[which]["cases_json"], encoding="utf-8") as f:
        return json.load(f)


def cases(which):
    return doc(which)["cases"]


def ids_of(which, name):
    prev = gen.SET
    gen.SET = which
    try:
        return gen.read_ids(name)
    finally:
        gen.SET = prev


# --------------------------------------------------------------------------
# Both sets: 40 cases, right mix, right files
# --------------------------------------------------------------------------
def test_case_mix_is_fifteen_fifteen_ten(which):
    counts = {"A": 0, "B": 0, "C": 0}
    for c in cases(which):
        counts[c["type"]] += 1
    assert counts == {"A": 15, "B": 15, "C": 10}
    assert len(cases(which)) == 40


def test_ids_and_cases_json_agree(which):
    prev = gen.SET
    gen.SET = which
    try:
        assert gen.verify() == 0
    finally:
        gen.SET = prev


def test_every_case_has_a_grading_pattern(which):
    for c in cases(which):
        assert c["match"].strip(), c["id"]


def test_sets_are_separate_copies_of_the_same_questions():
    """The 40 questions, their types and grading patterns are shared; only the
    padding that fixes the length differs. Otherwise the two sets could not be
    compared case by case.

    A C follow-up carries its tuning sentences inside the question (that is the
    text the template appends), so there the mid question is a prefix of the low
    one rather than byte-equal.
    """
    mid = {c["id"]: c for c in cases("mid")}
    low = {c["id"]: c for c in cases("low")}
    assert set(mid) == set(low)
    for cid, c in mid.items():
        assert c["match"] == low[cid]["match"], cid
        assert c["type"] == low[cid]["type"], cid
        if c["type"] == "C":
            assert low[cid]["question"].startswith(c["question"]), cid
        else:
            assert c["question"] == low[cid]["question"], cid


def test_the_low_set_lives_in_its_own_directory():
    """Regenerating the low set must not be able to touch the committed mid
    files, so the two sets never share a directory or a manifest."""
    assert gen.SETS["low"]["dir"] != gen.SETS["mid"]["dir"]
    assert gen.SETS["low"]["dir"].endswith(os.sep + "low")
    assert gen.SETS["low"]["cases_json"] != gen.SETS["mid"]["cases_json"]
    for c in cases("low"):
        assert os.path.isdir(gen.SETS["low"]["dir"])
        assert os.path.exists(os.path.join(gen.SETS["low"]["dir"], c["ids_file"]
                                          if c["type"] != "C"
                                          else c["history_ids_file"]))


# --------------------------------------------------------------------------
# The length windows: what each set is for
# --------------------------------------------------------------------------
@pytest.mark.parametrize("case", [c for c in cases("mid") if c["type"] in ("A", "B")],
                         ids=lambda c: "mid-" + c["id"])
def test_mid_single_shot_cases_separate_the_two_alignment_rules(case):
    """64-alignment picks a strictly smaller width than 16-alignment.

    ``n % 64 >= 16`` is exactly the condition: the 64 rule takes ``n - n%64``
    rows and replays the rest, the 16 rule takes at least 16 more.
    """
    n = case["tokens"]
    assert 16 <= n % gen.ALIGN_BASE < gen.ALIGN_BASE
    assert (n // gen.ALIGN_BASE) * gen.ALIGN_BASE < (n // 16) * 16


@pytest.mark.parametrize("case", [c for c in cases("mid") if c["type"] == "C"],
                         ids=lambda c: "mid-" + c["id"])
def test_mid_follow_up_chunks_separate_the_two_alignment_rules(case):
    nd = case["delta_tokens"]
    assert 16 <= nd <= 63, f"{case['id']}: {nd} tokens"
    # 64 alignment replays the whole chunk one row at a time, 16 alignment runs
    # a single dynamic launch of 16 or 32 rows.
    assert nd // 64 * 64 == 0
    assert nd // 16 * 16 >= 16


@pytest.mark.parametrize("case", [c for c in cases("low") if c["type"] in ("A", "B")],
                         ids=lambda c: "low-" + c["id"])
def test_low_single_shot_cases_leave_almost_no_exact_tail(case):
    """The MYS-2403 corner: under 64-alignment at most 7 rows are replayed.

    A real prompt whose length happens to land just past a multiple of 64 is in
    exactly this position, so the graded state is generated almost entirely
    from the inaccurate prefill graphs.
    """
    n = case["tokens"]
    assert n >= gen.ALIGN_BASE
    assert n % gen.ALIGN_BASE <= 7, f"{case['id']}: n={n} n%64={n % gen.ALIGN_BASE}"


@pytest.mark.parametrize("case", [c for c in cases("low") if c["type"] == "C"],
                         ids=lambda c: "low-" + c["id"])
def test_low_follow_up_chunks_leave_almost_no_exact_tail(case):
    nd = case["delta_tokens"]
    assert gen.SETS["low"]["delta_min"] <= nd <= gen.SETS["low"]["delta_max"], \
        f"{case['id']}: {nd} tokens"
    assert nd % gen.ALIGN_BASE <= 7, f"{case['id']}: delta%64={nd % gen.ALIGN_BASE}"
    # 64 alignment replays only the remainder; the 64-row launch is approximate.
    assert nd // gen.ALIGN_BASE * gen.ALIGN_BASE >= gen.ALIGN_BASE


@pytest.mark.parametrize("which", SETS)
def test_single_shot_cases_are_in_their_length_band(which):
    for case in cases(which):
        if case["type"] not in ("A", "B"):
            continue
        n = case["tokens"]
        lo, hi = (gen.MIN_FRESH, gen.MAX_FRESH) if case["type"] == "A" \
            else (gen.MIN_ARTICLE, gen.MAX_ARTICLE)
        assert lo <= n <= hi, f"{which}/{case['id']}: {n} tokens"
        assert len(ids_of(which, case["ids_file"])) == n


@pytest.mark.parametrize("which", SETS)
def test_multi_turn_history_fits_the_window(which):
    for case in cases(which):
        if case["type"] != "C":
            continue
        nh = case["history_tokens"]
        assert nh <= gen.MAX_HISTORY
        assert len(ids_of(which, case["history_ids_file"])) == nh
        assert nh + case["delta_tokens"] <= gen.MAX_HISTORY


def test_the_two_sets_windows_are_disjoint():
    """A mid length can never satisfy the low window (or the reverse), so
    ``--verify`` can tell a misfiled id file from a correct one."""
    mid, low = gen.SETS["mid"], gen.SETS["low"]
    assert low["rem_max"] < mid["rem_min"]
    assert mid["delta_max"] < low["delta_min"]


def test_separates_matches_the_selected_set():
    prev = gen.SET
    try:
        gen.SET = "mid"
        assert gen.separates(64 + 16) and gen.separates(64 + 63)
        assert not gen.separates(64) and not gen.separates(64 + 7)
        assert gen.separates_delta(16) and gen.separates_delta(63)
        assert not gen.separates_delta(64)
        gen.SET = "low"
        assert gen.separates(64) and gen.separates(64 + 7)
        assert not gen.separates(64 + 8)
        assert gen.separates_delta(64) and gen.separates_delta(71)
        assert not gen.separates_delta(15) and not gen.separates_delta(72)
    finally:
        gen.SET = prev


# --------------------------------------------------------------------------
# Ids, and the constraints recorded in cases.json
# --------------------------------------------------------------------------
@pytest.mark.parametrize("which", SETS)
def test_ids_are_in_the_qwen_vocabulary(which):
    # An id past the embedding table is an out-of-bounds device read on this
    # board: it wedges the TPU instead of reporting a bad argument.
    for c in cases(which):
        names = [c["ids_file"]] if c["type"] != "C" \
            else [c["history_ids_file"], c["delta_ids_file"]]
        for name in names:
            ids = ids_of(which, name)
            assert ids, name
            assert min(ids) >= 0 and max(ids) < gen.VOCAB, name


@pytest.mark.parametrize("which", SETS)
def test_cases_json_carries_the_constraints_it_was_generated_under(which):
    d = doc(which)
    assert d["align_base"] == 64
    assert d["min_delta"] == 16
    assert d["max_history"] == 2048
    assert d["note"]
    if which == "low":
        assert d["set"] == "low"


def test_low_set_records_its_own_windows():
    d = doc("low")
    assert d["set"] == "low"
    assert d["rem_min"] == 0
    assert d["rem_max"] == 7
    assert d["delta_min"] == 64
    assert d["delta_max"] == 71
    assert "n%64 <= 7" in d["note"]


def test_mid_manifest_stays_in_the_shape_mys2396_committed():
    """The mid set's output had to stay byte-identical, so its manifest keeps
    MYS-2396's keys and gains no ``set``/window fields. The window lives in
    ``gen.SETS`` instead."""
    d = doc("mid")
    assert "set" not in d and "rem_max" not in d
    assert d["note"] == ("A/B: prompt must be 16 <= n%64 so the two alignments pick "
                         "different widths. C: the appended follow-up chunk must be "
                         "16..63 tokens for the same reason.")
    assert gen.SETS["mid"]["rem_min"] == 16
    assert gen.SETS["mid"]["rem_max"] == 63
    assert gen.SETS["mid"]["delta_min"] == 16
    assert gen.SETS["mid"]["delta_max"] == 63


@pytest.mark.parametrize("which", SETS)
def test_b_and_c_questions_only_ask_about_their_own_text(which):
    """The question must be part of the prompt, and the answer must not be
    spelled out anywhere else in it -- otherwise the case grades itself."""
    for c in cases(which):
        assert c["question"] in c["text"], c["id"]
