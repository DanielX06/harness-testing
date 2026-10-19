#!/bin/bash
# Usage: ./run_batch.sh <model 1-3> <effort 1-5> [reps, default 10] [parallel, default 2] [noisy|clean, default noisy]
# Baseline calibration: the same harness run <reps> times, <parallel> at a time, each scored on the
# selection grid. Results in runs/batch_<time>_m<model>e<effort>_<noisy|clean>[_<harness>]/, with
# batch.json (the settings) and summary.md from summarize.py.
# noisy: grid A data with PMU-grade noise, and the prompt says the channels carry it.
# clean: the noise-free copy (test_cases/make_clean_sandbox.py), and the prompt says the channels are noise-free.
# Two optional environment variables, as paths relative to where you run the command:
#   HARNESS  harness folder (system.md, method.md, tools/), default harness_v0/harness; any other
#            folder adds its name to the batch folder's name
#   CONFIG   scorer config, default scorer/config_min.json; scorer/config_rsi.json also scores
#            every run on the hidden monitor grid M (use it for anything the RSI loop compares to)
#   bash run_batch.sh 1 1 10 2 clean
#   CONFIG=../scorer/config_rsi.json bash run_batch.sh 1 1 40 4 clean
#   HARNESS=path/to/h003 CONFIG=../scorer/config_rsi.json bash run_batch.sh 1 1 20 4 clean
# Keep <parallel> the same for every batch you compare: machine load changes how often tool calls
# hit the 120 s limit, and summary.md reports that rate.
set -u
MODEL=$1; EFFORT=$2; REPS=${3:-10}; PAR=${4:-2}; NOISE=${5:-noisy}
case "$NOISE" in
    noisy|clean) ;;
    *) echo "5th argument must be noisy or clean, got '$NOISE'" >&2; exit 1 ;;
esac
HERE="$(cd "$(dirname "$0")" && pwd)"
# resolve HARNESS and CONFIG against the caller's directory before moving into harness_v0
if [ -n "${HARNESS:-}" ]; then
    [ -d "$HARNESS" ] || { echo "HARNESS folder not found: $HARNESS" >&2; exit 1; }
    HARNESS="$(cd "$HARNESS" && pwd)"
else
    HARNESS="$HERE/harness"
fi
if [ -n "${CONFIG:-}" ]; then
    [ -f "$CONFIG" ] || { echo "CONFIG file not found: $CONFIG" >&2; exit 1; }
    CONFIG="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"
else
    CONFIG="$(cd "$HERE/../scorer" && pwd)/config_min.json"
fi
cd "$HERE"
SUFFIX=""
[ "$HARNESS" != "$HERE/harness" ] && SUFFIX="_$(basename "$HARNESS")"
BASE="runs/batch_$(date +%Y%m%d_%H%M%S)_m${MODEL}e${EFFORT}_${NOISE}${SUFFIX}"
mkdir -p runs
OUT="$BASE"; n=2
until mkdir "$OUT" 2>/dev/null; do OUT="${BASE}_$n"; n=$((n + 1)); done   # two batches in the same second
PY=../../.venv/bin/python
[ -x "$PY" ] || PY=python3
printf '{"model": %s, "effort": %s, "reps": %s, "parallel": %s, "noise": "%s",\n "harness": "%s",\n "config": "%s",\n "git": "%s", "started": "%s"}\n' \
    "$MODEL" "$EFFORT" "$REPS" "$PAR" "$NOISE" "$HARNESS" "$CONFIG" \
    "$(git describe --always --dirty 2>/dev/null || echo unknown)" "$(date +%Y-%m-%dT%H:%M:%S%z)" > "$OUT/batch.json"
export PY MODEL EFFORT OUT NOISE HARNESS CONFIG
seq "$REPS" | xargs -P "$PAR" -I{} sh -c '"$PY" run_harness.py "$MODEL" "$EFFORT" --noise "$NOISE" --harness "$HARNESS" --config "$CONFIG" --out "$OUT" --workers 2 > "$OUT/rep{}.log" 2>&1; echo "rep {} done"'
"$PY" summarize.py "$OUT"
