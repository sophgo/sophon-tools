"""Real HTTP/RPC integration with explicit mock vector semantics."""
import base64
import json
import math
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.models import ModelManager, is_vl_embedding, kind_of_bmodel
from app.engine.vl_embed import validate_items
from app.engine.vl_embed_native import VLEmbedder, instruction_text, render_prompt


PNG = "data:image/png;base64," + base64.b64encode(
    (Path(__file__).parent / "vision_fixtures/tiny.png").read_bytes()).decode()


@pytest.fixture()
def client(tmp_path):
    models = tmp_path / "models"
    for name, prefix in (("multimodal", "qwen3-vl-embedding-2b"),
                         ("wemm", "wemm-embedding-2b"),
                         ("textonly", "qwen3-embedding-0.6b")):
        d = models / name
        (d / "config").mkdir(parents=True)
        (d / f"{prefix}_w8bf16_seq2048_cv84x6.bmodel").write_bytes(b"fake")
        (d / "config" / "config.json").write_text("{}")
    app = create_app(data_dir=tmp_path / "state", models_dir=models,
                     backend_kind="mock", web_dir=tmp_path / "web")
    with TestClient(app) as c:
        assert c.post("/api/login", json={"password": "admin"}).status_code == 200
        for name in ("multimodal", "textonly", "wemm"):
            result = c.post(f"/api/models/{name}/load")
            assert result.status_code == 200, result.text
        key = c.post("/api/keys", json={"name": "test"}).json()["key"]
        c.headers["Authorization"] = f"Bearer {key}"
        yield c


def call(client, input, **extra):
    return client.post("/v1/embeddings", json={"model": "multimodal", "input": input, **extra})


def test_kind_and_prompt_contract():
    assert kind_of_bmodel("qwen3-vl-embedding-2b_w8bf16.bmodel") == "embedding"
    assert kind_of_bmodel("qwen3-vl-2b-instruct.bmodel") == "chat"
    assert is_vl_embedding("/a/qwen3_vl_embedding_2b.bmodel")
    assert instruction_text("检索相关图片") == "检索相关图片."
    assert instruction_text("检索相关图片。") == "检索相关图片。"
    assert render_prompt("cat", 2) == (
        "<|im_start|>system\nRepresent the user's input.<|im_end|>\n"
        "<|im_start|>user\n<|vision_start|><|image_pad|><|image_pad|><|vision_end|>"
        "cat<|im_end|>\n<|im_start|>assistant\n")


def test_wemm_is_embedding_with_its_own_prompt():
    assert kind_of_bmodel("wemm-embedding-2b_bf16.bmodel") == "embedding"
    assert is_vl_embedding("/models/wemm_embedding_2b.bmodel")
    assert render_prompt("cat", family="wemm_embedding") == "<|im_start|>user\ncat<|im_end|>\n"
    assert render_prompt("  cat \n", family="wemm_embedding") == render_prompt("cat", family="wemm_embedding")
    assert render_prompt("  cat \n", 1, family="wemm_embedding") == (
        "<|im_start|>user\n<|vision_start|><|image_pad|><|vision_end|>  cat<|im_end|>\n")
    assert render_prompt("cat", instruction="Retrieve images", family="wemm_embedding") == (
        "<|im_start|>system\nRetrieve images<|im_end|>\n<|im_start|>user\ncat<|im_end|>\n")


def test_wemm_rpc_mixed_inputs_and_dimensions(client):
    items = ["一只猫", {"image": PNG}, {"text": "一只猫", "image": PNG}]
    response = client.post("/v1/embeddings", json={"model": "wemm", "input": items, "dimensions": 256})
    assert response.status_code == 200, response.text
    vectors = response.json()["data"]
    assert [v["index"] for v in vectors] == [0, 1, 2]
    assert len({tuple(v["embedding"]) for v in vectors}) == 3
    for v in vectors:
        assert len(v["embedding"]) == 256
        assert sum(x*x for x in v["embedding"]) == pytest.approx(1)
    # The worker must choose WeMM's prompt; even the protocol fixture must not
    # silently pretend the two vector spaces are interchangeable.
    baseline = call(client, items, dimensions=256).json()["data"]
    assert baseline[0]["embedding"] != vectors[0]["embedding"]
    assert client.post("/v1/chat/completions", json={"model": "wemm",
        "messages": [{"role": "user", "content": "hello"}]}).status_code == 400


def test_mixed_batch_order_mrl_and_base64(client):
    items = ["a cat", {"image": PNG}, {"text": "a cat", "image": PNG}]
    r = call(client, items, dimensions=128)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert [x["index"] for x in data] == [0, 1, 2]
    assert len({tuple(x["embedding"]) for x in data}) == 3
    for item, row in zip(items, data):
        assert len(row["embedding"]) == 128
        assert math.sqrt(sum(x*x for x in row["embedding"])) == pytest.approx(1)
        single = call(client, item, dimensions=128).json()["data"][0]
        assert row["embedding"] == single["embedding"]
    encoded = call(client, items, dimensions=128, encoding_format="base64").json()["data"]
    for float_row, base64_row in zip(data, encoded):
        vec = struct.unpack("<128f", base64.b64decode(base64_row["embedding"]))
        assert vec == pytest.approx(float_row["embedding"], abs=1e-7)


def test_text_form_and_instruction_are_consistent(client):
    first = call(client, "cat").json()
    assert len(first["data"][0]["embedding"]) == 2048
    assert first == call(client, {"text": "cat"}).json()
    custom = call(client, "cat", instruction="Retrieve images").json()
    assert custom == call(client, {"text": "cat"}, instruction="Retrieve images.").json()
    assert custom["data"] != first["data"]


