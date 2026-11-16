#!/bin/bash
# Which consumer reads stale data? One d2d copy site is synced per arm, nothing
# else changes. Each trial is a separate process; trace is unset.
#
# Arms: none, embed, vit, block, wemm, all
#   embed = embed-graph output -> engine hidden
#   vit   = ViT output -> engine hidden (image path)
#   block = engine hidden -> next block's input  (the long chain)
#   wemm  = block output -> engine hidden
set -u
ROOT="${1:-/data/mys2913-clean}"
export PYTHONPATH=/opt/sophgo/cv84x6_llm_server/vendor
MODEL=/data/cv84x6_llm_server/models/wemm-embedding-2b/wemm-embedding-2b_w8bf16_seq2048_pixels1310720_cv84x6_4core_buckets_gdnmixed_20261114_091623.bmodel
CFG=/opt/sophgo/cv84x6_llm_server/model-config/wemm_embedding
DIAG="$ROOT/build/libcv84x6_vl_diag.so"
PKG="$ROOT/st/source/pcv84x6_llm_server"
CALLS="${CALLS:-6}"
TRIALS="${TRIALS:-2}"
mkdir -p "$ROOT/sites"

for site in none embed vit block wemm all; do
  files=()
  for t in $(seq 0 $((TRIALS - 1))); do
    out="$ROOT/sites/site-$site-t$t.json"
    if [ "$site" = none ]; then
      env -u CV_VLE_TRACE CV_VLE_COPY_SYNC=0 CV_VLE_COPY_DELAY_US=0 \
          CV_VLE_LAUNCH_SYNC=0 CV_VLE_MEMSET_SYNC=0 \
          python3 "$PKG/tools/vl_embed/repeat_compare.py" \
          --library "$DIAG" --model "$MODEL" --config "$CFG" \
          --calls "$CALLS" --trials 1 --long-text-repeats 20 --output "$out" \
          >/dev/null 2>&1
    else
      env -u CV_VLE_TRACE CV_VLE_COPY_SYNC=1 CV_VLE_COPY_SYNC_SITE="$site" \
          CV_VLE_COPY_DELAY_US=0 CV_VLE_LAUNCH_SYNC=0 CV_VLE_MEMSET_SYNC=0 \
          python3 "$PKG/tools/vl_embed/repeat_compare.py" \
          --library "$DIAG" --model "$MODEL" --config "$CFG" \
          --calls "$CALLS" --trials 1 --long-text-repeats 20 --output "$out" \
          >/dev/null 2>&1
    fi
    files+=("$out")
  done
  python3 "$(dirname "$0")/aggregate.py" "site=$site" "$ROOT/sites/agg-$site.json" "${files[@]}"
done
