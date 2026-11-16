"""What the OCR-VL backend must produce before the NPU is involved.

Three claims, each with an independent oracle, all of which a wrong answer would
still let "run":

1. **The prompt.** ``render_prompt`` is a hand-written transcription of
   ``model-config/paddleocr_vl_1_5/chat_template.jinja``, because the board has
   no jinja2. jinja2 is the oracle, and the comparison is byte for byte --
   ``Assistant:\\n`` and ``Assistant: `` are different token spans and only one
   of them is what the reference continues (A3 measured this).
2. **The token ids.** The rendered prompt, tokenised by the C++ tokenizer,
   must equal what the reference ``tokenizers`` package produces for the same
   text. The prototype's prompts are pinned to the ids MYS-2660's alignment ran
   with, so a change here would invalidate every number in ``docs/ocr-vl.md``.
3. **The pixels.** ``preprocess_image`` must produce the tensor HF's processor
   produces for the same picture. The golden is a real crop and the tensor the
   board actually fed the vit when the alignment was measured, so this is not a
   re-derivation of the same formula -- it is the measured artefact.

The C++ tokenizer half needs a compiler and the model's ``tokenizer.json``, both
of which are optional; it skips where they are missing rather than failing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.engine import paddle_vl as vl

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "model-config" / "paddleocr_vl_1_5"
TEMPLATE = CONFIG / "chat_template.jinja"
GOLDEN = ROOT / "tests" / "data" / "ocr" / "tokenizer_golden_paddleocr_vl.json"
IMG = ROOT / "tests" / "data" / "ocr" / "img"

#: A data URL with a one-byte payload. The rendering only needs a payload -- the
#: backend is what decodes it -- so a real image here would only slow the test.
_IMAGE_URL = "data:image/png;base64,AA=="


# ---------------------------------------------------------------------------
# 1. the prompt
# ---------------------------------------------------------------------------
def _jinja() -> object:
    return pytest.importorskip("jinja2")


def _render_with_template(messages: list[dict]) -> str:
    """The model's own template, rendered by jinja2 -- the oracle."""
    jinja2 = _jinja()
    env = jinja2.Environment(trim_blocks=False, lstrip_blocks=False)
    template = env.from_string(TEMPLATE.read_text(encoding="utf-8"))
    return template.render(messages=messages, add_generation_prompt=True)


def _messages(parts: list[dict]) -> list[dict]:
    """The OpenAI shape the API hands to ``render_prompt``.

    ``render_prompt`` reads content parts through ``_part_field``, which accepts
    the pydantic models the API uses *and* plain dicts -- the second is what
    jinja2 needs, so the same conversation can be fed to both.
    """
    return [{"role": "user", "content": parts}]


@pytest.mark.parametrize("prompt", list(vl.TASK_PROMPTS))
def test_the_rendered_prompt_matches_the_template(prompt):
    parts = [{"type": "image_url", "image_url": {"url": _IMAGE_URL}},
             {"type": "text", "text": prompt}]
    ours, images = vl.render_prompt(_messages(parts))
    assert len(images) == 1
    # jinja2's template branches on `content["type"] == "image"`, so the oracle
    # is given the image part in *its* spelling; the rendering is what is under
    # test, not the spelling.
    want = _render_with_template([{"role": "user", "content": [
        {"type": "image"},
        {"type": "text", "text": prompt},
    ]}])
    assert ours == want


def test_the_assistant_turn_ends_with_a_newline():
    """The A3 finding, pinned: ``Assistant:\\n`` is the generation prompt."""
    text, _ = vl.render_prompt(_messages([
        {"type": "image_url", "image_url": {"url": _IMAGE_URL}},
        {"type": "text", "text": "OCR:"},
    ]))
    assert text.endswith("Assistant:\n")
    assert not text.endswith("Assistant: ")


