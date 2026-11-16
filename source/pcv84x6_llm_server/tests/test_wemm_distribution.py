"""A catalogue download must work without a manually copied tokenizer."""
import hashlib
import json
from pathlib import Path

from tokenizers import Tokenizer

from app.core.downloader import catalog_entry
from app.core.models import ModelManager, discover_models
from app.engine.vl_embed_native import render_prompt

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "model-config/wemm_embedding"


def test_downloaded_wemm_uses_its_bundled_config(tmp_path):
    entry = catalog_entry("wemm-embedding-2b")
    directory = tmp_path / "models" / entry["id"]
    directory.mkdir(parents=True)
    (directory / entry["dfss"].rsplit("/", 1)[1]).write_bytes(b"model")
    manager = ModelManager(tmp_path / "models", backend_kind="mock", log_dir=tmp_path / "logs")
    manager.model_config_root = ROOT / "model-config"
    info = discover_models(tmp_path / "models")[0]
    assert info.kind == "embedding"
    assert manager.config_dir_for(info) == CONFIG
    assert manager.refresh()[0].has_config
    # A local config still wins; package upgrades must not override it.
    local = directory / "config"
    local.mkdir()
    (local / "tokenizer.json").write_text("{}")
    assert manager.config_dir_for(info) == local


def test_bundled_wemm_matches_the_published_model_contract():
    entry = catalog_entry("wemm-embedding-2b")
    manifest = json.loads((CONFIG / "embedding_config.json").read_text())
    assert entry["vision"] and entry["context"] == manifest["seq_length"] == 2048
    assert entry["vector_family"] == manifest["vector_family"] == "tencent/WeMM-Embedding-2B"
    assert entry["dflag"] == "cv84x6_llm_wemm-embedding-2b"
    assert entry["size_bytes"] == 3121778688
    assert entry["md5"] == "2065f4c866be364c0607b705c07f3dc4"
    assert manifest["model_type"] == "wemm_embedding"
    assert manifest["gdn_implementation"] == "static_primitives_v2"
    assert manifest["full_attention_codegen"] == "static_ungrouped"
    assert manifest["buckets"] == [128, 512, 1024, 2048]
    tokenizer = Tokenizer.from_file(str(CONFIG / "tokenizer.json"))
    tokenizer.no_padding()
    tokenizer.no_truncation()
    ids = tokenizer.encode(render_prompt("A cat.", family="wemm_embedding")).ids
    assert ids[-1] == 248077
    assert ids.count(248077) == 1
    assert tokenizer.token_to_id("<|image_pad|>") == 248056


def test_bundled_config_hashes_match_distribution_manifest():
    manifest = json.loads((CONFIG / "distribution.json").read_text())
    for name, digest in manifest["config_sha256"].items():
        assert hashlib.sha256((CONFIG / name).read_bytes()).hexdigest() == digest, name
