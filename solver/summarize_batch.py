"""Summarize a batch of solver runs: one row per run (status, cost, score components), then the spread.

    python solver/summarize_batch.py runs/batch_<time>      # prints the table and writes summary.md there

The grid M column fills in only for runs scored with config_rsi.json; older runs (before the status field)
show their status as "-". Every run's spend counts, including runs that crashed.
"""
import json
import os
import sys

import numpy as np


def spread(name, values):
    values = np.array(values)
    deviation = values.std(ddof=1) if len(values) > 1 else 0
    return (f"{name} over {len(values)} runs: mean {values.mean():.3f}, std {deviation:.3f}, "
            f"min {values.min():.3f}, max {values.max():.3f}")


def read_runs(batch_dir):
    runs = []
    for tag in sorted(os.listdir(batch_dir)):
        path = os.path.join(batch_dir, tag, "meta.json")
        if os.path.exists(path):
            with open(path) as file:
                runs.append(json.load(file))
    return runs


def summarize(batch_dir):
    runs = read_runs(batch_dir)
    if not runs:
        print("no runs with meta.json in", batch_dir)
        return None
    lines = ["| run | status | $ | steps | timeouts | submission | selection score | TD | FR | PAR | grid A held-out | grid M (monitor) |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    selection_scores, monitor_scores = [], []

    def cell(components, key):
        return f"{components[key]:.3f}" if key in components else "-"

    for meta in runs:
        components = meta.get("components", {})
        grid_b, grid_a, grid_m = components.get("grid_B", {}), components.get("grid_A", {}), components.get("grid_M", {})
        selection = meta.get("score_selection")
        if selection is not None:
            selection_scores.append(selection)
        if "score" in grid_m:
            monitor_scores.append(grid_m["score"])
        shown_selection = selection if selection is not None else meta.get("score_error", "-")
        lines.append(f"| {meta['tag']} | {meta.get('status', '-')} | {meta['spent_usd']:.2f} | {meta['steps']} | "
                     f"{meta.get('tool_timeouts', '-')} | {meta.get('submission_source') or '-'} | {shown_selection} | "
                     f"{cell(grid_b, 'td')} | {cell(grid_b, 'fr')} | {cell(grid_b, 'par')} | {cell(grid_a, 'score')} | "
                     f"{cell(grid_m, 'score')} |")
    costs = np.array([meta["spent_usd"] for meta in runs])
    lines.append("")
    if selection_scores:
        failed = int(np.sum(np.array(selection_scores) >= 2.0))
        lines.append(spread("selection score", selection_scores) + f"; runs at 2 (failed) {failed}")
    if monitor_scores:
        lines.append(spread("monitor score (grid M, never used for selection)", monitor_scores))
    unfinished = [meta["tag"] for meta in runs if meta.get("status") not in (None, "finished")]
    if unfinished:
        lines.append(f"not finished (resume with solver/solver_run.py --resume): {', '.join(unfinished)}")
    counted = [meta for meta in runs if meta.get("tool_timeouts") is not None]
    if counted:
        timeouts, calls = sum(meta["tool_timeouts"] for meta in counted), sum(meta["tool_calls"] for meta in counted)
        lines.append(f"tool calls cut off at 120 s: {timeouts} of {calls} ({100 * timeouts / max(1, calls):.1f}%)")
    lines.append(f"cost per run: mean ${costs.mean():.2f}, max ${costs.max():.2f}, total ${costs.sum():.2f}")
    text = "\n".join(lines)
    print(text)
    with open(os.path.join(batch_dir, "summary.md"), "w") as file:
        file.write(text + "\n")
    return text


if __name__ == "__main__":
    summarize(sys.argv[1])
