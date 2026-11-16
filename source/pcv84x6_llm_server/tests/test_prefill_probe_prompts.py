"""The committed prompt files the prefill-width probe reads (MYS-2394).

The probe's whole claim is that a dynamic prefill width can be compared against
the 64-aligned baseline. That only holds if both runs read the same ids, and the
ids only mean something if they are what the release tokenizer produces for real
text -- an earlier driver fed the engine hand-written id sequences and the TPU
timed out. These tests pin the properties the probe relies on without an NPU:
the files parse, their lengths are the ones the matrix asks for, they agree with
the manifest, and they are shaped like the prompt the worker actually builds.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPTS = os.path.join(HERE, "..", "tools", "prefill_probe_prompts")
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import gen_prefill_probe_prompts as gen  # noqa: E402


def ids_of(name):
    with open(os.path.join(PROMPTS, name), encoding="utf-8") as f:
        return [int(x) for x in f.read().replace("\n", ",").split(",") if x.strip()]


def manifest():
    with open(os.path.join(PROMPTS, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def test_manifest_lists_every_file_and_nothing_else():
    files = manifest()["files"]
    on_disk = {n for n in os.listdir(PROMPTS) if n.endswith(".txt")
               and n != "corpus.txt"}
    assert on_disk == set(files)


def test_files_agree_with_manifest():
    assert gen.verify_manifest() == 0


@pytest.mark.parametrize("name", sorted(manifest()["files"]))
def test_length_matches_name(name):
    want = int(name.split("-")[1].split(".")[0])
    assert len(ids_of(name)) == want


def test_matrix_lengths_are_all_present():
    # The matrix in MYS-2394: fresh 63/200/1000, extend 48/33/17/5 after a
    # 1000- and a 2048-token history.
    for n in (63, 200):
        assert ids_of(f"fresh-{n}.txt")
    for n in (1000, 2048):
        assert ids_of(f"turn-{n}.txt")
    for n in (5, 17, 33, 48):
        assert ids_of(f"delta-{n}.txt")


def test_ids_are_in_the_qwen_vocabulary():
    # 248320 is the tokenizer's vocab size; a larger id would make the
    # embedding graph read out of bounds, which wedges the board rather than
    # reporting an error.
    for name in manifest()["files"]:
        ids = ids_of(name)
        assert ids and min(ids) >= 0 and max(ids) < 248320, name


def test_fresh_files_end_at_the_generating_header():
    """A fresh prompt must end at the template's generating header.

    Everything the model is asked has to be inside the ids, and the header is
    what tells it to answer; a prompt cut before the header is a different
    input. ``header_ids`` in the manifest is what the tokenizer encoded that
    header to when the files were generated, so this check needs no tokenizer.
    """
    header = manifest()["header_ids"]
    assert len(header) >= 6
    for name in ("fresh-63.txt", "fresh-200.txt", "turn-1000.txt", "turn-2048.txt"):
        assert ids_of(name)[-len(header):] == header, name


def test_deltas_are_next_turns_and_prefixes_of_the_longest():
    """delta-5 is the whole next-turn opener; delta-48 is a whole chunk."""
    m = manifest()
    opener = m["next_turn_ids"]
    assert ids_of(f"delta-{min(gen.DELTA)}.txt") == opener
    assert ids_of(f"delta-{max(gen.DELTA)}.txt")[-len(m["header_ids"]):] == m["header_ids"]



def test_delta_longest_is_a_whole_next_turn():
    """delta-48 is the complete chunk the template appends for the next turn."""
    assert len(ids_of(f"delta-{max(gen.DELTA)}.txt")) == max(gen.DELTA)


def test_deltas_are_prefixes_of_the_longest():
    longest = max(gen.DELTA)
    full = ids_of(f"delta-{longest}.txt")
    for n in gen.DELTA:
        if n != longest:
            assert ids_of(f"delta-{n}.txt") == full[:n]


def test_corpus_is_text_not_ids():
    with open(os.path.join(PROMPTS, "corpus.txt"), encoding="utf-8") as f:
        words = f.read().split()
    assert len(words) > 500
    assert all(w.strip(".,;:").replace("-", "").isalpha() for w in words[:50])
