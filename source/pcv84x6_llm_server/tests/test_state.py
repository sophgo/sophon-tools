import json

import pytest

from app.core.state import StateStore, hash_key


def test_default_admin_password_is_admin(tmp_path):
    s = StateStore(tmp_path / "state.json")
    assert s.verify_admin("admin")
    assert not s.verify_admin("wrong")


def test_key_roundtrip_and_lookup(tmp_path):
    s = StateStore(tmp_path / "state.json")
    raw, key = s.create_key("laptop")
    assert raw.startswith("sk-")
    assert s.find_key(raw) is key
    assert s.find_key("sk-nope") is None
    # The raw key must never be persisted.
    on_disk = (tmp_path / "state.json").read_text()
    assert raw not in on_disk
    assert hash_key(raw) in on_disk


def test_revoked_key_stops_working(tmp_path):
    s = StateStore(tmp_path / "state.json")
    raw, key = s.create_key("x")
    assert s.revoke_key(key.id)
    assert s.find_key(raw) is None


def test_public_view_hides_hash(tmp_path):
    s = StateStore(tmp_path / "state.json")
    _, key = s.create_key("x")
    assert "key_hash" not in key.public()


def test_persistence_survives_reload(tmp_path):
    p = tmp_path / "state.json"
    s = StateStore(p)
    raw, key = s.create_key("persisted")
    s.record_usage(key, 10, 20, cached_tokens=4, decode_tps=21.5)
    s.set_admin_password("hunter2")

    s2 = StateStore(p)
    assert s2.find_key(raw) is not None
    assert s2.usage.prompt_tokens == 10
    assert s2.usage.completion_tokens == 20
    assert s2.usage.cached_tokens == 4
    assert s2.verify_admin("hunter2")


def test_corrupt_state_does_not_brick_startup(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{ this is not json")
    s = StateStore(p)
    assert s.verify_admin("admin"), "must fall back to the default rather than raise"


def test_usage_accumulates_per_key_and_globally(tmp_path):
    s = StateStore(tmp_path / "state.json")
    _, k1 = s.create_key("a")
    _, k2 = s.create_key("b")
    s.record_usage(k1, 5, 5)
    s.record_usage(k2, 7, 3, cached_tokens=2)
    assert s.usage.requests == 2
    assert k1.requests == 1 and k2.requests == 1
    assert k2.cached_tokens == 2
    assert s.usage.prompt_tokens == 12


def test_tps_history_is_bounded(tmp_path):
    s = StateStore(tmp_path / "state.json")
    _, k = s.create_key("a")
    for i in range(800):
        s.record_usage(k, 1, 1, decode_tps=20 + i % 5)
    assert len(s.usage.tps_history) <= 720


def test_default_concurrency_is_two_and_cap_stays_three():
    """A fresh install starts at 2; the hard ceiling is still 3.

    The board's NPU serves one token at a time, so three sessions split ~18
    tok/s between them and the third mostly makes the other two later. Existing
    installs that saved 3 keep it -- clamp() must not rewrite a stored value
    back down to the default.
    """
    from app.core.state import DEFAULT_CONCURRENCY, MAX_CONCURRENCY, Settings

    assert Settings().max_concurrent_per_model == 2 == DEFAULT_CONCURRENCY
    assert MAX_CONCURRENCY == 3
    # The clamp still allows the whole 1..3 range in both directions.
    assert Settings(max_concurrent_per_model=1).clamp().max_concurrent_per_model == 1
    assert Settings(max_concurrent_per_model=3).clamp().max_concurrent_per_model == 3
    assert Settings(max_concurrent_per_model=9).clamp().max_concurrent_per_model == 3
    assert Settings(max_concurrent_per_model=0).clamp().max_concurrent_per_model == 1


def test_stored_concurrency_of_three_survives_a_reload(tmp_path):
    """An operator who already chose 3 must not be silently moved to 2."""
    p = tmp_path / "state.json"
    s = StateStore(p)
    s.settings.max_concurrent_per_model = 3
    s.save()
    assert StateStore(p).settings.max_concurrent_per_model == 3


# -- inference log settings (MYS-2496) -------------------------------------
def test_inference_log_defaults_are_on_with_bounded_retention():
    from app.core.state import Settings

    s = Settings()
    assert s.inference_logging_enabled is True
    assert s.inference_log_retention_count == 1000
    assert s.inference_log_retention_days == 30


def test_an_old_state_file_gains_the_log_settings_and_keeps_its_own(tmp_path):
    """Upgrading a deployed board must not reset anything it already has.

    A v0.6.12 state.json has no inference-log keys at all; loading it has to
    default the new switch to *on* (the whole point is that the next bad answer
    is explainable) while leaving every existing field exactly as it was.
    """
    p = tmp_path / "state.json"
    p.write_text(json.dumps({
        "keys": [{"id": "k1", "name": "old", "key_hash": hash_key("sk-old"),
                  "prefix": "sk-old…", "created_at": 1.0, "revoked": False,
                  "prompt_tokens": 5, "completion_tokens": 6, "requests": 1,
                  "cached_tokens": 0}],
        "settings": {"max_concurrent_per_model": 3, "prefix_cache_max_mb": 512,
                     "prefix_cache_ttl_min": 30, "max_queue": 4,
                     "prefill_exact_tail": 128, "require_api_key": True,
                     "max_loaded_models": 2, "prefix_cache_entries": 32,
                     "admin_password_hash": hash_key("hunter2")},
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "requests": 1,
                  "cached_tokens": 0, "tps_history": [[1.0, 20.0]]},
    }))

    s = StateStore(p)
    assert s.settings.inference_logging_enabled is True
    assert s.settings.inference_log_retention_count == 1000
    assert s.settings.inference_log_retention_days == 30
    # Nothing that was already configured moved.
    assert s.settings.max_concurrent_per_model == 3
    # ``prefix_cache_max_mb`` was deleted in v0.6.34 (MYS-2785): the old 512 is
    # ignored, not migrated into some other field.
    assert not hasattr(s.settings, "prefix_cache_max_mb")
    assert s.settings.prefix_cache_ttl_min == 30
    assert s.settings.max_queue == 4
    assert s.verify_admin("hunter2")
    assert s.find_key("sk-old") is not None
    assert s.usage.prompt_tokens == 10


def test_inference_log_settings_round_trip_and_clamp(tmp_path):
    p = tmp_path / "state.json"
    s = StateStore(p)
    s.settings.inference_logging_enabled = False
    s.settings.inference_log_retention_count = 100_000
    s.settings.inference_log_retention_days = 3650
    s.save()
    reloaded = StateStore(p)
    assert reloaded.settings.inference_logging_enabled is False
    assert reloaded.settings.inference_log_retention_count == 100_000
    assert reloaded.settings.inference_log_retention_days == 3650

    # Out-of-range values in a hand-edited file are clamped, not obeyed.
    data = json.loads(p.read_text())
    data["settings"]["inference_log_retention_count"] = 0
    data["settings"]["inference_log_retention_days"] = 99999
    p.write_text(json.dumps(data))
    clamped = StateStore(p).settings
    assert clamped.inference_log_retention_count == 1
    assert clamped.inference_log_retention_days == 3650
