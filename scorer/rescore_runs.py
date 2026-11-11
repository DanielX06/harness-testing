"""Score saved solver runs again with today's scorer, for when the scorer itself was wrong.

    python scorer/rescore_runs.py results/<study>/<batch>/2*/ --reason "why" [--workers 2]
    python solver/summarize_batch.py results/<study>/<batch>

A submission is pure data, so a run can be scored again at no API cost. Only finished runs are scored. Each run's
old score/ and score.log are kept beside the new ones as score_before_<time>/ and score_before_<time>.log. The
scorer config is the one the run used, looked up by file name in this repository's scorer/ folder, since
meta.json records its path on the machine that made the run. meta.json gets the new scores in the fields
solver_run.py writes (score_selection, role_scores, components) and a "rescored" entry saying when, with which
commit, why, and what the scores were before. If the scorer fails, the run is left as it was.
"""
import argparse
import json
import os
import subprocess
import sys
import time

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPOSITORY_ROOT)
from common.project_paths import SCORER_DIR, SCORER_SCRIPT  # noqa: E402


def read_json(path):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def write_json(path, value):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(value, file, indent=1)
    os.replace(temporary, path)


def git_commit():
    result = subprocess.run(["git", "describe", "--always", "--dirty"], cwd=REPOSITORY_ROOT, capture_output=True,
                            text=True, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    return result.stdout.strip() or "unknown"


def inferred_config_name(run_dir):
    """config_rsi.json if the run's private scores cover the monitor grid M, else config_min.json."""
    private_path = os.path.join(run_dir, "score", "private.json")
    grids = read_json(private_path).get("grids", {}) if os.path.exists(private_path) else {}
    return "config_rsi.json" if "grid_M" in grids else "config_min.json"


def rescore(run_dir, reason, workers=None, scorer_script=str(SCORER_SCRIPT)):
    """Score one run again. Returns (selection score before, after), or raises RuntimeError and leaves it as it was."""
    meta_path = os.path.join(run_dir, "meta.json")
    if not os.path.exists(meta_path):
        raise RuntimeError("no meta.json (the run never got going)")
    meta = read_json(meta_path)
    # runs before Oct 17 have no status field: meta.json was written only once they had been scored
    status = meta.get("status") or ("finished" if os.path.exists(os.path.join(run_dir, "score", "public.json")) else None)
    if status != "finished":
        raise RuntimeError(f"status is {meta.get('status')!r}, not finished")
    if not os.path.exists(os.path.join(run_dir, "submission.json")):
        raise RuntimeError("no submission.json")
    # runs before Oct 20 do not record their config either: read it off the grids their scores cover
    config_name = os.path.basename(meta.get("config") or inferred_config_name(run_dir))
    config = os.path.join(SCORER_DIR, config_name)
    if not os.path.exists(config):
        raise RuntimeError(f"scorer config {config_name} not found in {SCORER_DIR}")
    score_dir, log_path = os.path.join(run_dir, "score"), os.path.join(run_dir, "score.log")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    kept_dir, kept_log = os.path.join(run_dir, f"score_before_{stamp}"), os.path.join(run_dir, f"score_before_{stamp}.log")
    for old, kept in ((score_dir, kept_dir), (log_path, kept_log)):
        if os.path.exists(old):
            os.rename(old, kept)
    command = [sys.executable, scorer_script, os.path.join(run_dir, "submission.json"), "--config", config,
               "--out", score_dir] + (["--workers", str(workers)] if workers else [])
    with open(log_path, "w") as log:
        return_code = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT).returncode
    public_path = os.path.join(score_dir, "public.json")
    if return_code != 0 or not os.path.exists(public_path):
        failed_log = os.path.join(run_dir, f"score_failed_{stamp}.log")
        os.rename(log_path, failed_log)
        if os.path.exists(score_dir):
            os.rename(score_dir, os.path.join(run_dir, f"score_failed_{stamp}"))
        for old, kept in ((score_dir, kept_dir), (log_path, kept_log)):
            if os.path.exists(kept):
                os.rename(kept, old)
        raise RuntimeError(f"scorer exit code {return_code}, see {os.path.basename(failed_log)}")
    public, private = read_json(public_path), read_json(os.path.join(score_dir, "private.json"))
    before = {key: meta.get(key) for key in ("score_selection", "role_scores", "components")}
    meta["score_selection"] = public["score"]
    meta["role_scores"] = private["role_scores"]
    meta["components"] = {grid: {key: values[key] for key in ("score", "td", "fr", "par")}
                          for grid, values in private["grids"].items()}
    meta.setdefault("rescored", []).append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "git_commit": git_commit(),
                                            "reason": reason, "config": config, "kept": os.path.basename(kept_dir),
                                            "before": before, **({} if meta.get("config") else
                                                                 {"config_inferred": "the run did not record its config; read off the grids in its private.json"})})
    write_json(meta_path, meta)
    return before["score_selection"], public["score"]


def main():
    parser = argparse.ArgumentParser(description="Score saved solver runs again with today's scorer.")
    parser.add_argument("runs", nargs="+", help="run folders (each with meta.json and submission.json)")
    parser.add_argument("--reason", required=True, help="why the runs are scored again, kept in meta.json")
    parser.add_argument("--workers", type=int, default=None, help="ANDES simulations at once")
    parser.add_argument("--scorer-script", default=str(SCORER_SCRIPT), help=argparse.SUPPRESS)   # for tests
    options = parser.parse_args()
    failed = 0
    for run_dir in options.runs:
        run_dir = run_dir.rstrip("/")
        name = os.path.basename(run_dir)
        print(f"{name}: scoring ...", flush=True)
        try:
            before, after = rescore(run_dir, options.reason, options.workers, options.scorer_script)
        except RuntimeError as error:
            failed += 1
            print(f"{name}: not rescored, {error}", flush=True)
            continue
        print(f"{name}: {before} -> {after}" + ("" if before != after else " (unchanged)"), flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
