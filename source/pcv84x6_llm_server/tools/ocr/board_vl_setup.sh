#!/bin/bash
# Board acceptance for /v1/ocr mode=vl (MYS-2664 §3).
#
# Runs a *side* instance (the installed 0.6.28 service on :8000 is untouched):
# /data/mys2664/side is a copy of the MYS-2663 side install plus this working
# tree's app/, so the code under test is exactly what is in git.
#
#   bash tools/ocr/board_vl_setup.sh          # one-time: copy + start
#   bash tools/ocr/board_vl_setup.sh stop     # tear the side instance down
set -u
BOARD=/home/zzt/workspace/cv84x2/mys2660/b157.sh
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o ServerAliveInterval=10 -p 10157 linaro@172.26.166.96"
: "${SSHPASS:?export SSHPASS (the .157 linaro password) before running}"; export SSHPASS
SIDE=/data/mys2664/side
PORT=8010

if [ "${1:-start}" = "stop" ]; then
  $BOARD "pkill -f 'port $PORT' || true; sleep 1; ss -ltn | grep -c :$PORT || true"
  exit 0
fi

echo "== copying the side install (app/lib/vendor/model-config/web)"
$BOARD "sudo mkdir -p /data/mys2664 && sudo cp -a /data/mys2663/side $SIDE && sudo chown -R linaro:linaro /data/mys2664" 2>&1 | tail -3

echo "== pushing this working tree's app/"
cd /home/zzt/workspace/cv84x2/cv84x6-llm-server || exit 1
rsync -az --delete --exclude=__pycache__ -e "$SSH" app linaro@172.26.166.96:$SIDE/ 2>&1 | tail -2

echo "== placing the VL bmodel where the manager will find it"
$BOARD "mkdir -p $SIDE/models/paddleocr-vl-1.5 && cp -n /data/qa3/paddleocr-vl-1.5_bf16_seq2048_bm1684x2_4core_static_20261103.bmodel $SIDE/models/paddleocr-vl-1.5/ && ls -la $SIDE/models/paddleocr-vl-1.5" 2>&1 | tail -3

echo "== starting the side instance on :$PORT"
$BOARD "cd $SIDE && pkill -f 'port $PORT' 2>/dev/null; sleep 1; \
  PYTHONPATH=/opt/sophon/sophon-opencv_2.3.0/opencv-python:$SIDE/vendor:$SIDE \
  CV84X6_LLM_LIB=$SIDE/lib/libcv84x6_llm.so \
  LD_LIBRARY_PATH=/opt/sophon/libsophon-current/lib \
  nohup python3 -m app.main --host 0.0.0.0 --port $PORT --backend native \
    --data-root $SIDE/data --install-dir $SIDE > $SIDE/server.log 2>&1 &
  sleep 8; tail -5 $SIDE/server.log; curl -s -m 5 http://127.0.0.1:$PORT/healthz" 2>&1 | tail -10
