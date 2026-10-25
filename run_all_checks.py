"""Every check this repository has, in one go.

    python run_all_checks.py                     # the fast checks: no API key, no Docker, no ANDES
    python run_all_checks.py --andes             # also the closed-loop scorer tests and a re-score of saved runs
    python run_all_checks.py --andes --rescore 10
    python run_all_checks.py --andes --rebuild-grid B      # also rebuild grid B and compare it with the committed one

The fast checks are the submission parser's (scorer/tests/test_submission_parser.py), a solver run against a fake
API, sandbox and scorer (solver/tests/test_solver_run.py) and the RSI loop's four test files (rsi/tests/). They
take a few minutes and run anywhere the venv's numpy, pandas and sympy do.

--andes needs ANDES (the shared venv on the Mac). It runs scorer/tests/test_scorer.py --quick, then scores the
newest --rescore saved submissions in harness_v0/runs again with today's scorer and compares each with the score
it got when it was made. A submission is pure data and the simulation is deterministic, so they should agree to
the 4 decimals public.json keeps; a difference means the scorer changed (or the run was scored by an older one).
--rebuild-grid simulates a grid again with test_cases/build_test_grids.py into a scratch folder and compares it with
the committed one: case.json byte for byte, every recording to within 1e-6 pu.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile
import time

import numpy as np

REPOSITORY_ROOT = os.path.dirname(os.path.abspath(__file__))
FAST_CHECKS = ["scorer/tests/test_submission_parser.py", "solver/tests/test_solver_run.py",
               "rsi/tests/test_updater_context.py", "rsi/tests/test_harness_proposal.py",
               "rsi/tests/test_rsi_experiment.py", "rsi/tests/test_experiment_archive.py"]
ANDES_CHECKS = [["scorer/tests/test_scorer.py", "--quick"]]


def run_check(command):
    """(passed, last line of output, seconds) for one test script."""
    started = time.monotonic()
    result = subprocess.run([sys.executable, *command], cwd=REPOSITORY_ROOT, capture_output=True, text=True)
    output = result.stdout if result.returncode == 0 else result.stdout + result.stderr
    lines = [line for line in output.strip().splitlines() if line.strip()]
    return result.returncode == 0, (lines[-1] if lines else ""), time.monotonic() - started


def newest_saved_submissions(count):
    """(run folder, stored public.json) for the newest scored runs in harness_v0/runs, newest first."""
    runs = []
    for run_dir in glob.glob(os.path.join(REPOSITORY_ROOT, "harness_v0", "runs", "batch_*", "2*")):
        public_path = os.path.join(run_dir, "score", "public.json")
        if os.path.exists(public_path) and os.path.exists(os.path.join(run_dir, "submission.json")):
            runs.append(run_dir)
    runs.sort(key=os.path.basename, reverse=True)
    picked = []
    for run_dir in runs[:count]:
        with open(os.path.join(run_dir, "score", "public.json")) as file:
            picked.append((run_dir, json.load(file)))
    return picked


def rescore(count, workers):
    """Score saved submissions again and compare. Returns the number that differ."""
    sys.path.insert(0, REPOSITORY_ROOT)
    from common.project_paths import MIN_SCORER_CONFIG
    from scorer.score_submission import SubmissionScorer
    scorer = SubmissionScorer(str(MIN_SCORER_CONFIG), worker_count=workers,
                              andes_log_dir=tempfile.mkdtemp(prefix="rescore_logs_"))
    differing = 0
    print(f"\nre-scoring the {count} newest saved submissions on {os.path.basename(str(MIN_SCORER_CONFIG))}:")
    for run_dir, stored in newest_saved_submissions(count):
        report = scorer.score(os.path.join(run_dir, "submission.json"))
        new, old = report.public, stored
        differences = []
        if abs((new["score"] or 0) - (old["score"] or 0)) > 1.5e-4:
            differences.append(f"score {old['score']} -> {new['score']}")
        for grid, entry in old.get("grids", {}).items():
            for key in ("td", "fr", "par"):
                if key in entry and abs(new["grids"].get(grid, {}).get(key, float("nan")) - entry[key]) > 1.5e-4:
                    differences.append(f"{grid} {key} {entry[key]} -> {new['grids'].get(grid, {}).get(key)}")
        differing += bool(differences)
        print(f"  {os.path.basename(os.path.dirname(run_dir))}/{os.path.basename(run_dir)}: "
              f"{'same' if not differences else 'DIFFERENT: ' + '; '.join(differences)} (stored {old['score']})", flush=True)
    return differing


def rebuild_and_compare(grid_key, workers, tolerance=1e-6):
    """Rebuild one grid in a scratch folder and compare it with the committed one. Returns 1 if they differ."""
    scratch = tempfile.mkdtemp(prefix=f"rebuilt_grid_{grid_key}_")
    command = [sys.executable, "test_cases/build_test_grids.py", "--grids", grid_key, "--out", scratch]
    command += ["--workers", str(workers)] if workers else []
    print(f"\nrebuilding grid {grid_key} in {scratch} ...", flush=True)
    result = subprocess.run(command, cwd=REPOSITORY_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print("FAIL  the rebuild stopped:", (result.stdout + result.stderr).strip().splitlines()[-1:])
        return 1
    committed = os.path.join(REPOSITORY_ROOT, "test_cases", f"grid_{grid_key}")
    rebuilt = os.path.join(scratch, f"grid_{grid_key}")
    problems = []
    with open(os.path.join(committed, "holdout", "case.json")) as old, open(os.path.join(rebuilt, "holdout", "case.json")) as new:
        if old.read() != new.read():
            problems.append("case.json differs")
    for path in sorted(glob.glob(os.path.join(committed, "holdout", "*.csv")) + glob.glob(os.path.join(committed, "sandbox_data", "*", "*.csv"))):
        relative = os.path.relpath(path, committed)
        old_values = np.loadtxt(path, delimiter=",", skiprows=1)
        new_values = np.loadtxt(os.path.join(rebuilt, relative), delimiter=",", skiprows=1)
        difference = np.max(np.abs(old_values - new_values)) if old_values.shape == new_values.shape else float("inf")
        print(f"  {relative}: largest difference {difference:.1e}")
        if not difference <= tolerance:
            problems.append(f"{relative} differs by {difference:.1e}")
    print(("pass  " if not problems else "FAIL  ") + f"grid {grid_key} rebuilt" + (": " + "; ".join(problems) if problems else
                                                                                   f", every recording within {tolerance:g} pu"))
    return 1 if problems else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--andes", action="store_true", help="also the checks that need ANDES")
    parser.add_argument("--rescore", type=int, default=6, help="saved submissions to score again with --andes")
    parser.add_argument("--workers", type=int, default=None, help="ANDES simulations at once when re-scoring or rebuilding")
    parser.add_argument("--rebuild-grid", default=None, metavar="LETTER", help="with --andes: rebuild this grid and compare")
    options = parser.parse_args()
    commands = [[path] for path in FAST_CHECKS] + (ANDES_CHECKS if options.andes else [])
    failed = 0
    for command in commands:
        passed, last_line, seconds = run_check(command)
        failed += not passed
        print(f"{'pass' if passed else 'FAIL'}  {' '.join(command):40s} {seconds:6.0f} s  {last_line[:100]}", flush=True)
    if options.andes and options.rescore:
        failed += rescore(options.rescore, options.workers)
    if options.andes and options.rebuild_grid:
        failed += rebuild_and_compare(options.rebuild_grid, options.workers)
    print("\nall checks passed" if not failed else f"\n{failed} check(s) failed or differed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
