"""Run tpu-mlir's llm_convert.py with a Qwen3-ASR converter that takes `loader`.

The tpuc22 container's tpu_mlir 1.30.2 ships a `Qwen3AsrConverter.__init__(self,
args, config)` -- it predates `llm_convert.py` passing `loader=`, a keyword only
GGUF models actually need. LlmConverter itself already falls back to building a
SafetensorsModelHandle when `loader is None` (LlmConverter.py:369-371), so
ignoring the keyword is behaviour-preserving for a safetensors checkpoint.

The patch goes into ``sys.modules`` because llm_convert.py re-imports the
converter by module name; patching only the class we imported here would leave
that second import holding the original. Nothing on disk changes -- 35B
compilation shares this container's site-packages.

    PYTHONPATH=/workspace/asr/stub python /workspace/asr/asr_convert.py <llm_convert args...>
"""

from __future__ import annotations

import runpy
import sys

import tpu_mlir.python.llm.Qwen3AsrConverter as _mod

_orig_init = _mod.Qwen3AsrConverter.__init__


def _init_without_loader(self, args, config, loader=None):
    # The same instance the base class would build for a safetensors checkpoint.
    _orig_init(self, args, config)


_mod.Qwen3AsrConverter.__init__ = _init_without_loader
sys.modules["llm.Qwen3AsrConverter"] = _mod
sys.modules["tpu_mlir.python.llm.Qwen3AsrConverter"] = _mod

TARGET = "/usr/local/lib/python3.10/dist-packages/tpu_mlir/python/tools/llm_convert.py"
sys.argv = [TARGET, *sys.argv[1:]]
runpy.run_path(TARGET, run_name="__main__")
