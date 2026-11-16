#!/usr/bin/env bash
# Time a knowledge-base build on whichever embedding bmodel is installed.
#
#   board_kb_time.sh <label>
#
# Creates a fresh library, uploads DOCS files, and stops the clock when every
# document reaches `ready`. That end-to-end figure is the one an operator sees:
# it includes the queue, the parser, the chunker and the HTTP round trips, not
# just the forward pass. Doing it per model is what makes the seq8192 ->
# seq2048 comparison a measurement rather than an extrapolation from
# milliseconds-per-text.
set -uo pipefail
BASE=http://127.0.0.1:8099
COOKIE=/tmp/ck_time
DOCS=${DOCS:-3}
LABEL=${1:-unnamed}

rm -f $COOKIE
curl -s -c $COOKIE -X POST "$BASE/api/login" -H 'Content-Type: application/json' \
  -d '{"password":"admin"}' > /dev/null

python3 - "$DOCS" <<'PY'
import sys
para = ("库房管理制度第{n}条：物料入库应当核对品名、规格、数量与送货单是否一致，"
        "发现短缺或破损应当在当日填写异常单并通知采购与质检；"
        "上架时按库位号顺序摆放，标识朝外，同类物料不得混放；"
        "每月末盘点一次，盘点结果由两人签字确认后归档保存三年；"
        "出库遵循先进先出，单据保留备查。")
for i in range(int(sys.argv[1])):
    open(f"/tmp/kbtime{i}.txt", "w").write(
        "\n".join(para.format(n=i * 60 + j) for j in range(60)))
PY

kb=$(curl -s -b $COOKIE -X POST "$BASE/api/apps/kb" -H 'Content-Type: application/json' \
     -d "{\"name\":\"计时 $LABEL\"}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["kb"]["id"])')

start=$(date +%s.%N)
for i in $(seq 0 $((DOCS - 1))); do
  curl -s -b $COOKIE -X POST "$BASE/api/apps/kb/$kb/docs" \
    -F "file=@/tmp/kbtime$i.txt" -o /dev/null
done

for _ in $(seq 1 900); do
  s=$(curl -s -b $COOKIE "$BASE/api/apps/kb/$kb/docs" | python3 -c "
import json,sys
d=json.load(sys.stdin)['docs']
busy=[x for x in d if x['status'] in ('queued','parsing','embedding')]
print(len(d), len(busy), sum(x['chunks'] for x in d))
" 2>/dev/null)
  set -- $s
  if [ "${2:-1}" = "0" ] && [ "${1:-0}" = "$DOCS" ]; then
    end=$(date +%s.%N)
    python3 -c "
import sys
docs, chunks, secs = int('$1'), int('$3'), $end-$start
print(f'$LABEL: {docs} docs, {chunks} chunks, {secs:.1f} s '
      f'({secs/max(chunks,1)*1000:.0f} ms/chunk)')"
    break
  fi
  sleep 2
done
