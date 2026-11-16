"""The three dense Qwen3.5 catalogue entries (MYS-2754).

A one-click download is only as good as its catalogue entry: every field the
downloader, the console and the update path read has to be present *and* right,
and the entry is written once by hand and then never touched again. These tests
pin the parts that would fail silently rather than loudly:

* a missing ``dflag`` or ``dfss`` would make the entry undownloadable -- the
  console would offer a card that cannot be installed;
* a wrong ``kind`` would show a chat model under the wrong endpoint;
* ``context`` drives what ``/v1/models`` reports, so an entry that claims less
  than the build supports would have agents truncate prompts for no reason;
* ``vision`` is what keeps the attachment button enabled on a model whose file
  name says nothing about images (``tests/test_agent_model_matrix.py`` relies
  on this for every chat entry).
"""

from __future__ import annotations

import re

import pytest

from app.agents.spec import url_filename
from app.core.downloader import CATALOG, catalog_entry
from app.core.models import KIND_CONFIG_MARKER, kind_of_bmodel

#: The three ids MYS-2754 adds, with the facts the builds were compiled to.
NEW_ENTRIES = {
    "qwen3.5-9b-128k": {"quant": "w4", "vision": True},
    "qwen3.5-4b-128k": {"quant": "w4", "vision": True},
}

#: An md5 in the catalogue is either the real digest or a placeholder standing
#: in for one the release owner has not uploaded yet. A placeholder is allowed
#: to exist in the source tree but must be recognisable, so this test can tell
#: "not filled in yet" from "filled in wrongly" -- and ``test_the_digest_is_set``
#: below fails loudly on the former at release time.
_PLACEHOLDER = re.compile(r"^PENDING-[A-Z0-9-]+$")
_MD5 = re.compile(r"^[0-9a-f]{32}$")


@pytest.mark.parametrize("model_id", sorted(NEW_ENTRIES))
def test_every_required_field_is_present(model_id):
    entry = catalog_entry(model_id)
    assert entry is not None, model_id
    for field in ("id", "kind", "title", "dfss", "dflag", "md5",
                  "size_bytes", "vision", "verified", "context", "prefix_cache"):
        assert field in entry, (model_id, field)


@pytest.mark.parametrize("model_id", sorted(NEW_ENTRIES))
def test_the_kind_is_chat(model_id):
    """The issue's explicit acceptance criterion: these are conversational.

    Both halves matter -- the declared ``kind`` (what the console labels before
    the file exists) and the one the bmodel name implies (what the scan derives
    after). The catalogue test in ``test_model_kind.py`` checks they agree; this
    one checks the value they agree *on*.
    """
    entry = catalog_entry(model_id)
    assert entry["kind"] == "chat"
    assert kind_of_bmodel(url_filename(entry["dfss"])) == "chat"


@pytest.mark.parametrize("model_id", sorted(NEW_ENTRIES))
def test_the_bmodel_name_carries_the_facts_the_entry_claims(model_id):
    """128k, 4 core, history KV and vision, all visible in the file name.

    Not cosmetic: the name is what an operator reads in the models directory
    after a download, and the ``seq`` token is also what the service parses back
    into ``context_length`` when the model is scanned (``models.py`` meta). A
    build whose file name said ``seq32768`` while the entry said 131072 would be
    served with a context the bmodel cannot hold.
    """
    entry = catalog_entry(model_id)
    name = url_filename(entry["dfss"]).lower()
    assert entry["context"] == 131072
    assert f"_seq{entry['context']}_" in name
    assert "history" in name
    assert "4core" in name
    # Vision is compiled in with ``--max_pixels``; the bmodel name has no token
    # for it, so the catalogue is the only place it is recorded. What the test
    # can check is that the entry says so, and that the engine agrees once the
    # model loads (the board measurements in docs/qwen35-small.md do that).
    assert entry["vision"] is True


@pytest.mark.parametrize("model_id", sorted(NEW_ENTRIES))
def test_the_quantisation_in_the_name_matches_the_title(model_id):
    """``w4bf16`` in the name, "int4" in the title, ``bf16`` for the bf16 build.

    The user reads the title in the console; the name is what lands on disk and
    what the precision report is about. The two disagreeing is how a w4 build
    gets mistaken for the from-float reference.
    """
    entry = catalog_entry(model_id)
    name = url_filename(entry["dfss"]).lower()
    spec = NEW_ENTRIES[model_id]
    if spec["quant"] == "w4":
        assert "_w4bf16_" in name, name
        assert "int4" in entry["title"], entry["title"]
    else:
        assert "_bf16_" in name, name
        assert "_w4bf16_" not in name
        assert "bf16" in entry["title"], entry["title"]


