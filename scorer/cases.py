"""Load the grids a submission is scored on. Trusted side only.

A grid is: a builder (ANDES network with an empty device slot and the disturbances), the
held-out runs with their clean truth (P, Q, V, theta at the device terminal), the measurement
noise sigmas, the metadata an operator would have, and the true device as a symbolic spec
(for the frequency-response and droop references).

Format kundur_family_v1: a test_cases/grid_* folder with holdout/case.json (network, operating
points and every run's events), holdout/<run>_clean.csv and holdout/answer_key.json; rebuilt by
grids/kundur_family.py from case.json.
"""
import json
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

from truth import regf1_spec

COLS = {"P": "active_power_pu", "Q": "reactive_power_pu", "V": "voltage_pu", "theta": "bus_angle_rad"}


@dataclass
class Run:
    id: str
    t: np.ndarray
    Y: dict                 # clean P, Q, V, theta (never leaves the trusted side)


@dataclass
class Grid:
    name: str
    role: str               # selection | test | monitor
    builder: str            # module in grids/ with build(device, params, run, pycode_path, spec)
    runs: list
    sigma: np.ndarray       # (sigma_P, sigma_Q)
    meta: dict
    truth_spec: dict        # true device as a symbolic submission
    spec_text: str          # case.json, passed to the builder in each worker

    @property
    def op(self):
        """(V0, theta0, P0, Q0) before the disturbance; the same for every run on a grid."""
        r = self.runs[0]
        return np.array([r.Y["V"][0], r.Y["theta"][0], r.Y["P"][0], r.Y["Q"][0]])


def _read_run(path, run_id):
    c = pd.read_csv(path)
    return Run(run_id, c["time_s"].to_numpy(float), {k: c[col].to_numpy(float) for k, col in COLS.items()})


def load_grid(entry, base_dir):
    path = os.path.normpath(os.path.join(base_dir, entry["path"]))
    if entry.get("format") != "kundur_family_v1":
        raise ValueError(f"unknown grid format {entry.get('format')}")
    hold = os.path.join(path, "holdout")
    key = json.load(open(os.path.join(hold, "answer_key.json")))
    spec_text = open(os.path.join(hold, "case.json")).read()
    case = json.loads(spec_text)
    run_ids = entry.get("runs") or [r for r, v in case["runs"].items() if v["split"] == "holdout"]
    meta = dict(key.get("metadata", {})) | dict(entry.get("meta", {}))
    runs = [_read_run(os.path.join(hold, f"{r}_clean.csv"), r) for r in run_ids]
    sigma = np.array([key["sigmas"]["P"], key["sigmas"]["Q"]])
    truth = regf1_spec.spec(key["params_used"], inner="full", Sn=float(key["device_rating_MVA"]))
    g = Grid(entry["name"], entry.get("role", "selection"), "kundur_family", runs, sigma, meta, truth,
             spec_text)
    for r in runs[1:]:
        a, b = runs[0], r
        if any(abs(a.Y[k][0] - b.Y[k][0]) > 1e-6 for k in COLS):
            raise ValueError(f"{g.name}: runs do not share a pre-disturbance operating point")
    return g


def load_config(path):
    cfg = json.load(open(path))
    base = os.path.dirname(os.path.abspath(path))
    return cfg, [load_grid(e, base) for e in cfg["grids"]]