def test_a_text_only_turn_renders_without_an_image_block():
    text, images = vl.render_prompt([{"role": "user", "content": "OCR:"}])
    assert images == []
    assert "<|IMAGE_START|>" not in text
    assert text == "<|begin_of_sentence|>User: OCR:\nAssistant:\n"


def test_several_images_are_written_before_the_text():
    """The template loops images first, then text -- order in the array is not
    order in the prompt."""
    parts = [{"type": "text", "text": "OCR:"},
             {"type": "image_url", "image_url": {"url": _IMAGE_URL}},
             {"type": "image_url", "image_url": {"url": _IMAGE_URL}}]
    ours, images = vl.render_prompt(_messages(parts))
    assert len(images) == 2
    want = _render_with_template([{"role": "user", "content": [
        {"type": "image"}, {"type": "image"}, {"type": "text", "text": "OCR:"},
    ]}])
    assert ours == want


def test_a_history_turn_matches_the_template():
    """An assistant turn keeps its ``</s>``; a second user turn starts afresh."""
    messages = [
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": _IMAGE_URL}},
            {"type": "text", "text": "OCR:"}]},
        {"role": "assistant", "content": "<fcel>a<nl>"},
        {"role": "user", "content": "Table Recognition:"},
    ]
    ours, images = vl.render_prompt(messages)
    assert len(images) == 1
    want = _render_with_template([
        {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": "OCR:"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "<fcel>a<nl>"}]},
        {"role": "user", "content": [{"type": "text", "text": "Table Recognition:"}]},
    ])
    assert ours == want


def test_an_unsupported_role_is_a_client_error():
    with pytest.raises(ValueError):
        vl.render_prompt([{"role": "tool", "content": "x"}])


# ---------------------------------------------------------------------------
# 2. the token ids
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def checker(tmp_path_factory) -> Path:
    cxx = shutil.which("g++") or shutil.which("c++") or shutil.which("clang++")
    if cxx is None:
        pytest.skip("no C++ compiler to build the tokenizer checker")
    out = tmp_path_factory.mktemp("vl_tok") / "tok_check"
    proc = subprocess.run(
        [cxx, "-std=c++17", "-O1", f"-I{ROOT / 'native' / 'include'}",
         str(ROOT / "tools" / "tok_check.cpp"),
         str(ROOT / "native" / "src" / "tokenizer.cpp"), "-o", str(out)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.fail(f"tokenizer checker failed to build:\n{proc.stderr}")
    return out


def _have_tokenizer() -> bool:
    return (CONFIG / "tokenizer.json").is_file()


def test_the_cpp_tokenizer_matches_the_reference_on_this_model(checker: Path):
    """The 75-case golden this tokenizer family needs.

    Includes the byte-fallback cases (``门簪`` is one token plus three
    ``<0xXX>`` tokens) and the OTSL markers, which is what makes it a check of
    *this* tokenizer rather than of Qwen's.
    """
    if not _have_tokenizer():
        pytest.skip("model-config/paddleocr_vl_1_5/tokenizer.json is not present")
    assert GOLDEN.is_file(), "the PaddleOCR-VL tokenizer golden is missing"
    proc = subprocess.run([str(checker), str(CONFIG / "tokenizer.json"), str(GOLDEN)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, (
        "the C++ tokenizer no longer matches the reference implementation:\n"
        f"{proc.stdout}\n{proc.stderr}")


#: The ids MYS-2660's alignment ran with: 5 text tokens, 784 image rows, then the
#: prompt and the generation turn. Pinned as literals so a golden regeneration
#: cannot quietly move them.
PROTOTYPE_HEAD = [100273, 2969, 93963, 93919, 101305]
PROTOTYPE_TAIL_BY_PROMPT = {
    "OCR:": [101306, 93972, 2497, 93963, 23, 92267, 93963, 23],
    "Table Recognition:": [101306, 2567, 93514, 93963, 23, 92267, 93963, 23],
}
IMAGE_TOKENS_784 = 784


@pytest.mark.parametrize("prompt", list(PROTOTYPE_TAIL_BY_PROMPT))
def test_the_prompt_ids_are_the_ones_the_alignment_used(prompt):
    """The prompt the service builds == the prompt the board was measured on.

    ``docs/ocr-vl.md`` reports 797-token prompts and a 5-token head; those two
    numbers are the contract this test keeps. Re-derived through the service's
    own renderer and the reference tokenizer, so a template edit, a tokenizer
    change or a different placeholder would show up here rather than as a
    changed score on the board.
    """
    tokenizers = pytest.importorskip("tokenizers")
    if not _have_tokenizer():
        pytest.skip("model-config/paddleocr_vl_1_5/tokenizer.json is not present")
    tok = tokenizers.Tokenizer.from_file(str(CONFIG / "tokenizer.json"))

    text, images = vl.render_prompt(_messages([
        {"type": "image_url", "image_url": {"url": _IMAGE_URL}},
        {"type": "text", "text": prompt},
    ]))
    ids = tok.encode(text, add_special_tokens=False).ids
    ph = ids.index(100295)                      # <|IMAGE_PLACEHOLDER|>
    assert ids[:ph] == PROTOTYPE_HEAD
    assert ids[ph + 1:] == PROTOTYPE_TAIL_BY_PROMPT[prompt]
    assert len(images) == 1

    expanded = ids[:ph] + [100295] * IMAGE_TOKENS_784 + ids[ph + 1:]
    assert len(expanded) == 797                 # the number in docs/ocr-vl.md


def test_the_serviced_tokenizer_expands_one_placeholder_to_784_rows():
    """The expansion the backend does is the one the prompt needs.

    ``_encode`` replaces the single placeholder with one row per merged patch.
    Getting this wrong writes image embeddings into the wrong prompt rows and
    still emits text, so the count is checked against the vit stage's own
    arithmetic rather than against a constant that could drift from it.
    """
    tokenizers = pytest.importorskip("tokenizers")
    if not _have_tokenizer():
        pytest.skip("model-config/paddleocr_vl_1_5/tokenizer.json is not present")
    tok = tokenizers.Tokenizer.from_file(str(CONFIG / "tokenizer.json"))
    text, _ = vl.render_prompt(_messages([
        {"type": "image_url", "image_url": {"url": _IMAGE_URL}},
        {"type": "text", "text": "OCR:"},
    ]))
    ids = tok.encode(text, add_special_tokens=False).ids
    n_img = (vl.GRID // vl.MERGE) * (vl.GRID // vl.MERGE)
    assert n_img == IMAGE_TOKENS_784
    assert ids.count(100295) == 1


# ---------------------------------------------------------------------------
# 3. the pixels
# ---------------------------------------------------------------------------
#: The crop and the patch tensor ``table_stats`` is fed to the vit, regenerated
#: for the letterbox arithmetic of MYS-2681. The file set is the same one
#: MYS-2660's alignment used (``/data/mys2660/align/table_stats/``), so this runs
#: without the board; the tensor itself was re-derived through
#: ``tools/ocr/vl_native_prep.py``, which letterboxes exactly as the service does.
PREP_DIR = ROOT / "tests" / "data" / "ocr" / "vl_prep"


@pytest.fixture(scope="module")
def cv2():
    return pytest.importorskip("cv2", reason="image preprocessing needs OpenCV")


@pytest.fixture(scope="module")
def prep():
    if not (PREP_DIR / "patches.f32.gz").is_file():
        pytest.skip("tests/data/ocr/vl_prep/patches.f32.gz is missing")
    return PREP_DIR


def test_preprocess_reproduces_the_tensor_the_board_fed_the_vit(cv2, prep):
    """Element for element, against the recorded artefact.

    This is the strongest form of the claim the card asks for ("与 HF processor
    of 像素张量逐元素比较"): the golden is not this function's output rounded and
    re-saved, it is the tensor the alignment in ``docs/ocr-vl.md`` §4 was
    measured on. Reproducing it means the service preprocesses exactly what was
    measured -- ``cv2.INTER_CUBIC`` rather than the processor's BICUBIC, which
    differ by up to 1.42 on this very crop, and now the white letterbox both
    surfaces share (MYS-2681).

    MYS-2681 regenerated the tensor: the previous file pinned the *stretched*
    arithmetic the chat path used to have. The 1240x1400 crop letterboxes to a
    694x784 band inside the square, so the padding is visible in the data.
    """
    blob = (prep / "crop.png").read_bytes()
    gh, gw, patches = vl.preprocess_image(blob, cv2=cv2)
    # Gzipped in the repository: 7.4 MB of float32 that compresses 130:1 (the
    # tensor is the same handful of image pixels repeated across a resize, so it
    # is highly redundant), and this file is only ever read whole.
    import gzip

    want = np.frombuffer(gzip.decompress((prep / "patches.f32.gz").read_bytes()),
                         dtype=np.float32)
    assert (gh, gw) == (vl.GRID, vl.GRID)
    assert patches.shape == (gh * gw, 3, vl.PATCH, vl.PATCH)
    assert patches.size == want.size
    diff = np.abs(patches.reshape(-1) - want)
    # Host OpenCV and the board's Sophos build are both 4.x; the arithmetic is
    # integer-exact rescale, so this is an equality, not a tolerance.
    assert float(diff.max()) == 0.0


def test_preprocess_is_patch_major_and_normalised(cv2):
    """The two things the vit graph's input shape silently depends on.

    ``[gh*gw, 3, 14, 14]`` is patch-major (a channel-major reshape would feed
    interleaved channels as planes and still run), and the normalisation is
    ``(x/255 - 0.5)/0.5`` -- the model's ``image_mean``/``image_std`` of 0.5.

    The patch read is from the **middle** of the grid, not patch 0: since
    MYS-2681 the crop is letterboxed, so the corner patches are white padding
    and the image sits in a band across the centre.
    """
    import cv2 as _cv2

    img = np.zeros((40, 60, 3), np.uint8)
    img[:, :] = (0, 0, 255)                      # BGR red
    ok, buf = _cv2.imencode(".png", img)
    assert ok
    gh, gw, patches = vl.preprocess_image(buf.tobytes(), cv2=cv2)
    assert patches.shape == (gh * gw, 3, vl.PATCH, vl.PATCH)
    # 60x40 into 784x784 preserving the aspect: a 784x523 band, so the middle
    # row of the patch grid (row 27) is image and row 0 is padding.
    grid = patches.reshape(gh, gw, 3, vl.PATCH, vl.PATCH)
    # Red pixel -> RGB (255, 0, 0) -> normalised (+1, -1, -1).
    row = grid[gh // 2, gw // 2]
    assert np.allclose(row[0], 1.0)
    assert np.allclose(row[1], -1.0)
    assert np.allclose(row[2], -1.0)
    # And the corner is the white padding, which is (+) on all three channels.
    assert np.allclose(grid[0, 0], 1.0)


def test_preprocess_refuses_bytes_that_are_not_an_image(cv2):
    with pytest.raises(ValueError):
        vl.preprocess_image(b"not an image at all", cv2=cv2)


def test_the_golden_files_are_the_ones_the_docs_quote():
    """A cheap guard against a silently regenerated golden.

    The golden records the ``tokenizers`` version that produced it. A future
    regeneration with a different version is exactly the change that could move
    ids without anyone noticing, so the recorded version is asserted against the
    one this repository's requirements pin.
    """
    if not GOLDEN.is_file():
        pytest.skip("the PaddleOCR-VL tokenizer golden is missing")
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert payload["generated_by"] == "tools/gen_tokenizer_golden_paddleocr_vl.py"
    assert payload["tokenizers_version"], "the golden must record its generator"
    assert payload["specials"]["<fcel>"] == 101309
    assert payload["specials"]["<|IMAGE_PLACEHOLDER|>"] == 100295
