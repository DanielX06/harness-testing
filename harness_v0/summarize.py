"""Summarize a batch of harness runs: per-run score components and cost, then the spread.

    python summarize.py runs/batch_<time>        # prints a table and writes summary.md there

The grid M column fills in only for runs scored with config_rsi.json, and the timeouts column only
for runs made after Oct 17 (older meta.json files don't record it); otherwise they show "-".
"""
import json
import os
import sys

import numpy as np


def spread(name, x):
    x = np.array(x)
    return (f"{name} over {len(x)} runs: mean {x.mean():.3f}, std {x.std(ddof=1) if len(x) > 1 else 0:.3f}, "
            f"min {x.min():.3f}, max {x.max():.3f}")


def main(batch):
    rows = []
    for tag in sorted(os.listdir(batch)):
        p = os.path.join(batch, tag, "meta.json")
        if os.path.exists(p):
            rows.append(json.load(open(p)))
    if not rows:
        print("no runs with meta.json in", batch)
        return
    lines = ["| run | $ | steps | timeouts | submission | selection score | TD | FR | PAR | grid A held-out | grid M (monitor) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    scores, monitor = [], []
    for m in rows:
        c = m.get("components", {})
        b, a, mon = c.get("grid_B", {}), c.get("grid_A", {}), c.get("grid_M", {})
        s = m.get("score_selection")
        if s is not None:
            scores.append(s)
        if "score" in mon:
            monitor.append(mon["score"])
        f = lambda d, k: f"{d[k]:.3f}" if k in d else "-"
        lines.append(f"| {m['tag']} | {m['spent_usd']:.2f} | {m['steps']} | {m.get('tool_timeouts', '-')} | "
                     f"{m['submission_source']} | {s if s is not None else m.get('score_error', '-')} | {f(b, 'td')} | "
                     f"{f(b, 'fr')} | {f(b, 'par')} | {f(a, 'score')} | {f(mon, 'score')} |")
    cost = np.array([m["spent_usd"] for m in rows])
    lines.append("")
    if scores:
        lines.append(spread("selection score", scores) + f"; runs at 2 (failed) {int(np.sum(np.array(scores) >= 2.0))}")
    if monitor:
        lines.append(spread("monitor score (grid M, never used for selection)", monitor))
    timed = [m for m in rows if "tool_timeouts" in m]
    if timed:
        n_to, n_calls = sum(m["tool_timeouts"] for m in timed), sum(m["tool_calls"] for m in timed)
        lines.append(f"tool calls cut off at 120 s: {n_to} of {n_calls} ({100 * n_to / max(1, n_calls):.1f}%)")
    lines.append(f"cost per run: mean ${cost.mean():.2f}, max ${cost.max():.2f}, total ${cost.sum():.2f}")
    text = "\n".join(lines)
    print(text)
    open(os.path.join(batch, "summary.md"), "w").write(text + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
