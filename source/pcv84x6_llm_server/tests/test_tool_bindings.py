"""Every engine C-ABI call a tool makes must declare its argtypes.

Why this is a test and not a code-review note: ctypes' default argument
conversion for an undeclared function turns anything that is not a ctypes type
into a C ``int``. A pointer built from a ctypes array therefore arrives at the
engine truncated to 32 bits, the engine dereferences garbage, and the process
dies with SIGSEGV *inside the engine* -- which reads like an engine fault and
sends the investigation to the wrong place.

That is exactly what happened to ``tools/session_bench.py``: it called
``llm_session_extend`` with no ``argtypes`` while ``llm_session_prefill`` (same
signature) had them. Every other call in the script was fine, so the crash
appeared only on the restore->extend path -- looking for all the world like a
state-machine bug in the engine.

The test is structural because the bug is: it parses each tool, finds the
``llm_*`` entry points it calls, and requires each one to be configured.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOLS = sorted(p for p in (ROOT / "tools").glob("*.py"))

# Entry points that take no pointer argument: every argument is a handle
# (c_void_p) or an integer, both of which ctypes passes correctly without
# argtypes. Kept explicit rather than inferred, so adding a pointer-taking
# function to this list is a visible change.
SCALAR_ONLY = {
    "llm_engine_num_layers",
    "llm_engine_context_length",
    "llm_engine_max_input_length",
    "llm_engine_hidden_size",
    "llm_engine_has_vision",
    "llm_engine_vit_max_patches",
    "llm_engine_vit_dims",
    "llm_engine_supports_history",
    "llm_engine_fault",
    "llm_engine_session_state_bytes",
    "llm_engine_kv_bytes_per_token",
    "llm_engine_linear_state_bytes",
    "llm_engine_vocab_size",
    "llm_snapshot_bytes",
    "llm_session_token_len",
    "llm_last_error",
}


def _calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr.startswith("llm_"):
            names.add(fn.attr)
    return names


def _declared(path: Path) -> set[str]:
    return set(re.findall(r"\.(llm_\w+)\.argtypes", path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("tool", TOOLS, ids=lambda p: p.name)
def test_every_pointer_taking_engine_call_declares_argtypes(tool: Path):
    missing = (_calls(tool) - _declared(tool)) - SCALAR_ONLY
    assert not missing, (
        f"{tool.name} calls {sorted(missing)} without argtypes. ctypes will pass "
        f"any ctypes-array pointer as a 32-bit int, so the engine receives a "
        f"truncated address and crashes. Declare argtypes (and restype) for it.")
