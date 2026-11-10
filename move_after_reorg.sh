#!/usr/bin/env bash
# One-time cleanup for a machine that had this repository before the Nov 9 reorganization (the desktop).
#
# git pull moves every tracked file, but it leaves behind what git never tracked: Docker sandboxes, *.debug.log,
# __pycache__, and any runs that were never committed. This script
#   1. moves what is left in the old folders to _leftovers_from_reorg/<old path> (ignored by git), and
#   2. moves the RSI loop repository from rsi/experiments to rsi_loops and gives the three loops their new names.
# It only prints what it would do unless you pass --go. Run it after `git pull` in the main repository.
#
#     bash move_after_reorg.sh          # dry run
#     bash move_after_reorg.sh --go
#
# Every move is a rename of a whole folder, so it is instant, and folders Docker made as root inside a sandbox
# come along without sudo. Running it twice is harmless: anything already moved is skipped.
set -uo pipefail

GO=0
if [ "${1:-}" = "--go" ]; then GO=1; fi
cd "$(dirname "$0")" || exit 1

if [ ! -d harnesses/v0/harness ]; then
    echo "harnesses/v0/harness is missing: run git pull in the main repository first"
    exit 1
fi

FAILED=0
move() {  # source destination
    if [ -e "$2" ]; then
        echo "SKIP    $1: $2 already exists, so move it by hand"
        FAILED=1
    elif [ "$GO" = 1 ]; then
        mkdir -p "$(dirname "$2")"
        if mv "$1" "$2"; then echo "moved   $1 -> $2"; else echo "FAILED  $1 -> $2"; FAILED=1; fi
    else
        echo "would move  $1 -> $2"
    fi
}

echo "== 1. what git left in the old folders"
OLD_PATHS=(runs harness_v0 experiments scorer/runs information_ladder/rungs rsi/candidates
           rsi/experiments/20261022_194111 rsi/experiments/20261022_210717 rsi/experiments/test_p10)
for old in "${OLD_PATHS[@]}"; do
    [ -e "$old" ] || continue
    if [ "$(git ls-files -- "$old" | wc -l)" -gt 0 ]; then
        echo "SKIP    $old: git still tracks files in it, so the pull did not finish"
        FAILED=1
        continue
    fi
    loose=$(git ls-files --others --exclude-standard -- "$old" | wc -l)
    if [ "$loose" -gt 0 ]; then
        echo "NOTE    $old holds $loose files that are neither in git nor ignored (runs never committed?)"
        git ls-files --others --exclude-standard --directory -- "$old" | head -20 | sed 's/^/          /'
    fi
    move "$old" "_leftovers_from_reorg/$old"
done
if [ "$GO" = 1 ] && [ -d _leftovers_from_reorg ] && [ ! -e _leftovers_from_reorg/README.md ]; then
    cat > _leftovers_from_reorg/README.md <<'NOTE'
# Left over from the Nov 9 reorganization

Files git never tracked, from folders the reorganization renamed: Docker sandboxes, *.debug.log, __pycache__,
and anything never committed. The paths below this folder are the old ones; the tracked files from the same
folders are now in results/, harnesses/ and analyses/ (see ../README.md for which went where). Git ignores this
folder. Delete it once you no longer need the sandboxes; Docker made some files as root, so that takes sudo rm -rf.
NOTE
fi

echo "== 2. the RSI loop repository"
if [ -d rsi/experiments/.git ]; then
    move rsi/experiments rsi_loops
    LOOPS=rsi/experiments
    [ "$GO" = 1 ] && [ -d rsi_loops/.git ] && LOOPS=rsi_loops
elif [ -d rsi_loops/.git ]; then
    LOOPS=rsi_loops
    echo "ok      rsi_loops is already there"
else
    echo "NOTE    no loop repository in rsi/experiments or rsi_loops; clone harness-experiments into rsi_loops"
    LOOPS=""
fi
if [ -n "$LOOPS" ]; then
    while read -r old new; do
        if [ -e "$LOOPS/$new" ]; then
            echo "ok      $new is already there"
            [ -e "$LOOPS/$old" ] && { echo "SKIP    $LOOPS/$old also exists; merge it by hand"; FAILED=1; }
        elif [ -e "$LOOPS/$old" ]; then
            move "$LOOPS/$old" "$LOOPS/$new"
        else
            echo "NOTE    $LOOPS/$old not found"
        fi
    done <<'LIST'
run1 2026-10-24_run1_haiku-low-updater_from-v0
run2_sonnetLow_updater 2026-10-25_run2_sonnet-low-updater_from-v0
run3_r5_menu_start 2026-11-01_run3_sonnet-low-updater_from-ladder-r5
LIST
fi

echo
if [ "$GO" = 0 ]; then
    echo "Dry run: nothing moved. Run again with --go to do it."
elif [ "$FAILED" = 1 ]; then
    echo "Some moves were skipped or failed (see above). Fix those and run again; it skips what is done."
else
    echo "Done. Now commit the loop renames in the loop repository:"
    echo "    cd rsi_loops && git status --short | head -20"
    echo "    git add -A && git commit -m 'Readable loop folder names' && git pull --no-rebase --no-edit && git push"
fi
