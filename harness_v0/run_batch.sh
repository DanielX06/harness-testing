#!/bin/bash
# Usage: ./run_batch.sh <model 1-3> <effort 1-5> [reps, default 10] [parallel, default 2] [noisy|clean, default noisy]
# Baseline calibration: the same harness run <reps> times, <parallel> at a time, each scored on the
# selection grid. Results in runs/batch_<time>_m<model>e<effort>_<noisy|clean>/, summarized by summarize.py.
# noisy: grid A data with PMU-grade noise, and the prompt says the channels carry it.
# clean: the noise-free copy (test_cases/make_clean_sandbox.py), and the prompt says the channels are noise-free.
#   bash run_batch.sh 1 1 10 2 clean
set -u
MODEL=$1; EFFORT=$2; REPS=${3:-10}; PAR=${4:-2}; NOISE=${5:-noisy}
case "$NOISE" in
    noisy|clean) ;;
    *) echo "5th argument must be noisy or clean, got '$NOISE'" >&2; exit 1 ;;
esac
cd "$(dirname "$0")"
OUT="runs/batch_$(date +%Y%m%d_%H%M%S)_m${MODEL}e${EFFORT}_${NOISE}"
mkdir -p "$OUT"
PY=../../.venv/bin/python
[ -x "$PY" ] || PY=python3
export PY MODEL EFFORT OUT NOISE
seq "$REPS" | xargs -P "$PAR" -I{} sh -c '"$PY" run_harness.py "$MODEL" "$EFFORT" --noise "$NOISE" --out "$OUT" --workers 2 > "$OUT/rep{}.log" 2>&1; echo "rep {} done"'
"$PY" summarize.py "$OUT"
