#!/usr/bin/env python3
"""Make the build container able to compile bge-reranker-v2-m3.

tpu-mlir 1.30.2-38 ships no ``XLMRobertaConverter`` and no ``XLM_ROBERTA_INFO``
weight map, so ``llm_convert.py -m bge-reranker-v2-m3`` fails at dispatch
("Unsupported model type: xlm-roberta") before it reads a single weight. Both
pieces exist upstream in tpu-mlir master; this script fetches them and patches
the installed copy, which is the VM's own build image rather than this repo.

Idempotent, and backs up each file it touches to ``<name>.bak-mys2702`` once, so
``--revert`` puts the image back the way the other models' builds expect.

    python3 setup_xlm_roberta.py            # install
    python3 setup_xlm_roberta.py --revert   # restore the originals
"""
import argparse
import os
import re
import shutil
import sys
import urllib.request

LLM_DIR = "/usr/local/lib/python3.10/dist-packages/tpu_mlir/python/llm"
RAW = "https://raw.githubusercontent.com/sophgo/tpu-mlir/master/python/llm/"
BACKUP_SUFFIX = ".bak-mys2702"

#: Appended to LlmInfo.py when absent. Byte-identical to the block upstream
#: carries (python/llm/LlmInfo.py, "XLM-RoBERTa (encoder-only reranker...").
INFO_BLOCK = '''

# XLM-RoBERTa (encoder-only reranker, e.g. bge-reranker-v2-m3)
# No NORM/LMHEAD at model level (LayerNorms are per-layer, classifier is custom).
XLM_ROBERTA_INFO = ModelInfo(ModelConfig(),
                             weights={
                                 LlmList.LAYERS: "roberta.encoder.layer",
                                 LlmList.EMBEDING: "roberta.embeddings.word_embeddings",
                                 LlmList.NORM: "",
                                 LlmList.LMHEAD: "",
                                 LlmList.INPUT_LN: "",
                                 LlmList.Q_PROJ: "attention.self.query",
                                 LlmList.K_PROJ: "attention.self.key",
                                 LlmList.V_PROJ: "attention.self.value",
                                 LlmList.O_PROJ: "attention.output.dense",
                                 LlmList.POST_ATTN_LN: "attention.output.LayerNorm",
                                 LlmList.MLP_GATE: "",
                                 LlmList.MLP_UP: "intermediate.dense",
                                 LlmList.MLP_DOWN: "output.dense",
                             })
'''


def backup(path: str) -> None:
    bak = path + BACKUP_SUFFIX
    if not os.path.exists(bak):
        shutil.copy2(path, bak)


def install() -> int:
    info_path = os.path.join(LLM_DIR, "LlmInfo.py")
    conv_path = os.path.join(LLM_DIR, "XLMRobertaConverter.py")

    backup(info_path)
    if not os.path.exists(conv_path):
        data = urllib.request.urlopen(RAW + "XLMRobertaConverter.py", timeout=30).read()
        with open(conv_path, "wb") as f:
            f.write(data)
        print("wrote", conv_path, len(data), "bytes")
    else:
        print("kept", conv_path)

    with open(info_path, encoding="utf-8") as f:
        source = f.read()
    if "XLM_ROBERTA_INFO" not in source:
        with open(info_path, "a", encoding="utf-8") as f:
            f.write(INFO_BLOCK)
        print("appended XLM_ROBERTA_INFO to", info_path)
    else:
        print("XLM_ROBERTA_INFO already present in", info_path)

    # llm_convert.py dispatches on config.json's model_type; tpu-mlir's table has
    # no entry for "xlm-roberta", so register one rather than editing the caller.
    conv_convert = os.path.join(LLM_DIR, "..", "tools", "llm_convert.py")
    conv_convert = os.path.normpath(conv_convert)
    backup(conv_convert)
    with open(conv_convert, encoding="utf-8") as f:
        src = f.read()
    if "XLMRobertaConverter" in src:
        print("dispatch already present in", conv_convert)
    else:
        anchor = '    (("chatglm", ), "llm.Chatglm3Converter", "Chatglm3Converter", {}),'
        if anchor not in src:
            print("ERROR: dispatch table anchor not found", file=sys.stderr)
            return 1
        src = src.replace(
            anchor,
            '    (("xlm-roberta", "xlm_roberta"), "llm.XLMRobertaConverter",\n'
            '     "XLMRobertaConverter", {}),\n' + anchor,
            1)
        with open(conv_convert, "w", encoding="utf-8") as f:
            f.write(src)
        print("registered xlm-roberta in", conv_convert)
    return 0


def revert() -> int:
    for name in ("LlmInfo.py", "XLMRobertaConverter.py"):
        path = os.path.join(LLM_DIR, name)
        bak = path + BACKUP_SUFFIX
        if os.path.exists(bak):
            shutil.move(bak, path)
            print("restored", path)
        elif name == "XLMRobertaConverter.py" and os.path.exists(path):
            os.remove(path)
            print("removed", path)
    conv = os.path.normpath(os.path.join(LLM_DIR, "..", "tools", "llm_convert.py"))
    if os.path.exists(conv + BACKUP_SUFFIX):
        shutil.move(conv + BACKUP_SUFFIX, conv)
        print("restored", conv)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()
    return revert() if args.revert else install()


if __name__ == "__main__":
    sys.exit(main())
