"""Follow-up test: is the B_line crash caused by the fast positive Q-V gain itself, or by the missing
slow Q-V droop?

Adds a slow droop state to two crashing batch submissions, leaving the agent's model otherwise as written:
    xdr' = (Kdr*(V - V0) - xdr) / Tdr        Q_new = Q_old + xdr
Kdr = -25.10 - (fast gain), so the total steady-state dQ/dV equals the truth's -25.10 in every variant.
Tdr decides what the droop does at 1 Hz: with Tdr = 5 s it barely acts there, so the fast positive gain
survives (Re G_QV(1 Hz) stays near +0.5); with Tdr = 1 s it cancels it (Re G_QV(1 Hz) near 0 or below).
The script prints the linearized G_QV of each variant next to its scores so that is visible.

    ../../../.venv/bin/python run_droop.py --workers 3       # 7 variants, about 1 min each

Results: variants/droop_*.json, scores/droop_*/, results_droop.md.
How to read it:
  fast gain kept (Tdr 5 s) and B_line runs  -> the crash came from the missing slow droop
  fast gain kept (Tdr 5 s) and B_line crashes -> the fast positive gain is dangerous on its own
"""
import argparse
import copy
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))             # Harness_testing
sys.path.insert(0, os.path.join(ROOT, "scorer"))
import symbolic                                            # noqa: E402
import metrics as M                                        # noqa: E402
from cases import load_config                              # noqa: E402

BATCH = os.path.join(ROOT, "harness_v0", "runs", "batch_20261011_182645_m1e1")
SCORE = os.path.join(ROOT, "scorer", "score.py")
CONFIG = os.path.join(HERE, "config_gridB.json")
TRUE_GAIN = -25.10                                         # truth's steady-state dQ/dV on grid B (pu/pu)

BASES = {  # tag -> (folder, fast-gain param, Q output expression to extend)
    "8b47": ("20261011_185037_haiku_low_8b47", "Kqv"),
    "dc99": ("20261011_183336_haiku_low_dc99", "b"),
}
# (base, fast gain or None for the agent's value, Tdr in s)
VARIANTS = [
    ("8b47", None, 5.0), ("8b47", None, 1.0), ("8b47", 0.0, 5.0), ("8b47", 1.0, 5.0),
    ("dc99", None, 5.0), ("dc99", None, 1.0), ("dc99", 0.0, 5.0),
]

ap = argparse.ArgumentParser()
ap.add_argument("--workers", type=int, default=3)
ap.add_argument("--dry", action="store_true", help="build and linearize the variants, no scoring")
args = ap.parse_args()

_, grids = load_config(CONFIG)
gB = grids[0]
os.makedirs(os.path.join(HERE, "variants"), exist_ok=True)
rows = []
for tag, gain, Tdr in VARIANTS:
    folder, p = BASES[tag]
    sub = copy.deepcopy(json.load(open(os.path.join(BATCH, folder, "submission.json"))))
    if gain is not None:
        sub["params"][p] = gain
    k = sub["params"][p]
    sub["params"]["Kdr"] = TRUE_GAIN - k
    sub["params"]["Tdr"] = Tdr
    sub["states"]["xdr"] = {"rhs": "(Kdr*(V-V0)-xdr)/Tdr", "init": "0.0"}
    sub["outputs"]["Q"] = f"({sub['outputs']['Q']})+xdr"
    name = f"droop_{tag}_{p}{'orig' if gain is None else f'{gain:+.2f}'}_Td{Tdr:g}"
    path = os.path.join(HERE, "variants", name + ".json")
    json.dump(sub, open(path, "w"), indent=1)

    lin = symbolic.Model(sub).linearize(gB.op)
    G = M.transfer(*[lin[x] for x in "ABCD"], [1e-4, 0.1, 1.0])[:, 1, 0]
    gq = f"{G[0].real:+.1f} / {G[1].real:+.2f}{G[1].imag:+.2f}j / {G[2].real:+.2f}{G[2].imag:+.2f}j"
    head = f"| {tag} | {k:+.2f} | {Tdr:g} | {gq} |"
    print(f"{name}: G_QV(1e-4, 0.1, 1 Hz) = {gq}, init residual {lin['init_residual']:.1e}", flush=True)
    if args.dry:
        continue
    out = os.path.join(HERE, "scores", name)
    rc = subprocess.run([sys.executable, SCORE, path, "--config", CONFIG, "--out", out,
                         "--workers", str(args.workers)], capture_output=True, text=True).returncode
    try:
        d = json.load(open(os.path.join(out, "private.json")))["grids"]["grid_B"]
    except (OSError, KeyError, json.JSONDecodeError):
        rows.append(f"{head} scorer error (exit {rc}) | | | | | |")
        continue
    tdr = d["td_runs"]
    cell = lambda r: "CRASH" if "failure" in tdr[r] else f"{tdr[r]['P']:.2f} / {tdr[r]['Q']:.2f}"
    rows.append(f"{head} {cell('B_line')} | {cell('B_vref')} | {cell('B_load')} | {d['par_entries']['volt']:.2f} | "
                f"{d['fr_entries']['Q/V']:.2f} | {d['score']:.3f} |")
    print("  " + rows[-1], flush=True)

if not args.dry:
    table = "\n".join(["| base | fast gain | Tdr (s) | G_QV at 1e-4 Hz / 0.1 Hz / 1 Hz | B_line P / Q | B_vref P / Q | "
                       "B_load P / Q | PAR volt | FR Q/V | grid B score |",
                       "|---|---|---|---|---|---|---|---|---|---|"] + rows)
    table += ("\n\nTruth G_QV: -25.1 / +4.29+22.97j / +0.98+0.20j. Same bases without the droop: "
              "8b47 crashed at Kqv >= 0.2, dc99 at b = 0.61 (results.md).\n")
    open(os.path.join(HERE, "results_droop.md"), "w").write(table)
    print("\n" + table)
