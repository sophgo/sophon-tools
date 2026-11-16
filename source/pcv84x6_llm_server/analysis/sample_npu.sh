#!/bin/bash
# Sample /sys/class/bm-tpu/bm-tpu0/device/npu_usage while another process decodes.
# usage:N is a per-sample TPU utilisation percentage; the weight is the mean of
# the samples, which is what "is the TPU the bottleneck" actually asks.
out=${1:-/tmp/npu_samples.txt}
: > "$out"
for i in $(seq 1 "$2"); do
  v=$(sed -n 's/^usage:\([0-9]*\).*/\1/p' /sys/class/bm-tpu/bm-tpu0/device/npu_usage 2>/dev/null)
  echo "${v:-none}" >> "$out"
  sleep 0.1
done
