#!/bin/bash
# Run all benchmarks; prints per-field summaries. Usage: bench/run_all.sh [label]
cd "$(dirname "$0")/.."
P=.venv/bin/python
$P tests/eval.py > /tmp/ev_basic.txt; echo "basic synthetic: $(grep OVERALL /tmp/ev_basic.txt)"
$P bench/eval_bench.py tests/synth2_gt.json tests/synth2 --show > /tmp/ev_synth2.txt; echo "synth2: $(grep OVERALL /tmp/ev_synth2.txt)"
$P bench/eval_bench.py bench/real_gt.json bench/real --show > /tmp/ev_real.txt; echo "real: $(grep OVERALL /tmp/ev_real.txt)"; grep Calibration /tmp/ev_synth2.txt /tmp/ev_real.txt
if [ -s bench/corrections/gt.json ]; then $P bench/eval_bench.py bench/corrections/gt.json bench/corrections --show > /tmp/ev_corr.txt; echo "corrections: $(grep OVERALL /tmp/ev_corr.txt)"; grep Calibration /tmp/ev_corr.txt; fi
