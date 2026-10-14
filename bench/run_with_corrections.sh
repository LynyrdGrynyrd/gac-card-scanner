#!/bin/bash
# Re-run the benchmark including reviewer corrections captured by the app (bench/corrections/gt.json + photos).
# Usage: bench/run_with_corrections.sh        (corrections only, then the full suite)
cd "$(dirname "$0")/.." || exit 1
P=.venv/bin/python
if [ -s bench/corrections/gt.json ]; then
  $P bench/eval_bench.py bench/corrections/gt.json bench/corrections --show > /tmp/ev_corr.txt
  echo "reviewer corrections ($($P -c 'import json;print(len(json.load(open("bench/corrections/gt.json"))))') cards): $(grep OVERALL /tmp/ev_corr.txt)"; grep Calibration /tmp/ev_corr.txt
else echo "no reviewer corrections captured yet (bench/corrections/gt.json)"; fi
bash bench/run_all.sh
