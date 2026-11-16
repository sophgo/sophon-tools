"""Engine backend abstraction.

The scheduler, prefix cache, HTTP layer and stats all talk to this interface only.
Two implementations exist:

* ``MockBackend``  -- deterministic fake inference; lets the whole service be
  developed and tested on x86 without an NPU.
* ``SailBackend``  -- the real thing, driving ``sophon.sail.EngineLLM``.

Keeping the seam this narrow is deliberate: everything except the ~200 lines of
``sail_backend.py`` is verifiable off-device.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import AsyncIterator, Sequence

# A token is just an int for our purposes; the tokenizer lives in the backend
# because it ships with the model directory.
Token = int


@dataclass
class GenerateParams:
    """Sampling parameters, mirroring the OpenAI request fields."""

    max_tokens: int = 512
    temperature: float = 0.8
    top_p: float = 0.8
    top_k: int = 50
    repetition_penalty: float = 1.1
    stop: list[str] = field(default_factory=list)
    seed: int | None = None


@dataclass
class TokenEvent:
    """One streamed chunk."""

    text: str
    token: Token | None = None


@dataclass
class GenerateResult:
    """What the scheduler records once a request finishes."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    first_token_latency_s: float | None = None
    decode_tps: float | None = None
    finish_reason: str = "stop"


class Session(abc.ABC):
    """One conversation's decoding state.

    A session owns its KV cache inside the backend, which is what makes
    concurrent requests possible without reloading weights: many sessions, one
    set of weights.
    """

    @property
    @abc.abstractmethod
    def token_len(self) -> int:
        """Number of prompt tokens currently in the session's KV cache."""

    @abc.abstractmethod
    async def feed_prompt(self, tokens: Sequence[Token]) -> None:
        """Prefill ``tokens`` into the session's KV cache.

        Implementations may do this in chunks so the scheduler can interleave
        other sessions; ``feed_prompt`` should be resumable.
        """

    @abc.abstractmethod
    async def step(self) -> Token:
        """Decode one token, advancing the session."""

    @abc.abstractmethod
    def decode(self, tokens: Sequence[Token]) -> str:
        """Detokenize. Used to turn sampled ids into text for streaming."""

    def decode_bytes(self, tokens: Sequence[Token]) -> bytes:
        """Detokenize to raw UTF-8 bytes, before any text conversion.

        Byte-level tokenizers (BPE over a byte alphabet) split a multi-byte
        character across tokens: ``门簪`` is three ids here, the first holding
        the three bytes of ``门`` and the others two thirds and one third of
        ``簪``. Decoding each id on its own can only produce U+FFFD for the
        fragments, and U+FFFD is not recoverable, so the scheduler needs the
        bytes and has to assemble them across tokens itself.

        The default is right for backends whose decode is text already (the
        mock, SAIL): it round-trips through UTF-8 and the scheduler's
        incremental decoder then finds nothing to join. Byte-level backends
        override it.
        """
        return self.decode(tokens).encode("utf-8")

    @abc.abstractmethod
    def is_stop_token(self, token: Token) -> bool:
        """True when ``token`` ends the sequence."""

    @abc.abstractmethod
    async def snapshot(self, token_len: int) -> object:
        """Capture the KV state for exactly ``token_len`` tokens.

        ``token_len`` is required, not implied by the session's current length.
        The prefix cache keys a snapshot on the *prompt* prefix, so capturing
        the whole session (prompt + everything generated so far) would store KV
        that the cache then advertises as not existing. Restoring such a
        snapshot would silently start decoding from a longer context than the
        request asked for.

        The handle is opaque to the scheduler; it is handed back to
        :meth:`restore` later. Backends must treat it as immutable.
        """

    @abc.abstractmethod
    async def restore(self, snap: object) -> None:
        """Load a snapshot produced by :meth:`snapshot` into this session."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Release KV cache and any backend resources."""


class EngineBackend(abc.ABC):
    """A loaded model."""

    @property
    @abc.abstractmethod
    def model_id(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def context_length(self) -> int:
        """Hard cap on total tokens (prompt + completion)."""

    @property
    @abc.abstractmethod
    def supports_vision(self) -> bool:
        ...

    @property
    def supports_sampling(self) -> bool:
        """Whether temperature/top_p/top_k actually affect the output.

        A bmodel whose lm_head emits a single int32 has the argmax fused into the
        graph, so there is no distribution left to sample from: the server can
        only return the argmax. Reporting this lets the API and console say so
        plainly instead of accepting the parameters and silently ignoring them,
        which would make "temperature: 1.5" look broken rather than unsupported.
        """
        return True

    @property
    def supports_chunked_prefill(self) -> bool:
        """Whether ``feed_prompt`` may be called repeatedly to extend a prompt.

        The mock can; the SAIL backend cannot, because the prefill graph builds
        its attention mask for the whole prompt and there is no way to extend it
        mid-prefill. The scheduler asks rather than assuming, so the limitation
        is explicit instead of a silent wrong-mask bug on the board.
        """
        return True

    @abc.abstractmethod
    async def encode(self, text: str, images: Sequence[bytes] | None = None) -> list[Token]:
        """Tokenize a prompt, expanding image placeholders when given images."""

    @abc.abstractmethod
    async def new_session(self) -> Session:
        ...

    @abc.abstractmethod
    async def close(self) -> None:
        ...
