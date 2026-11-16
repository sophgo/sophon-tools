"""What the ``ocr_vl`` kind is, and where it must not appear.

PaddleOCR-VL answers ``/v1/chat/completions`` -- that is the whole point of the
interface, and the reason the official PaddleOCR client can use it. What it
cannot do is hold a conversation, so it must be invisible to the two places that
*pick* a model rather than being handed one:

* an agent's model menu and default model (``AgentManager.model_choices``);
* the knowledge base's answer stage.

Both are asserted here rather than in the API tests because they are decisions
about the *kind*, and a file-name change is what would break them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.downloader import CATALOG, catalog_file_set
from app.core.models import (
    AGENT_MODEL_KINDS,
    AUX_KINDS,
    KINDS,
    KIND_CONFIG_DIRS,
    config_marker_for,
    kind_of_bmodel,
)


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", [
    "paddleocr-vl-1.5_bf16_seq2048_bm1684x2_4core_static_20261103.bmodel",
    "PaddleOCR-VL-1.5_bf16.bmodel",
    "paddleocr_vl_1_5_bf16.bmodel",
])
def test_paddleocr_vl_is_its_own_kind(name):
    assert kind_of_bmodel(name) == "ocr_vl"
    assert "ocr_vl" in KINDS


@pytest.mark.parametrize("name,kind", [
    # The PP-OCR det/rec pair keeps its own kind: /v1/ocr has a different shape.
    ("ppocrv6-medium-det_f16_736_bm1684x2_static_20261103.bmodel", "ocr"),
    ("ppdoclayout-m_f16_640_bm1684x2_static_20261104.bmodel", "ocr"),
    # A 35B is still a chat model, and a name that matches nothing is too.
    ("qwen3.6-35b-a3b-int4-autoround_w4bf16_seq32768_cv84x6_4core_history_dynamic.bmodel",
     "chat"),
    ("something-else.bmodel", "chat"),
])
def test_adding_ocr_vl_does_not_capture_its_neighbours(name, kind):
    assert kind_of_bmodel(name) == kind


def test_the_catalogue_entry_agrees_with_its_own_file_name():
    """The catalogue's ``kind`` and the file name must not disagree.

    ``discover_models`` reads the kind off the file it would load; the catalogue
    says what the card offers. A download whose name says ``ocr_vl`` but whose
    entry says ``chat`` would be listed under one endpoint and served by another.
    """
    entry = next(e for e in CATALOG if e["id"] == "paddleocr-vl-1.5")
    assert entry["kind"] == "ocr_vl"
    name = entry["dfss"].rsplit("/", 1)[-1]
    assert kind_of_bmodel(name) == "ocr_vl"
    # One file, so the card click and the id expansion are the same download,
    # and the entry keeps its own dflag (the update mechanism lives on it).
    files = catalog_file_set(entry)
    assert len(files) == 1
    assert files[0]["dflag"] == "cv84x6_llm_paddleocr-vl-1.5"


def test_the_config_directory_is_the_model_config_we_ship():
    assert KIND_CONFIG_DIRS["ocr_vl"] == "paddleocr_vl_1_5"
    assert config_marker_for("ocr_vl") == "tokenizer.json"


def test_the_shipped_config_directory_is_usable():
    """The bundled directory must carry every file the worker is started with.

    ``config_dir_for`` proves a directory is usable by the kind's marker file;
    the worker then asks it for the tokenizer *and* renders the prompt from it.
    A directory missing either would start a worker that loads and then fails on
    the first request.
    """
    root = Path(__file__).resolve().parent.parent / "model-config" / \
        KIND_CONFIG_DIRS["ocr_vl"]
    assert root.is_dir(), f"{root} is missing"
    for name in ("tokenizer.json", "config.json", "preprocessor_config.json",
                 "chat_template.jinja", "added_tokens.json"):
        assert (root / name).is_file(), f"{root / name} is missing"


# ---------------------------------------------------------------------------
# where it must not appear
# ---------------------------------------------------------------------------
def test_ocr_vl_is_not_an_auxiliary_kind():
    """It is loaded and unloaded by hand, like a chat model.

    ``AUX_KINDS`` is the idle machinery's whitelist: a member is unloaded when
    unused and loaded on demand. A 2.27 GB bmodel that takes ~7 s to map must
    not be, or every gap between two pages would pay the load again.
    """
    assert "ocr_vl" not in AUX_KINDS


def test_agents_may_only_be_configured_with_a_conversation_model():
    assert AGENT_MODEL_KINDS == ("chat",)
    assert "ocr_vl" not in AGENT_MODEL_KINDS


def test_agent_model_choices_exclude_ocr_vl(tmp_path):
    """The menu an operator picks from, with the real manager.

    A loaded OCR-VL model that appeared here could also become an agent's
    *default* model (``_pick_default_model`` takes the first choice), so this is
    the difference between "an extra row in a dropdown" and "every new agent is
    born broken".
    """
    from app.agents.manager import AgentManager
    from app.core.models import ModelInfo

    mgr = object.__new__(AgentManager)
    mgr.models = _StubModels([
        ModelInfo(model_id="qwen3.6-35b-a3b-128k", path=str(tmp_path / "a"),
                  display_name="chat", kind="chat", context_length=32768),
        ModelInfo(model_id="paddleocr-vl-1.5", path=str(tmp_path / "b"),
                  display_name="vl", kind="ocr_vl", context_length=2048),
    ])
    choices = mgr.model_choices()
    assert [c.id for c in choices] == ["qwen3.6-35b-a3b-128k"]


def test_the_kb_answer_stage_asks_for_a_conversation_model():
    from app.apps.kb import models as kb_models

    assert kb_models.answer_kind() == "chat"
    assert "ocr_vl" not in (kb_models.answer_kind(),)


class _StubModels:
    """Just the two methods ``model_choices`` uses."""

    def __init__(self, models) -> None:
        self._models = models

    def list(self):
        return list(self._models)
