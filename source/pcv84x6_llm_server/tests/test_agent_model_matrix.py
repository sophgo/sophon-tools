"""The model-config contract, checked across every model and every agent.

One model is not the contract. The context length is what decides the agent's
context window *and* how much output it reserves, and the four models this
project ships come in two of them -- 32768 and 131072. A test that only checked
32k would pass while a 128k model was handed a window the NPU cannot take, so
every assertion here is parameterised over all four models and all three agents.

The three agents describe a model very differently, which is why this file checks
each one's own document shape rather than one shared expectation:

    opencode   provider.cv84x6.models.<id>.limit.{context,output}, attachment
    OpenClaw   models.providers.cv84x6.models[].{contextWindow,maxTokens,input}
    PicoClaw   model_list[].{model_name,model,api_base,api_keys} + agents.defaults

What they must agree on, and what is asserted for all three:

* the model id this service is asked for (bare, never provider-prefixed),
* the API base -- loopback, this service's port, ``/v1``,
* the API key,
* the context window, exactly 32768 or 131072,
* the output cap, ``min(16384, context // 2)``,
* the default model, as each agent spells it,
* vision, wherever the agent has a field for it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents import openclaw as openclaw_mod
from app.agents import opencode as opencode_mod
from app.agents import picoclaw as picoclaw_mod
from app.agents.openclaw import OpenclawSpec
from app.agents.opencode import OpencodeSpec
from app.agents.picoclaw import PicoclawSpec
from app.agents.spec import InstallContext, ModelChoice, url_filename
from app.core.downloader import CATALOG

# The four models, named as the catalogue names them. Contexts are the ones the
# service reports from the loaded graph; the fallback in the manager would give
# the same pair, and either way the agent must see the real number.
MODELS = [
    ModelChoice(id="qwen3.6-35b-a3b-128k", context=131072, vision=True),
    ModelChoice(id="qwen3.5-35b-a3b-128k", context=131072, vision=True),
    ModelChoice(id="qwen3.6-35b-a3b-32k", context=32768, vision=True),
    ModelChoice(id="qwen3.5-35b-a3b-32k", context=32768, vision=True),
]

SERVICE_PORT = 8000
API_KEY = "sk-agent-under-test"
SECRET = "agent-secret-1234"

OUTPUT_CAP = 16384


def _ctx(default: str, thinking: bool = False, **over) -> InstallContext:
    base = dict(
        service_port=SERVICE_PORT,
        api_key=API_KEY,
        models=list(MODELS),
        default_model=default,
        thinking=thinking,
        secret=SECRET,
        port=14097,
    )
    base.update(over)
    return InstallContext(**base)


SPECS = [PicoclawSpec(), OpencodeSpec(), OpenclawSpec()]
SPEC_IDS = ["picoclaw", "opencode", "openclaw"]


def _expected_output(context: int, minimum: int) -> int:
    """``min(16384, context // 2)``, floored at each agent's own minimum.

    OpenClaw clamps at 256 and PicoClaw at 512; opencode has no floor. The
    meaningful cases are all far above either, so the floor only matters for a
    tiny context no shipped model has.
    """
    return min(OUTPUT_CAP, max(minimum, context // 2))


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
@pytest.mark.parametrize("choice", MODELS, ids=lambda c: c.id)
def test_every_agent_describes_every_model_correctly(spec, choice, tmp_path):
    """The whole contract, one agent and one model at a time."""
    ctx = _ctx(default=choice.id)
    if spec.id == "picoclaw":
        cfg = spec.build_config(tmp_path, ctx)
        entry = {m["model_name"]: m for m in cfg["model_list"]}[choice.id]
        assert entry["model"] == f"openai/{choice.id}"
        # The id this service is asked for is bare -- never "openai/<id>".
        assert choice.id in entry["model"]
        assert entry["api_base"] == f"http://127.0.0.1:{SERVICE_PORT}/v1"
        assert entry["api_keys"] == [API_KEY]
        defaults = cfg["agents"]["defaults"]
        assert defaults["model_name"] == choice.id
        assert defaults["context_window"] == choice.context
        assert defaults["max_tokens"] == _expected_output(choice.context, 512)
        assert cfg["gateway"]["port"] == 14098

    elif spec.id == "opencode":
        cfg = spec.build_config(ctx)
        provider = cfg["provider"][opencode_mod.PROVIDER]
        assert provider["options"]["baseURL"] == f"http://127.0.0.1:{SERVICE_PORT}/v1"
        assert provider["options"]["apiKey"] == API_KEY
        entry = provider["models"][choice.id]
        assert entry["limit"]["context"] == choice.context
        assert entry["limit"]["output"] == _expected_output(choice.context, 0)
        assert entry["attachment"] is choice.vision
        assert cfg["model"] == f"{opencode_mod.PROVIDER}/{choice.id}"
        assert cfg["small_model"] == f"{opencode_mod.PROVIDER}/{choice.id}"

    else:
        cfg = spec.build_config(tmp_path, ctx)
        provider = cfg["models"]["providers"][openclaw_mod.PROVIDER]
        assert provider["baseUrl"] == f"http://127.0.0.1:{SERVICE_PORT}/v1"
        assert provider["apiKey"] == API_KEY
        entry = {m["id"]: m for m in provider["models"]}[choice.id]
        assert entry["contextWindow"] == choice.context
        assert entry["maxTokens"] == _expected_output(choice.context, 256)
        assert entry["compat"]["maxTokensField"] == "max_tokens"
        assert entry["input"] == (["text", "image"] if choice.vision else ["text"])
        assert (cfg["agents"]["defaults"]["model"]["primary"]
                == f"{openclaw_mod.PROVIDER}/{choice.id}")


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_no_agent_writes_a_rounded_context_window(spec, tmp_path):
    """128000 is the tempting wrong number; the models are 131072.

    Checked separately from the per-model test because a hand-written default
    would pass a "the window is large" assertion and fail this one.
    """
    ctx = _ctx(default="qwen3.6-35b-a3b-128k")
    text = json.dumps(
        spec.build_config(tmp_path, ctx) if spec.id != "opencode"
        else spec.build_config(ctx)
    )
    assert "128000" not in text
    assert "131072" in text


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_switching_the_default_model_moves_only_the_default(spec, tmp_path):
    """A model switch must not rewrite the other entries' numbers.

    Same model list, different default: everything except the default selector
    has to be byte-identical. That is what makes "切换默认模型" a cheap,
    safe operation rather than a regeneration that could carry a new mistake.
    """
    first = _ctx(default="qwen3.6-35b-a3b-32k")
    second = _ctx(default="qwen3.5-35b-a3b-128k")

    def build(ctx):
        return spec.build_config(tmp_path, ctx) if spec.id != "opencode" \
            else spec.build_config(ctx)

    a, b = build(first), build(second)
    if spec.id == "picoclaw":
        assert [m["model_name"] for m in a["model_list"]] == \
               [m["model_name"] for m in b["model_list"]]
        a["agents"]["defaults"].pop("model_name")
        b["agents"]["defaults"].pop("model_name")
        # The context window follows the default model, which is the point.
        a["agents"]["defaults"].pop("context_window")
        b["agents"]["defaults"].pop("context_window")
        a["agents"]["defaults"].pop("max_tokens")
        b["agents"]["defaults"].pop("max_tokens")
        assert a == b
    elif spec.id == "opencode":
        a.pop("model")
        b.pop("model")
        a.pop("small_model")
        b.pop("small_model")
        assert a == b
    else:
        a["agents"]["defaults"].pop("model")
        b["agents"]["defaults"].pop("model")
        assert a == b


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_every_agent_reaches_the_service_on_loopback_with_the_key(spec, tmp_path):
    """The one thing all three must get identically right.

    The service is on the same board, so the base is loopback -- using the
    board's LAN address would work from the board and fail nowhere visibly, then
    break the moment the service binds more narrowly.
    """
    ctx = _ctx(default="qwen3.6-35b-a3b-32k")
    text = json.dumps(spec.build_config(tmp_path, ctx) if spec.id != "opencode"
                      else spec.build_config(ctx))
    assert f"http://127.0.0.1:{SERVICE_PORT}/v1" in text
    assert API_KEY in text
    assert "0.0.0.0" not in text


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_thinking_off_is_the_default_and_reaches_the_service(spec, tmp_path):
    """Thinking defaults to off, and "off" must be what the request says.

    The service treats thinking as opt-in, so an agent that omits the field gets
    it off -- but an agent that *asserts* it off is what makes the console's
    toggle mean something in both directions.
    """
    off = _ctx(default="qwen3.6-35b-a3b-32k", thinking=False)
    on = _ctx(default="qwen3.6-35b-a3b-32k", thinking=True)

    def build(ctx):
        return spec.build_config(tmp_path, ctx) if spec.id != "opencode" \
            else spec.build_config(ctx)

    off_text, on_text = json.dumps(build(off)), json.dumps(build(on))
    if spec.id == "picoclaw":
        assert '"thinking_level": "off"' in off_text
        assert '"enable_thinking": true' in on_text
    elif spec.id == "opencode":
        # opencode gets both variants so the operator can flip it per session.
        assert '"enable_thinking": false' in off_text
        assert '"enable_thinking": true' in on_text
    else:
        assert '"thinkingDefault": "off"' in off_text
        assert '"thinkingDefault": "off"' not in on_text


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
def test_a_fresh_install_and_a_sync_write_the_same_document(spec, tmp_path):
    """Install and sync must agree, or a restart silently changes behaviour.

    ``sync_config`` runs on every start, so anything it writes differently from
    the install is what the agent actually runs on -- and the console would be
    showing the install's version.
    """
    ctx = _ctx(default="qwen3.5-35b-a3b-128k")
    directory = tmp_path / "agent"
    (directory / "config").mkdir(parents=True)
    (directory / "bin").mkdir(parents=True)
    (directory / "bin" / (spec.executable or "x")).write_text("")

    spec.write_config(directory, ctx)
    first = spec.config_path(directory).read_text()
    spec.write_config(directory, ctx)
    second = spec.config_path(directory).read_text()
    assert first == second
    # The key written at install is the one a sync recovers.
    assert spec.existing_key(directory) == API_KEY


# -- from the model list to the config file ---------------------------------
#
# Everything above starts from a hand-built ``ModelChoice``. That is why the
# defect this section guards went unnoticed: the manager builds those choices
# from ``ModelManager`` and the catalogue, and it was dropping vision to False
# for an installed-but-unloaded 35B model -- the file-name heuristic looks for
# ``vl``/``vit``/``vision`` and none of the four builds has any of those in its
# name. Every agent then wrote a config saying "text only".
#
# So these tests start one level earlier: real model directories named the way
# the catalogue's downloads are, the manager's own ``model_choices()``, and the
# agent's own ``build_config`` on the context the manager hands it.


def _bmodel_name(model_id: str) -> str:
    """The .bmodel file name a one-click catalogue download lands on disk.

    Taken from the catalogue rather than invented, because the whole defect is
    about what that name does and does not contain.
    """
    entry = next(c for c in CATALOG if c["id"] == model_id)
    return url_filename(entry["dfss"])


def _manager(tmp_path, model_ids: tuple[str, ...] = (), infos: dict | None = None):
    """An ``AgentManager`` over all three agents and a real models directory.

    ``model_ids`` are created on disk with the file name a one-click catalogue
    download produces, then scanned by a real ``ModelManager``; the resulting
    entries are left unloaded, because a worker is not something a config test
    should have to start, and "installed but not loaded" is the state the
    defect showed up in. ``infos`` replaces the scan outright for the cases
    that are about loaded workers or ids no download would produce.
    """
    from app.agents.manager import AgentManager
    from app.core.models import ModelManager
    from app.core.state import StateStore

    models_root = tmp_path / "models"
    models_root.mkdir()
    for model_id in model_ids:
        directory = models_root / model_id
        directory.mkdir()
        (directory / _bmodel_name(model_id)).write_bytes(b"")
    manager = ModelManager(models_root, backend_kind="mock", log_dir=tmp_path / "logs")
    manager.refresh()
    if infos is not None:
        manager._models = dict(infos)

    root = tmp_path / "root"
    (root / "agents").mkdir(parents=True)
    store = StateStore(root / "state" / "state.json")
    mgr = AgentManager(root, key_store=store, models=manager, specs=list(SPECS),
                       service_port=SERVICE_PORT)
    return mgr, manager


def _config_from_manager(spec, mgr, model_id: str, tmp_path) -> tuple[dict, ModelChoice]:
    """The document each agent builds from the manager's own model list.

    ``model_choices()`` is the boundary the defect lived on: everything below it
    is agent-specific, and the three agents below all read the same
    ``ModelChoice.vision``. Feeding it straight into ``build_config`` keeps the
    test about that boundary instead of about a hand-written context.
    """
    choices = mgr.model_choices()
    ctx = InstallContext(
        service_port=SERVICE_PORT, api_key=API_KEY, models=choices,
        default_model=model_id, thinking=False, secret=SECRET,
        port=spec.default_port,
    )
    built = spec.build_config(tmp_path, ctx) if spec.id != "opencode" \
        else spec.build_config(ctx)
    return built, {c.id: c for c in choices}[model_id]


def _entry_for(spec, cfg, model_id: str) -> dict:
    if spec.id == "picoclaw":
        return {m["model_name"]: m for m in cfg["model_list"]}[model_id]
    if spec.id == "opencode":
        return cfg["provider"][opencode_mod.PROVIDER]["models"][model_id]
    return {m["id"]: m for m in cfg["models"]["providers"][openclaw_mod.PROVIDER]["models"]}[model_id]


@pytest.mark.parametrize("spec", SPECS, ids=SPEC_IDS)
@pytest.mark.parametrize(
    "model_id",
    # Chat models only: an embedding or rerank model is not a choice an agent may
    # be configured with (it cannot answer a chat turn), so `model_choices()`
    # deliberately omits it and there is no config to inspect.
    [c["id"] for c in CATALOG if c.get("kind", "chat") == "chat"])
def test_an_installed_but_unloaded_catalogue_model_still_declares_images(
        spec, model_id, tmp_path):
    """The regression: a 35B model on disk but not loaded is still a VLM.

    Its file name says nothing about vision, so the local scan reports False.
    The catalogue knows these four take images, and that knowledge is what the
    agent's config has to be written from -- otherwise opencode greys out the
    attachment button and OpenClaw refuses to send an image, on a model that
    would have accepted it.
    """
    mgr, models = _manager(tmp_path, model_ids=(model_id,))
    info = models.get(model_id)
    # The premise of the bug: the scan cannot see vision in these names.
    assert info is not None and info.loaded is False
    assert info.supports_vision is False, _bmodel_name(model_id)

    cfg, choice = _config_from_manager(spec, mgr, model_id, tmp_path)
    assert choice.vision is True

    entry = _entry_for(spec, cfg, model_id)
    if spec.id == "opencode":
        assert entry["attachment"] is True
    elif spec.id == "openclaw":
        assert entry["input"] == ["text", "image"]
    else:
        # PicoClaw's 0.3.1 schema has no per-model vision field: media is
        # base64-encoded and sent to the active model, and the only vision knob
        # is agents.defaults.image_model (a separate model for image turns).
        # So the fix cannot show up in its document, and this asserts the
        # honest fact -- PicoClaw never claimed text-only and its config does
        # not depend on the flag at all.
        assert entry["model"] == f"openai/{model_id}"
        text_only = spec.build_config(
            tmp_path, InstallContext(
                service_port=SERVICE_PORT, api_key=API_KEY,
                models=[ModelChoice(id=model_id, context=choice.context,
                                    vision=False)],
                default_model=model_id, port=spec.default_port,
            ),
        )
        assert text_only == cfg


def test_a_loaded_model_reports_its_own_vision_over_the_catalogue(tmp_path):
    """The loaded worker is the authority, in both directions.

    The catalogue describes what the build was made for; the worker reports
    what its graphs actually contain. A loaded model that says "no vision" must
    not be talked into attachments by the catalogue -- that would turn a config
    problem into a 400 from ``/v1/chat/completions``.
    """
    from app.core.models import ModelInfo

    loaded = "qwen3.6-35b-a3b-32k"
    mgr, _ = _manager(tmp_path)
    mgr.models._models = {
        # Catalogue says vision: the loaded graph says otherwise.
        loaded: ModelInfo(model_id=loaded, path="", display_name="", loaded=True,
                          context_length=32768, supports_vision=False),
        # Not in the catalogue at all, and its name says nothing: the worker is
        # the only source, and it says yes.
        "local-vl": ModelInfo(model_id="local-vl", path="", display_name="",
                              loaded=True, context_length=32768,
                              supports_vision=True),
    }
    choices = {c.id: c.vision for c in mgr.model_choices()}
    assert choices[loaded] is False
    assert choices["local-vl"] is True


def test_a_model_the_catalogue_does_not_know_keeps_its_scanned_vision(tmp_path):
    """No catalogue entry: the local answer stands, whatever it is.

    An operator's hand-imported model is judged by its file name and nothing
    else, so a ``_vl_`` build keeps its images and a plain one stays text-only.
    """
    from app.core.models import ModelInfo

    mgr, _ = _manager(tmp_path)
    mgr.models._models = {
        "hand-imported-vl": ModelInfo(model_id="hand-imported-vl", path="",
                                      display_name="", context_length=32768,
                                      supports_vision=True),
        "hand-imported-text": ModelInfo(model_id="hand-imported-text", path="",
                                        display_name="", context_length=32768,
                                        supports_vision=False),
    }
    choices = {c.id: c.vision for c in mgr.model_choices()}
    assert choices["hand-imported-vl"] is True
    assert choices["hand-imported-text"] is False


def test_the_catalogue_vision_is_normalised_to_a_bool(tmp_path, monkeypatch):
    """The flag reaches opencode as ``is True``, so it has to *be* a bool.

    The catalogue is data an operator can edit; a ``1`` or a ``"yes"`` there
    would otherwise travel into the agent's config as-is, and opencode's
    ``attachment`` is compared with ``is`` in the contract.
    """
    from app.core.models import ModelInfo

    mgr, _ = _manager(tmp_path)
    mgr.models._models = {
        "truthy": ModelInfo(model_id="truthy", path="", display_name=""),
        "falsy": ModelInfo(model_id="falsy", path="", display_name=""),
    }
    monkeypatch.setattr(
        "app.core.downloader.CATALOG",
        [{"id": "truthy", "vision": 1}, {"id": "falsy", "vision": 0}],
    )
    choices = {c.id: c.vision for c in mgr.model_choices()}
    assert choices["truthy"] is True
    assert choices["falsy"] is False


def test_an_embedding_model_is_not_offered_to_agents(tmp_path):
    """`model_choices()` is the list an agent's config is written from.

    An embedding or rerank model cannot answer a chat turn: offering one would
    write a config whose every request comes back 400 (the kind check in
    app/api/openai_api.py). So the list stays chat-only, and a board with both
    kinds installed still hands the agent exactly the chat models.
    """
    from app.core.models import ModelInfo

    mgr, _ = _manager(tmp_path)
    mgr.models._models = {
        "qwen3.6-35b-a3b-32k": ModelInfo(
            model_id="qwen3.6-35b-a3b-32k", path="", display_name="",
            kind="chat", context_length=32768, supports_vision=True),
        "qwen3-embedding-0.6b": ModelInfo(
            model_id="qwen3-embedding-0.6b", path="", display_name="",
            kind="embedding", context_length=8192),
        "bge-reranker-v2-m3": ModelInfo(
            model_id="bge-reranker-v2-m3", path="", display_name="",
            kind="rerank", context_length=2048),
    }
    assert [c.id for c in mgr.model_choices()] == ["qwen3.6-35b-a3b-32k"]
