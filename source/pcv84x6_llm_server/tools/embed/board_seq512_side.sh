#!/bin/bash
# MYS-2706 side instance on `.157`: two embedding builds, one service.
#
# Deliberately NOT the installed service (which runs 0.6.28 out of
# /opt/sophgo and holds rerank+asr+ocr+seq8192). This one runs the branch's
# `app/` out of /data/mys2706, its own data root and its own model tree, so the
# board is left exactly as found: kill this and it is gone.
#
# Two things the notes say are easy to get wrong:
#   * CV84X6_LLM_LIB must be set explicitly, or the worker inherits systemd's
#     (older) copy even though --native-lib was passed;
#   * CV84X6_MODEL_CONFIG_ROOT must point at a tree that has every kind's
#     config, or a model without its own config/ falls back to the wrong one.
cd /data/mys2706
export PYTHONPATH=/opt/sophgo/cv84x6_llm_server/vendor
export CV84X6_LLM_LIB=/opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so
export CV84X6_MODEL_CONFIG_ROOT=/opt/sophgo/cv84x6_llm_server/model-config
export CV84X6_DEFAULT_CONFIG=/opt/sophgo/cv84x6_llm_server/model-config/qwen3_embedding
export LD_LIBRARY_PATH=/opt/sophon/libsophon-current/lib
exec python3 -u -m app.main --host 127.0.0.1 --port 8031 --backend native \
  --data-root /data/mys2706/side/data --models-dir /data/mys2706/side/models \
  --install-dir /opt/sophgo/cv84x6_llm_server \
  > /data/mys2706/side/logs/server.log 2>&1
