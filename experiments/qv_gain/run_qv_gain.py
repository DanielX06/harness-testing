"""Intervention test: does the size of a submission's fast Q-V gain decide whether grid B's line trip crashes?

Takes two batch submissions that crashed B_line and whose Q responds to V through a single gain:
  8b47: x' = (Kqs*(Vset-V0) + Kqv*(V-V0) - x)/Tq, Q = Q0 + x + ...     (Tq = 10 ms)  -> scale Kqv
  dc99: xq' = (Q0 + a*(Vset-V0) + b*(V-V0) + ... - xq)/Tq, Q = xq      (Tq = 38 ms)  -> scale b
Everything else in each submission stays exactly as the agent wrote it. Each variant is scored on
grid B with the real scorer, and the table at the end shows B_line pass/fail against the gain.

    ../../../.venv/bin/python run_qv_gain.py              # all variants, about 1 min each
    ../../../.venv/bin/python run_qv_gain.py --workers 3

Results: variants/<name>.json, scores/<name>/, results.md.
Note: in both models the gain is static, so it sets the fast AND the steady-state dQ/dV together.
This test can show whether the gain is causal; it cannot say which time scale matters.
"""
import argparse
import copy
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))             # Harness_testing
BATCH = os.path.join(ROOT, "harness_v0", "runs", "batch_20261011_182645_m1e1")
SCORE = os.path.join(ROOT, "scorer", "score.py")
CONFIG = os.path.join(HERE, "config_gridB.json")

BASES = {  # run tag suffix -> (folder, param to scale, original value)
    "8b47": ("20261011_185037_haiku_low_8b47", "Kqv"),
    "dc99": ("20261011_183336_haiku_low_dc99", "b"),
}
# gains to try; the batch survivors had 0 to 0.17 at 1 Hz, the crashers 0.56 and up, the truth +0.98
GAINS = [None, 0.4, 0.3, 0.2, 0.1, 0.0, -0.3]               # None = the agent's original value

ap = argparse.ArgumentParser()
ap.add_argument("--workers", type=int, default=3)
args = ap.parse_args()

os.makedirs(os.path.join(HERE, "variants"), exist_ok=True)
rows = []
for tag, (folder, p) in BASES.items():
    base = json.load(open(os.path.join(BATCH, folder, "submission.json")))
    for g in GAINS:
        sub = copy.deepcopy(base)
        if g is not None:
            sub["params"][p] = g
        val = sub["params"][p]
        name = f"{tag}_{p}_{'orig' if g is None else f'{g:+.2f}'}"
        path = os.path.join(HERE, "variants", name + ".json")
        json.dump(sub, open(path, "w"), indent=1)
        out = os.path.join(HERE, "scores", name)
        print(f"scoring {name} ({p} = {val}) ...", flush=True)
        rc = subprocess.run([sys.executable, SCORE, path, "--config", CONFIG, "--out", out,
                             "--workers", str(args.workers)], capture_output=True, text=True).returncode
        try:
            d = json.load(open(os.path.join(out, "private.json")))["grids"]["grid_B"]
        except (OSError, KeyError, json.JSONDecodeError):
            rows.append(f"| {tag} | {p} = {val:+.3f} | scorer error (exit {rc}) | | | | |")
            continue
        tdr = d["td_runs"]
        cell = lambda r: "CRASH" if "failure" in tdr[r] else f"{tdr[r]['P']:.2f} / {tdr[r]['Q']:.2f}"
        rows.append(f"| {tag} | {p} = {val:+.3f} | {cell('B_line')} | {cell('B_vref')} | {cell('B_load')} | "
                    f"{d['par_entries']['volt']:.2f} | {d['score']:.3f} |")
        print("  " + rows[-1], flush=True)

table = "\n".join(["| base | gain | B_line P / Q | B_vref P / Q | B_load P / Q | PAR volt | grid B score |",
                   "|---|---|---|---|---|---|---|"] + rows)
open(os.path.join(HERE, "results.md"), "w").write(table + "\n")
print("\n" + table)
