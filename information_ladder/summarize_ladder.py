"""One row per rung for a ladder run (or several): selection score on grid B, grid M and grid A held-out, the
P-f and Q-V components, cost and steps.

    python information_ladder/summarize_ladder.py runs/ladder_<time>_<model>_<effort> [more ladder folders]

Writes ladder_summary.md into the first folder. Rows are in rung order; a rung with no finished runs shows "-".
Mean and standard deviation are over finished runs; runs that failed to score (2) are included, since that is
the rung's own outcome.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_rung import RUNG_NAMES  # noqa: E402


def rung_rows(ladder_dir):
    rows = []
    for rung in sorted(os.listdir(ladder_dir), key=lambda name: RUNG_NAMES.index(name) if name in RUNG_NAMES else 99):
        folder = os.path.join(ladder_dir, rung)
        if not os.path.isdir(folder):
            continue
        metas = []
        for tag in sorted(os.listdir(folder)):
            path = os.path.join(folder, tag, "meta.json")
            if os.path.exists(path):
                with open(path) as file:
                    metas.append(json.load(file))
        finished = [meta for meta in metas if meta.get("status") == "finished" and meta.get("score_selection") is not None]
        rows.append((os.path.basename(ladder_dir.rstrip("/")), rung, metas, finished))
    return rows


def describe(values):
    if not values:
        return "-"
    values = np.asarray(values, float)
    spread = values.std(ddof=1) if values.size > 1 else 0.0
    return f"{values.mean():.3f} ± {spread:.3f} ({values.min():.3f} to {values.max():.3f})"


def grid_values(finished, grid, key):
    return [meta["components"][grid][key] for meta in finished
            if grid in meta.get("components", {}) and key in meta["components"][grid]]


def main(argv=None):
    folders = list(sys.argv[1:] if argv is None else argv)
    if not folders:
        sys.exit(__doc__)
    lines = ["| ladder | rung | runs (finished) | grid B score | grid M | grid A held-out | B TD | B FR | B PAR | "
             "failed (2) | mean $ | mean steps |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for folder in folders:
        for ladder, rung, metas, finished in rung_rows(folder):
            selection = [meta["score_selection"] for meta in finished]
            failed = sum(1 for value in selection if value >= 2.0)
            cost = np.mean([meta.get("spent_usd", 0.0) for meta in metas]) if metas else float("nan")
            steps = np.mean([meta.get("steps", 0) for meta in metas]) if metas else float("nan")
            lines.append(f"| {ladder} | {rung} | {len(metas)} ({len(finished)}) | {describe(selection)} | "
                         f"{describe(grid_values(finished, 'grid_M', 'score'))} | "
                         f"{describe(grid_values(finished, 'grid_A', 'score'))} | "
                         f"{describe(grid_values(finished, 'grid_B', 'td'))} | {describe(grid_values(finished, 'grid_B', 'fr'))} | "
                         f"{describe(grid_values(finished, 'grid_B', 'par'))} | {failed} | {cost:.3f} | {steps:.0f} |")
    text = "\n".join(lines) + "\n"
    print(text)
    with open(os.path.join(folders[0], "ladder_summary.md"), "w") as file:
        file.write(text)


if __name__ == "__main__":
    main()
