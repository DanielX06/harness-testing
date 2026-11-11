#!/bin/bash
# Usage: bash solver/run_solver_batch.sh <model> <effort> [runs, default 10] [parallel, default 2] [noisy|clean, default noisy]
#   model: 1-3 or haiku, sonnet, opus.  effort: 1-5 or low ... max.
# The same harness run <runs> times, <parallel> at a time, each scored with the scorer config. Results go in
# results/unfiled/<date>_<time>_<model>-<effort>_<noisy|clean>[_regf2][_<harness>]/ with batch.json (the settings) and summary.md.
# Move the folder into a study folder under results/ once it is done (results/README.md lists them).
# noisy: grid A data with PMU-grade noise, and the prompt says the channels carry it.
# clean: the noise-free copy (test_cases/make_noise_free_sandbox.py), and the prompt says the channels are noise-free.
# Three optional environment variables (HARNESS and CONFIG as paths relative to where you run the command):
#   HARNESS  harness folder (system.md, method.md, tools/), default harnesses/v0/harness; any other folder adds
#            its name to the batch folder's name (the folder above harness/ when the folder itself is called harness)
#   CONFIG   scorer config, default the device's config_min (scorer/config_min.json, or config_min_regf2.json for
#            REGF2); scorer/config_rsi.json (config_rsi_regf2.json) also scores every run on the hidden monitor grid
#            M (M2); use it for anything the RSI loop is compared with
#   DEVICE   REGF1 (default: grid A's recordings) or REGF2 (grid A2's); a REGF2 batch adds _regf2 to its folder name
#   bash solver/run_solver_batch.sh haiku low 10 2 clean
#   CONFIG=scorer/config_rsi.json bash solver/run_solver_batch.sh haiku low 40 4 clean
#   HARNESS=rsi_loops/<loop>/candidates/h003/harness CONFIG=scorer/config_rsi.json bash solver/run_solver_batch.sh haiku low 20 4 clean
#   DEVICE=REGF2 CONFIG=scorer/config_rsi_regf2.json bash solver/run_solver_batch.sh haiku low 10 2 clean
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
    HARNESS="$REPOSITORY/harnesses/v0/harness"
fi
DEVICE=${DEVICE:-REGF1}
case "$DEVICE" in
    REGF1) DEFAULT_CONFIG="$REPOSITORY/scorer/config_min.json"; DEVICE_SUFFIX="" ;;
    REGF2) DEFAULT_CONFIG="$REPOSITORY/scorer/config_min_regf2.json"; DEVICE_SUFFIX="_regf2" ;;
    *) echo "DEVICE must be REGF1 or REGF2, got '$DEVICE'" >&2; exit 1 ;;
esac
if [ -n "${CONFIG:-}" ]; then
    [ -f "$CONFIG" ] || { echo "CONFIG file not found: $CONFIG" >&2; exit 1; }
    CONFIG="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"
else
    CONFIG="$DEFAULT_CONFIG"
fi
SUFFIX="$DEVICE_SUFFIX"
if [ "$HARNESS" != "$REPOSITORY/harnesses/v0/harness" ]; then
    NAME="$(basename "$HARNESS")"
    [ "$NAME" = "harness" ] && NAME="$(basename "$(dirname "$HARNESS")")"     # harnesses/<name>/harness, candidates/hNNN/harness
    SUFFIX="${SUFFIX}_$NAME"
fi
BASE="$REPOSITORY/results/unfiled/$(date +%Y-%m-%d_%H%M%S)_${MODEL}-${EFFORT}_${NOISE}${SUFFIX}"
mkdir -p "$REPOSITORY/results/unfiled"
OUT="$BASE"; n=2
until mkdir "$OUT" 2>/dev/null; do OUT="${BASE}_$n"; n=$((n + 1)); done   # two batches in the same second
PYTHON="$REPOSITORY/../.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3
printf '{"model": "%s", "effort": "%s", "runs": %s, "parallel": %s, "noise": "%s", "device": "%s",\n "harness": "%s",\n "config": "%s",\n "git": "%s", "started": "%s"}\n' \
    "$MODEL" "$EFFORT" "$RUNS" "$PARALLEL" "$NOISE" "$DEVICE" "$HARNESS" "$CONFIG" \
    "$(cd "$REPOSITORY" && GIT_OPTIONAL_LOCKS=0 git describe --always --dirty 2>/dev/null || echo unknown)" \
    "$(date +%Y-%m-%dT%H:%M:%S%z)" > "$OUT/batch.json"
export PYTHON MODEL EFFORT OUT NOISE HARNESS CONFIG REPOSITORY DEVICE
seq "$RUNS" | xargs -P "$PARALLEL" -I{} sh -c '"$PYTHON" "$REPOSITORY/solver/solver_run.py" "$MODEL" "$EFFORT" --noise "$NOISE" --device "$DEVICE" --harness "$HARNESS" --config "$CONFIG" --out "$OUT" --workers 2 > "$OUT/run{}.log" 2>&1; echo "run {} done"'
"$PYTHON" "$REPOSITORY/solver/summarize_batch.py" "$OUT"