@pytest.mark.parametrize("model_id", sorted(NEW_ENTRIES))
def test_the_tag_is_the_house_scheme(model_id):
    """``cv84x6_llm_<id>`` -- the scheme ``docs/model-release.md`` documents.

    A tag that does not follow it would still work, but the release checklist is
    written against this shape and the ``.md5`` sidecar tag is derived from it by
    appending a suffix. Getting it wrong once means the update path silently
    finds no sidecar and falls back to the fixed URL, which is exactly the
    "update removes the ability to update" failure the tag exists to prevent.
    """
    entry = catalog_entry(model_id)
    assert entry["dflag"] == f"cv84x6_llm_{entry['id']}"


@pytest.mark.parametrize("model_id", sorted(NEW_ENTRIES))
def test_the_dfss_path_is_under_our_publish_directory(model_id):
    entry = catalog_entry(model_id)
    assert entry["dfss"].startswith(
        "open@sophgo.com:/tools/cv84x6_llm_server/"), entry["dfss"]


@pytest.mark.parametrize("model_id", sorted(NEW_ENTRIES))
def test_the_digest_is_set(model_id):
    """The digest and size are the download's own integrity check.

    A placeholder is a release blocker, not a warning: ``size_bytes`` is what the
    downloader checks the disk against *before* starting (a 10 GB download that
    dies at 99% because the disk filled is the failure mode it exists for), and
    ``md5`` is what verifies the bytes afterwards. Run with
    ``MYS2754_ALLOW_PENDING=1`` while the build is still running; the release
    check must not.
    """
    import os

    entry = catalog_entry(model_id)
    pending = (_PLACEHOLDER.match(entry["md5"] or "")
               or not entry["size_bytes"])
    if pending and os.environ.get("MYS2754_ALLOW_PENDING") == "1":
        pytest.skip(f"{model_id}: build not published yet, {entry['md5']}")
    assert _MD5.match(entry["md5"] or ""), (model_id, entry["md5"])
    assert entry["size_bytes"] > 0, model_id


@pytest.mark.parametrize("model_id", sorted(NEW_ENTRIES))
def test_the_build_timestamp_is_one_a_build_could_have_produced(model_id):
    """The name's trailing timestamp must be a real build stamp, not a guess.

    I wrote these entries before the builds finished and left a plausible-looking
    ``_20261110_041500`` in two of them; the actual artifacts are stamped
    ``033630`` and ``051942``. Nobody notices a wrong timestamp -- the download
    works, the model serves -- but the name is the only record of *which* build a
    board is running, so a wrong one makes every later comparison ("is this the
    build I measured?") unanswerable.

    What this can check without the artifacts present: the stamp parses as a
    timestamp, and it is not the placeholder the entries were written with.
    ``docs/qwen35-small.md`` §5 is the authoritative list; a mismatch there is a
    documentation bug this test cannot see, which is why the release step is
    "copy the md5 from the file" and not "type it".
    """
    import datetime as _dt

    entry = catalog_entry(model_id)
    name = url_filename(entry["dfss"])
    m = re.search(r"_(\d{8})_(\d{6})\.bmodel$", name)
    assert m, (model_id, name)
    stamp = _dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    # A build cannot be stamped in the future relative to when this catalogue
    # shipped, and a 128k build takes hours, so nothing before 2026 is plausible.
    assert stamp.year >= 2026, (model_id, stamp)
    assert "041500" not in name, (model_id, "placeholder timestamp left in the name")


def test_the_chat_config_marker_exists_for_these_entries():
    """A chat download has no ``config/`` of its own, so the bundled one serves.

    ``config_dir_for`` falls back to it, and a kind whose marker file is missing
    gives the worker an empty ``--config-path``. The marker name is the contract
    between the catalogue entry's kind and what the release ships.
    """
    assert KIND_CONFIG_MARKER["chat"] == "tokenizer.json"


def test_the_4b_bf16_build_is_no_longer_offered():
    """Dropped in v0.6.32 (user decision): same memory as the 9B w4, half its speed."""
    assert "qwen3.5-4b-bf16-128k" not in {m["id"] for m in CATALOG}
