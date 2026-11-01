#!/bin/bash
# Usage: bash information_ladder/run_ladder.sh <model> <effort> [runs per rung, default 10] [parallel, default 2] [rung ...]
#   model: 1-3 or haiku, sonnet, opus.  effort: 1-5 or low ... max.  rungs: default every rung, r0_v0 to r6_structure_given.
# Runs each rung <runs> times, <parallel> at a time, rung after rung, all on noise-free data. Results go in
#   runs/ladder_<time>_<model>_<effort>/<rung>/   (one batch folder per rung, with batch.json and summary.md)
# and the ladder's table in runs/ladder_<time>_<model>_<effort>/ladder_summary.md.
# CONFIG (optional, a path relative to where you run the command) picks the scorer config; the default is
# scorer/config_rsi.json, so every run is also scored on the hidden monitor grid M, like the RSI baselines.
#   bash information_ladder/run_ladder.sh haiku low 10 2
#   bash information_ladder/run_ladder.sh sonnet low 10 2 r0_v0 r1_grid_equivalent
# Keep <parallel> the same for every batch you compare. A run that crashes can be finished with
#   python solver/solver_run.py --resume <run folder>
set -u
MODEL=$1; EFFORT=$2; RUNS=${3:-10}; PARALLEL=${4:-2}
shift $(( $# < 4 ? $# : 4 ))
RUNGS="$*"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPOSITORY="$(cd "$HERE/.." && pwd)"
if [ -n "${CONFIG:-}" ]; then
    [ -f "$CONFIG" ] || { echo "CONFIG file not found: $CONFIG" >&2; exit 1; }
    CONFIG="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"
else
    CONFIG="$REPOSITORY/scorer/config_rsi.json"
fi
PYTHON="$REPOSITORY/../.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3
[ -n "$RUNGS" ] || RUNGS="$("$PYTHON" -c "import sys; sys.path.insert(0, '$HERE'); from run_rung import RUNG_NAMES; print(' '.join(RUNG_NAMES))")"
LADDER="$REPOSITORY/runs/ladder_$(date +%Y%m%d_%H%M%S)_${MODEL}_${EFFORT}"
mkdir -p "$LADDER"
GIT="$(cd "$REPOSITORY" && GIT_OPTIONAL_LOCKS=0 git describe --always --dirty 2>/dev/null || echo unknown)"
for RUNG in $RUNGS; do
    OUT="$LADDER/$RUNG"
    mkdir -p "$OUT"
    printf '{"model": "%s", "effort": "%s", "runs": %s, "parallel": %s, "noise": "clean", "rung": "%s",\n "config": "%s",\n "git": "%s", "started": "%s"}\n' \
        "$MODEL" "$EFFORT" "$RUNS" "$PARALLEL" "$RUNG" "$CONFIG" "$GIT" "$(date +%Y-%m-%dT%H:%M:%S%z)" > "$OUT/batch.json"
    echo "== $RUNG"
    export PYTHON MODEL EFFORT OUT CONFIG REPOSITORY RUNG
    seq "$RUNS" | xargs -P "$PARALLEL" -I{} sh -c '"$PYTHON" "$REPOSITORY/information_ladder/run_rung.py" "$RUNG" "$MODEL" "$EFFORT" --config "$CONFIG" --out "$OUT" --workers 2 > "$OUT/run{}.log" 2>&1; echo "  run {} done"'
    "$PYTHON" "$REPOSITORY/solver/summarize_batch.py" "$OUT" > /dev/null
done
"$PYTHON" "$REPOSITORY/information_ladder/summarize_ladder.py" "$LADDER"
