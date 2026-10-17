"""Summarize a batch of harness runs: per-run score components and cost, then the spread.

    python summarize.py runs/batch_<time>        # prints a table and writes summary.md there
"""
import json
import os
import sys

import numpy as np


def main(batch):
    rows = []
    for tag in sorted(os.listdir(batch)):
        p = os.path.join(batch, tag, "meta.json")
        if os.path.exists(p):
            rows.append(json.load(open(p)))
    if not rows:
        print("no runs with meta.json in", batch)
        return
    lines = ["| run | $ | steps | submission | selection score | TD | FR | PAR | grid A held-out |",
             "|---|---|---|---|---|---|---|---|---|"]
    scores = []
    for m in rows:
        c = m.get("components", {})
        b, a = c.get("grid_B", {}), c.get("grid_A", {})
        s = m.get("score_selection")
        if s is not None:
            scores.append(s)
        f = lambda d, k: f"{d[k]:.3f}" if k in d else "-"
        lines.append(f"| {m['tag']} | {m['spent_usd']:.2f} | {m['steps']} | {m['submission_source']} | "
                     f"{s if s is not None else m.get('score_error', '-')} | {f(b, 'td')} | {f(b, 'fr')} | "
                     f"{f(b, 'par')} | {f(a, 'score')} |")
    cost = np.array([m["spent_usd"] for m in rows])
    lines.append("")
    if scores:
        s = np.array(scores)
        lines.append(f"selection score over {len(s)} runs: mean {s.mean():.3f}, std {s.std(ddof=1) if len(s) > 1 else 0:.3f}, "
                     f"min {s.min():.3f}, max {s.max():.3f}; runs at 2 (failed) {int(np.sum(s >= 2.0))}")
    lines.append(f"cost per run: mean ${cost.mean():.2f}, max ${cost.max():.2f}, total ${cost.sum():.2f}")
    text = "\n".join(lines)
    print(text)
    open(os.path.join(batch, "summary.md"), "w").write(text + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
