"""Durable service state.

Everything the UI must remember across restarts: API keys (hash only), settings,
cumulative usage. Writes are atomic (temp file + ``os.replace``) because the
board loses power without warning and a half-written JSON would take the whole
service down at boot.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


#: What a key is allowed to call (MYS-2676). ``inference`` keys drive ``/v1``;
#: ``admin`` keys may also drive every ``/api/*`` route, which is how a script
#: manages the service without a browser session. Kept as two strings in
#: ``state`` (rather than imported from ``core.auth``) so the state file needs no
#: import of a module that itself imports ``state``.
SCOPE_INFERENCE = "inference"
SCOPE_ADMIN = "admin"
SCOPES = (SCOPE_INFERENCE, SCOPE_ADMIN)


@dataclass
class ApiKey:
    id: str
    name: str
    key_hash: str
    prefix: str            # first few chars, for display: "sk-abcd…"
    created_at: float
    revoked: bool = False
    # Cumulative usage, so the UI can show per-key cost without scanning logs.
    prompt_tokens: int = 0
    completion_tokens: int = 0
    requests: int = 0
    cached_tokens: int = 0
    #: ``inference`` or ``admin``. The default is what every key minted before
    #: MYS-2676 means, so an older ``state.json`` -- whose rows have no ``scope``
    #: at all -- loads as a set of inference keys with no migration step. A
    #: value this build does not know (a hand edit, a downgrade) is read as
    #: ``inference``: the narrower permission is the safe interpretation, and
    #: the alternative is an unparseable state file that bricks the service.
    scope: str = SCOPE_INFERENCE

    def __post_init__(self) -> None:
        if self.scope not in SCOPES:
            self.scope = SCOPE_INFERENCE

    def public(self) -> dict:
        d = asdict(self)
        d.pop("key_hash", None)  # never leaves the process
        return d


MAX_CONCURRENCY = 3  # hard cap per model; the NPU serves one token at a time

# What a fresh install starts with. Two, not the cap of three: three sessions
# share the board's decode throughput (~18 tok/s between them in total), so the
# third one mostly makes the other two later. An operator who already saved 3
# keeps it -- clamp() does not rewrite a stored value.
DEFAULT_CONCURRENCY = 2

#: The upper bound the console's idle-unload field accepts, in minutes (a day).
#: Bounded rather than open because the value is persisted and drives a timer.
AUX_IDLE_UNLOAD_MAX_MIN = 1440
#: (aux_idle_unload_min, aux_auto_load) as v0.6.27 defaulted them.
_AUX_OLD_ON = (10, True)

#: Settings fields that no longer exist but may still be in a state file. They are
#: dropped on load, so the value is ignored *and* the next ``save`` stops writing
#: it: without this an upgraded board would keep advertising a setting that does
#: nothing. ``Settings(**...)`` already filters on ``__annotations__``, so the
#: value could not be read either way -- this tuple makes the dropping explicit
#: and testable (MYS-2785). The matching accept-and-ignore on the wire lives in
#: ``SettingsBody``, which keeps the field as a deprecated no-op so a console
#: built before the deletion can still save its form.
LEGACY_SETTING_FIELDS = ("prefix_cache_max_mb",)

#: Retention bounds for the management audit trail, in days. Shared by
#: ``Settings.clamp``, the settings API and ``AuditStore`` so a value can never
#: be accepted by one and refused by another.
AUDIT_RETENTION_DAYS_MIN, AUDIT_RETENTION_DAYS_MAX = 30, 3650
AUDIT_RETENTION_DAYS_DEFAULT = 180

#: The smallest per-model memory limit the settings API accepts, in MiB. Not 1:
#: a limit below a small auxiliary model's own static footprint can never be
#: satisfied and would turn every load into a 409 with no way out. 64 MiB is
#: under every model this service ships, so it is reachable, and low enough that
#: an operator can still use it to squeeze a board deliberately.
MEM_LIMIT_MB_MIN = 64
#: Largest accepted per-model limit, in MiB (1 TiB). Bounded rather than open
#: because the value is persisted and compared against device readings.
MEM_LIMIT_MB_MAX = 1024 * 1024


@dataclass
class ModelSettings:
    """What an operator configured for one model, independently of the others.

    Every field's ``None`` means "follow the default", and the default is a
    different thing per field:

      * ``idle_unload_min`` / ``auto_load`` -- follow the **global** settings
        (``Settings.aux_idle_unload_min`` / ``aux_auto_load``), whose meaning
        is exactly "the value an auxiliary model uses when nobody configured
        it individually". That is why these start out as ``None`` rather than
        as a copy of today's global value: a copy would freeze the model at the
        old number the moment the operator changed the global one.
      * ``mem_limit_mb`` -- follow this model's **derived** default
        (``app.core.mem_limit.default_limit_bytes``), which is a function of the
        model's own static footprint and kind, not of any global setting.

    A dataclass rather than a bare dict so a state file with an unknown key
    cannot smuggle a field into the comparison the API does; ``from_json``
    drops anything it does not know.
    """

    idle_unload_min: int | None = None
    auto_load: bool | None = None
    mem_limit_mb: int | None = None

    def to_json(self) -> dict:
        return {
            "idle_unload_min": self.idle_unload_min,
            "auto_load": self.auto_load,
            "mem_limit_mb": self.mem_limit_mb,
        }

    @classmethod
    def from_json(cls, raw: object) -> "ModelSettings" | None:
        """Parse one entry of ``state.json``'s ``model_settings`` map.

        Returns None when there is nothing worth keeping (an empty object, a
        non-object, or one whose every field failed validation): a settings
        entry that says nothing is the same as no entry, and storing it would
        make ``PUT`` and a fresh model indistinguishable in the API response.

        Invalid values are **dropped to None**, not refused: the file may have
        been edited by hand or written by a version with different bounds, and
        a bad field must not take the whole service down at boot. ``null`` is
        the "follow the default" answer, which is the safe interpretation.
        """
        if not isinstance(raw, dict):
            return None
        out = cls()
        minutes = raw.get("idle_unload_min")
        if minutes is not None and not isinstance(minutes, bool):
            try:
                minutes = int(minutes)
            except (TypeError, ValueError):
                minutes = None
            if minutes is not None and 0 <= minutes <= AUX_IDLE_UNLOAD_MAX_MIN:
                out.idle_unload_min = minutes
        auto = raw.get("auto_load")
        if isinstance(auto, bool):
            out.auto_load = auto
        limit = raw.get("mem_limit_mb")
        if limit is not None and not isinstance(limit, bool):
            try:
                limit = int(limit)
            except (TypeError, ValueError):
                limit = None
            if limit is not None and MEM_LIMIT_MB_MIN <= limit <= MEM_LIMIT_MB_MAX:
                out.mem_limit_mb = limit
        if out.idle_unload_min is None and out.auto_load is None and out.mem_limit_mb is None:
            return None
        return out

    def is_default(self) -> bool:
        """True when every field follows its default: nothing to persist."""
        return (self.idle_unload_min is None and self.auto_load is None
                and self.mem_limit_mb is None)



@dataclass
class Settings:
    max_concurrent_per_model: int = DEFAULT_CONCURRENCY
    #: Unused since v0.6.25 (kept so older state files still load); the count
    #: limit comes from ``--max-loaded`` only.
    max_loaded_models: int = 0
    prefix_cache_entries: int = 32
    admin_password_hash: str = ""
    require_api_key: bool = True
    # Prefix cache: how many entries are kept and how long an unused one lives.
    # There is deliberately **no service-wide byte ceiling** any more (MYS-2785):
    # the cache shares each model's own runtime budget (``limit - static``), so
    # "how much may this model occupy" answers the cache question too. A stale
    # ``prefix_cache_max_mb`` in an old state file is dropped on load -- see
    # ``LEGACY_SETTING_FIELDS``.
    prefix_cache_ttl_min: int = 120
    # Requests waiting for a slot before new ones get HTTP 429.
    max_queue: int = 16
    # Prompts of EXACT_TAIL_MIN_PROMPT+ tokens prefill their last this-many
    # tokens through the decode graphs (exact routed-expert MoE, ~40 ms per
    # token) -- the prefill graphs' MoE is inaccurate on CV84X6. Shorter
    # prompts use min(this, SHORT_EXACT_TAIL). 0 = off for all prompts.
    prefill_exact_tail: int = 64
    # Inference audit log (MYS-2496). On by default: on a customer site the
    # ability to explain a wrong answer is worth more than the disk it costs.
    # Retention is count *and* days -- whichever keeps fewer rows wins.
    inference_logging_enabled: bool = True
    inference_log_retention_count: int = 1000
    inference_log_retention_days: int = 30
    # Auxiliary models (embedding/rerank/asr/ocr) hold the NPU and several
    # hundred MB of system RAM for as long as they are loaded, and a console
    # operator loads one to try it once. Unloading it after this many minutes
    # idle gives that memory back; the next request loads it again. 0 = never.
    #
    # Since MYS-2675 this is the **default for models nobody configured
    # individually**, not a blanket policy: ``model_settings[<id>]`` overrides
    # it per model, and that is how a chat model (excluded here) can opt in.
    # It still applies only to ``AUX_KINDS`` when a model has no entry of its
    # own, so an existing install behaves exactly as before.
    #
    # Off by default (the operator opts in on the settings page): a model the
    # operator loaded stays loaded until they unload it.
    aux_idle_unload_min: int = 0
    #: Load an auxiliary model on demand instead of answering 409 "not loaded".
    #: The cost is a few seconds on the first request after an idle unload (tens
    #: of seconds for a chat model). Off by default, like the idle unload, and
    #: likewise now the default for models without their own entry.
    aux_auto_load: bool = False
    #: Which defaults the two aux settings above were written under. v0.6.27
    #: shipped them on (10 min / true) and ``save`` persists every field, so a
    #: state file from that release carries those values without the operator
    #: having chosen them; ``load`` turns them off once (see ``_AUX_OLD_ON``).
    aux_defaults_rev: int = 1
    # Management audit trail (MYS-2674): how long an operation record is kept.
    # Days only -- there is no count cap, because "the last 1000 changes" on a
    # quiet board is a year and on a busy one an afternoon, and neither is a
    # policy an operator asked for. 180 days is the default.
    audit_retention_days: int = AUDIT_RETENTION_DAYS_DEFAULT

    def clamp(self) -> "Settings":
        """Force values into their valid ranges (also for old state files)."""
        self.max_concurrent_per_model = max(1, min(MAX_CONCURRENCY, int(self.max_concurrent_per_model)))
        self.prefix_cache_entries = max(1, min(256, int(self.prefix_cache_entries)))
        self.prefix_cache_ttl_min = max(0, min(7 * 24 * 60, int(self.prefix_cache_ttl_min)))
        self.max_queue = max(0, min(256, int(self.max_queue)))
        self.prefill_exact_tail = max(0, min(1024, int(self.prefill_exact_tail)))
        self.inference_logging_enabled = bool(self.inference_logging_enabled)
        self.inference_log_retention_count = max(
            1, min(100_000, int(self.inference_log_retention_count)))
        self.inference_log_retention_days = max(
            1, min(3650, int(self.inference_log_retention_days)))
        self.aux_idle_unload_min = max(0, min(AUX_IDLE_UNLOAD_MAX_MIN,
                                             int(self.aux_idle_unload_min)))
        self.aux_auto_load = bool(self.aux_auto_load)
        self.audit_retention_days = max(
            AUDIT_RETENTION_DAYS_MIN, min(AUDIT_RETENTION_DAYS_MAX,
                                          int(self.audit_retention_days)))
        return self


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    requests: int = 0
    cached_tokens: int = 0
    # Rolling samples for the throughput chart: (epoch_seconds, decode_tps).
    tps_history: list[list[float]] = field(default_factory=list)


class StateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.keys: list[ApiKey] = []
        self.settings = Settings()
        #: Per-model overrides, keyed by model id (the directory name, which is
        #: what every API path uses). Only models an operator changed appear
        #: here: an absent key and an all-``None`` entry mean the same thing,
        #: and the absent one is what keeps the file from growing a row per
        #: model on a board that never touched them.
        self.model_settings: dict[str, ModelSettings] = {}
        self.usage = Usage()
        self.load()

    # -- io --------------------------------------------------------------
    def load(self) -> None:
        if not self.path.exists():
            self.settings.admin_password_hash = hash_key("admin")
            return
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            # Corrupt state must not brick the service; start clean and let the
            # operator notice via the UI rather than a crash loop.
            self.settings.admin_password_hash = hash_key("admin")
            return
        self.keys = [ApiKey(**k) for k in data.get("keys", [])]
        s = data.get("settings") or {}
        # A field this release deleted (``prefix_cache_max_mb``) is dropped here,
        # not just left for the constructor's annotation filter: the value is
        # ignored *and* the next ``save`` does not write it back, so an upgraded
        # board stops advertising a setting that no longer does anything.
        s = {k: v for k, v in s.items() if k not in LEGACY_SETTING_FIELDS}
        if "aux_defaults_rev" not in s and (
                s.get("aux_idle_unload_min"), s.get("aux_auto_load")) == _AUX_OLD_ON:
            # Written by v0.6.27 with its on-by-default values: apply the new
            # off defaults. Any other value was set by the operator; keep it.
            s = {**s, "aux_idle_unload_min": 0, "aux_auto_load": False}
        self.settings = Settings(**{k: v for k, v in s.items() if k in Settings.__annotations__}).clamp()
        if not self.settings.admin_password_hash:
            self.settings.admin_password_hash = hash_key("admin")
        # An older state file simply has no `model_settings`, and every model
        # then follows the defaults -- which is the pre-MYS-2675 behaviour
        # exactly, so an upgrade needs no migration step.
        raw_models = data.get("model_settings") or {}
        self.model_settings = {}
        if isinstance(raw_models, dict):
            for model_id, entry in raw_models.items():
                if not isinstance(model_id, str) or not model_id:
                    continue
                parsed = ModelSettings.from_json(entry)
                if parsed is not None:
                    self.model_settings[model_id] = parsed
        u = data.get("usage") or {}
        self.usage = Usage(**{k: v for k, v in u.items() if k in Usage.__annotations__})

    def save(self) -> None:
        with self._lock:
            payload = {
                "keys": [asdict(k) for k in self.keys],
                "settings": asdict(self.settings),
                "model_settings": {
                    mid: entry.to_json()
                    for mid, entry in sorted(self.model_settings.items())
                    if not entry.is_default()
                },
                "usage": asdict(self.usage),
            }
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2))
            os.replace(tmp, self.path)  # atomic on POSIX: no torn state on power loss

    # -- keys ------------------------------------------------------------
    def create_key(self, name: str, scope: str = SCOPE_INFERENCE) -> tuple[str, ApiKey]:
        """Mint a key. ``scope`` decides what it may call (MYS-2676).

        The scope is *stored on the row*, not derived from the name or the
        caller: the same key has to keep its permission across a restart, and
        an agent that was handed an inference key must not acquire management
        rights because the code that mints keys changed.
        """
        if scope not in SCOPES:
            raise ValueError(f"scope must be one of {', '.join(SCOPES)}, got {scope!r}")
        raw = "sk-" + secrets.token_urlsafe(32)
        key = ApiKey(
            id=secrets.token_hex(8),
            name=name,
            key_hash=hash_key(raw),
            prefix=raw[:10] + "…",
            created_at=time.time(),
            scope=scope,
        )
        with self._lock:
            self.keys.append(key)
            self.save()
        return raw, key

    def find_key(self, raw: str) -> ApiKey | None:
        h = hash_key(raw)
        for k in self.keys:
            if not k.revoked and secrets.compare_digest(k.key_hash, h):
                return k
        return None

    def revoke_key(self, key_id: str) -> bool:
        with self._lock:
            for k in self.keys:
                if k.id == key_id:
                    k.revoked = True
                    self.save()
                    return True
        return False

    def delete_key(self, key_id: str) -> bool:
        with self._lock:
            before = len(self.keys)
            self.keys = [k for k in self.keys if k.id != key_id]
            if len(self.keys) != before:
                self.save()
                return True
        return False

    # -- usage -----------------------------------------------------------
    def record_usage(
        self, key: ApiKey | None, prompt_tokens: int, completion_tokens: int,
        cached_tokens: int = 0, decode_tps: float | None = None,
    ) -> None:
        with self._lock:
            self.usage.prompt_tokens += prompt_tokens
            self.usage.completion_tokens += completion_tokens
            self.usage.cached_tokens += cached_tokens
            self.usage.requests += 1
            if decode_tps:
                self.usage.tps_history.append([time.time(), round(decode_tps, 2)])
                # Keep ~2h at one sample per few seconds; bounded so the state
                # file cannot grow without limit.
                if len(self.usage.tps_history) > 720:
                    self.usage.tps_history = self.usage.tps_history[-720:]
            if key is not None:
                key.prompt_tokens += prompt_tokens
                key.completion_tokens += completion_tokens
                key.cached_tokens += cached_tokens
                key.requests += 1
            self.save()

    def verify_admin(self, password: str) -> bool:
        return secrets.compare_digest(self.settings.admin_password_hash, hash_key(password))

    def set_admin_password(self, password: str) -> None:
        with self._lock:
            self.settings.admin_password_hash = hash_key(password)
            self.save()

    # -- per-model settings (MYS-2675) ------------------------------------
    def get_model_settings(self, model_id: str) -> ModelSettings:
        """The overrides stored for ``model_id``; all-``None`` when it has none.

        Always returns a fresh object rather than the stored one: a caller that
        edits the result must not change the store without going through
        ``set_model_settings``, which is what writes the file.
        """
        with self._lock:
            entry = self.model_settings.get(model_id)
            return ModelSettings() if entry is None else ModelSettings(**entry.to_json())

    def set_model_settings(self, model_id: str, entry: ModelSettings) -> None:
        """Replace ``model_id``'s overrides and persist.

        An all-``None`` entry is *removed* rather than stored: a model the
        operator reset to the defaults should look exactly like one nobody ever
        touched, in this process and in the file.

        **All or nothing, in memory as well as on disk** (MYS-2801). The old
        order -- edit the live dict, then call ``save`` -- left a half write
        behind when the disk refused: the management plane reported the new
        ``mem_limit_mb``, the worker had it rolled back, and the file still had
        the old one, so three readers of the same "setting" disagreed. The dict
        is now edited, saved, and rolled back on failure, which is what lets the
        API's rollback story ("the file did not take it, so the worker is put
        back") actually hold: nothing else about any model's settings is touched,
        and a failure leaves the previous entry -- including "there was none" and
        including ``None``-means-default -- exactly as it was.
        """
        with self._lock:
            missing = object()
            previous = self.model_settings.get(model_id, missing)
            if entry.is_default():
                self.model_settings.pop(model_id, None)
            else:
                self.model_settings[model_id] = ModelSettings(**entry.to_json())
            try:
                self.save()
            except BaseException:
                # Restore the *object identity* the file still describes -- a
                # caller holding a reference from ``get_model_settings`` is
                # unaffected, because that always hands out a copy.
                if previous is missing:
                    self.model_settings.pop(model_id, None)
                else:
                    self.model_settings[model_id] = previous
                raise

    def forget_model_settings(self, model_id: str) -> bool:
        """Drop ``model_id``'s overrides (called when the model is deleted).

        Returns whether anything was there. A deletion that leaves the entry
        behind would re-apply a stale limit to a *different* model downloaded
        under the same name later -- including an idle threshold the operator
        never chose for it.
        """
        with self._lock:
            if self.model_settings.pop(model_id, None) is None:
                return False
            self.save()
            return True
