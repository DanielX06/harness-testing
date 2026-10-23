#!/bin/bash
# Usage: bash solver/run_solver_batch.sh <model> <effort> [runs, default 10] [parallel, default 2] [noisy|clean, default noisy]
#   model: 1-3 or haiku, sonnet, opus.  effort: 1-5 or low ... max.
# The same harness run <runs> times, <parallel> at a time, each scored with the scorer config. Results go in
# runs/batch_<time>_<model>_<effort>_<noisy|clean>[_<harness>]/ with batch.json (the settings) and summary.md.
# noisy: grid A data with PMU-grade noise, and the prompt says the channels carry it.
# clean: the noise-free copy (test_cases/make_noise_free_sandbox.py), and the prompt says the channels are noise-free.
# Two optional environment variables, as paths relative to where you run the command:
#   HARNESS  harness folder (system.md, method.md, tools/), default harness_v0/harness; any other folder adds
#            its name to the batch folder's name
#   CONFIG   scorer config, default scorer/config_min.json; scorer/config_rsi.json also scores every run on the
#            hidden monitor grid M (use it for anything the RSI loop is compared with)
#   bash solver/run_solver_batch.sh haiku low 10 2 clean
#   CONFIG=scorer/config_rsi.json bash solver/run_solver_batch.sh haiku low 40 4 clean
#   HARNESS=rsi/experiments/long1/candidates/h003/harness CONFIG=scorer/config_rsi.json bash solver/run_solver_batch.sh haiku low 20 4 clean
# Keep <parallel> the same for every batch you compare: machine load changes how often tool calls hit the
# 120 s limit, and summary.md reports that rate. A run that crashes can be finished with
#   python solver/solver_run.py --resume <run folder>
set -u
MODEL=$1; EFFORT=$2; RUNS=${3:-10}; PARALLEL=${4:-2}; NOISE=${5:-noisy}
case "$NOISE" in
    noisy|clean) ;;
    *) echo "5th argument must be noisy or clean, got '$NOISE'" >&2; exit 1 ;;
esac
HERE="$(cd "$(dirname "$0")" && pwd)"
REPOSITORY="$(cd "$HERE/.." && pwd)"
# resolve HARNESS and CONFIG against the caller's folder before anything changes folder
if [ -n "${HARNESS:-}" ]; then
    [ -d "$HARNESS" ] || { echo "HARNESS folder not found: $HARNESS" >&2; exit 1; }
    HARNESS="$(cd "$HARNESS" && pwd)"
else
    HARNESS="$REPOSITORY/harness_v0/harness"
fi
if [ -n "${CONFIG:-}" ]; then
    [ -f "$CONFIG" ] || { echo "CONFIG file not found: $CONFIG" >&2; exit 1; }
    CONFIG="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"
else
    CONFIG="$REPOSITORY/scorer/config_min.json"
fi
SUFFIX=""
[ "$HARNESS" != "$REPOSITORY/harness_v0/harness" ] && SUFFIX="_$(basename "$HARNESS")"
BASE="$REPOSITORY/runs/batch_$(date +%Y%m%d_%H%M%S)_${MODEL}_${EFFORT}_${NOISE}${SUFFIX}"
mkdir -p "$REPOSITORY/runs"
OUT="$BASE"; n=2
until mkdir "$OUT" 2>/dev/null; do OUT="${BASE}_$n"; n=$((n + 1)); done   # two batches in the same second
PYTHON="$REPOSITORY/../.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3
printf '{"model": "%s", "effort": "%s", "runs": %s, "parallel": %s, "noise": "%s",\n "harness": "%s",\n "config": "%s",\n "git": "%s", "started": "%s"}\n' \
    "$MODEL" "$EFFORT" "$RUNS" "$PARALLEL" "$NOISE" "$HARNESS" "$CONFIG" \
    "$(cd "$REPOSITORY" && GIT_OPTIONAL_LOCKS=0 git describe --always --dirty 2>/dev/null || echo unknown)" \
    "$(date +%Y-%m-%dT%H:%M:%S%z)" > "$OUT/batch.json"
export PYTHON MODEL EFFORT OUT NOISE HARNESS CONFIG REPOSITORY
seq "$RUNS" | xargs -P "$PARALLEL" -I{} sh -c '"$PYTHON" "$REPOSITORY/solver/solver_run.py" "$MODEL" "$EFFORT" --noise "$NOISE" --harness "$HARNESS" --config "$CONFIG" --out "$OUT" --workers 2 > "$OUT/run{}.log" 2>&1; echo "run {} done"'
"$PYTHON" "$REPOSITORY/solver/summarize_batch.py" "$OUT"