@pytest.mark.parametrize("value", [{}, {"image": "http://127.0.0.1/private"},
    {"image": "/etc/passwd"}, {"image": "data:image/png;base64,bm90IHBORw=="},
    {"image": "data:image/png;base64,%%%"}, {"text": 3}, {"video": "movie.mp4"},
    {"text": "x", "unknown": True}, {"image": "data:image/jpeg;base64,iVBORw0KGgo="}])
def test_invalid_multimodal_inputs_are_400(client, value):
    assert call(client, value).status_code == 400


def test_text_model_never_silently_drops_an_image(client):
    r = client.post("/v1/embeddings", json={"model": "textonly", "input": {"image": PNG}})
    assert r.status_code == 400
    assert "多模态" in r.text


def test_mrl_range_and_overlength(client):
    for dimension in (32, 63, 2049):
        assert call(client, "x", dimensions=dimension).status_code == 400
    assert call(client, "x", dimensions=64).status_code == 200
    assert call(client, "x" * 3000).status_code == 400
    assert call(client, [{"image": PNG}] * 17).status_code == 400


def test_multimodal_is_not_a_chat_model(client):
    r = client.post("/v1/chat/completions", json={"model": "multimodal",
        "messages": [{"role": "user", "content": "hello"}]})
    assert r.status_code == 400


def test_validation_preserves_text_and_image():
    assert validate_items(["x", {"image": PNG}]) == [{"text": "x"}, {"text": "", "image": PNG}]


def test_native_prompt_keeps_checkpoint_eos_postprocessor():
    from tokenizers import Tokenizer, models, processors

    # Same contract as the official embedding tokenizer: TemplateProcessing
    # appends an end-of-text token even though the rendered chat template ends
    # at the assistant prefix. Pooling the prefix instead changes the vector.
    engine = VLEmbedder.__new__(VLEmbedder)
    engine.tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "<|endoftext|>": 1}, unk_token="[UNK]"))
    engine.tokenizer.post_processor = processors.TemplateProcessing(
        single="$A <|endoftext|>", special_tokens=[("<|endoftext|>", 1)])
    engine.lib, engine.seq_len = None, 32
    engine.family = "qwen3_vl_embedding"
    prepared = engine.prepare("cat")
    assert prepared.ids == [0, 1]
    assert engine.input_tokens("cat") == 2
    engine.seq_len = 1
    with pytest.raises(ValueError, match="超过"):
        engine.prepare("cat")


def test_wemm_never_uses_bundled_qwen_tokenizer(tmp_path):
    models = tmp_path / "models"
    model = models / "wemm"
    model.mkdir(parents=True)
    (model / "wemm-embedding-2b_bf16_seq2048.bmodel").write_bytes(b"model")
    configs = tmp_path / "configs"
    wrong = configs / "qwen3_vl_embedding"
    wrong.mkdir(parents=True)
    (wrong / "embedding_config.json").write_text("{}")
    (wrong / "tokenizer.json").write_text("{}")
    manager = ModelManager(models, backend_kind="mock", log_dir=tmp_path / "logs")
    manager.model_config_root = configs
    manager.refresh()
    info = manager.get("wemm")
    assert info.supports_vision
    assert manager.config_dir_for(info) == model / "config"
    assert not info.has_config
    correct = configs / "wemm_embedding"
    correct.mkdir()
    (correct / "embedding_config.json").write_text("{}")
    (correct / "tokenizer.json").write_text("{}")
    assert manager.config_dir_for(info) == correct


@pytest.mark.parametrize("native_family,expected", [(0, "model families"), (1, None)])
def test_manifest_family_checked_against_bmodel(tmp_path, monkeypatch, native_family, expected):
    from types import SimpleNamespace
    import tokenizers
    import app.engine.vl_embed_native as native

    (tmp_path / "embedding_config.json").write_text(json.dumps({
        "model_type": "wemm_embedding", "seq_length": 2048, "hidden_size": 2048,
        "max_pixels": 1310720, "min_pixels": 65536}))
    class Tokenizer:
        def no_truncation(self): pass
        def no_padding(self): pass
        def encode(self, *args, **kwargs): return SimpleNamespace(ids=[1, 248077])
    monkeypatch.setattr(tokenizers.Tokenizer, "from_file", lambda *a: Tokenizer())
    closed = []
    def info(handle, seq, hidden, patches):
        seq._obj.value, hidden._obj.value, patches._obj.value = 2048, 2048, 5120
        return 0
    library = SimpleNamespace(
        cv_vle_create=lambda *a: 1, cv_vle_destroy=lambda h: closed.append(h),
        cv_vle_fault=lambda *a: 0, cv_vle_info=info, cv_vle_family=lambda *a: native_family,
        cv_vle_image_create=lambda *a: None, cv_vle_image_create_ex=lambda *a: None,
        cv_vle_image_destroy=lambda *a: None, cv_vle_forward=lambda *a: 0)
    monkeypatch.setattr(native.C, "CDLL", lambda *a: library)
    if expected:
        with pytest.raises(ValueError, match=expected):
            VLEmbedder("model.bmodel", str(tmp_path), "library.so")
    else:
        with VLEmbedder("model.bmodel", str(tmp_path), "library.so") as engine:
            assert engine.min_pixels == 65536
            assert engine.prepare("cat").ids[-1] == 248077
    assert closed == [1]
