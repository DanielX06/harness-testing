"""The grids a submission is scored on, loaded from a scorer config (config_min.json, config_rsi.json).

A scoring grid is a builder (it rebuilds the ANDES network with an empty device slot and replays each
held-out run's events), the held-out runs with their clean recordings at the device terminal, the
measurement-noise sigmas (for the time-domain floor), the metadata an operator would have, and the true
device written as a submission (the reference for the frequency response and the droops).

Grid format kundur_family_v1: a test_cases/grid_* folder with holdout/case.json (network, operating points
and every run's events), holdout/<run>_clean.csv and holdout/answer_key.json, rebuilt by
scorer/grids/kundur_family_builder.py.
"""
import json
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

from scorer.truth import truth_spec_for

SIGNAL_COLUMNS = {"P": "active_power_pu", "Q": "reactive_power_pu", "V": "voltage_pu", "theta": "bus_angle_rad"}
# grid format -> the module whose build_system() rebuilds its runs in ANDES
GRID_BUILDERS = {"kundur_family_v1": "scorer.grids.kundur_family_builder"}
# selection: its score goes to public.json and decides what the RSI loop keeps. monitor: scored on every run,
# private, never used to select. train_holdout: grid A's own held-out runs, private. test: a final evaluation.
GRID_ROLES = ("selection", "monitor", "train_holdout", "test")


@dataclass
class HeldOutRun:
    name: str
    times: np.ndarray
    clean_signals: dict             # P, Q, V, theta at the device terminal without noise (never leaves the scorer)


@dataclass
class ScoringGrid:
    name: str
    role: str
    builder_module: str             # module with build_system(device_model, device_params, run_name, pycode_path, case_spec)
    runs: list                      # HeldOutRun, all starting from the same operating point
    noise_sigmas: np.ndarray        # (sigma_P, sigma_Q)
    metadata: dict
    truth_submission: dict          # the true device as a submission
    case_spec_text: str             # case.json, passed to the builder in each worker process

    @property
    def operating_point(self):
        """(V0, theta0, P0, Q0) before the disturbance, shared by every run on the grid."""
        first = self.runs[0].clean_signals
        return np.array([first["V"][0], first["theta"][0], first["P"][0], first["Q"][0]])


def _read_held_out_run(path, name):
    recording = pd.read_csv(path)
    return HeldOutRun(name, recording["time_s"].to_numpy(float),
                      {signal: recording[column].to_numpy(float) for signal, column in SIGNAL_COLUMNS.items()})


def load_grid(entry, config_dir):
    """One grid from a config's "grids" list; paths in the config are relative to the config file."""
    name, role, grid_format = entry.get("name"), entry.get("role"), entry.get("format")
    if role not in GRID_ROLES:
        raise ValueError(f"grid {name}: role must be one of {GRID_ROLES}, got {role!r}")
    if grid_format not in GRID_BUILDERS:
        raise ValueError(f"grid {name}: unknown grid format {grid_format!r}")
    holdout_dir = os.path.join(os.path.normpath(os.path.join(config_dir, entry["path"])), "holdout")
    with open(os.path.join(holdout_dir, "answer_key.json")) as file:
        answer_key = json.load(file)
    with open(os.path.join(holdout_dir, "case.json")) as file:
        case_spec_text = file.read()
    case_spec = json.loads(case_spec_text)
    run_names = entry.get("runs") or [run for run, spec in case_spec["runs"].items() if spec["split"] == "holdout"]
    runs = [_read_held_out_run(os.path.join(holdout_dir, f"{run}_clean.csv"), run) for run in run_names]
    grid = ScoringGrid(
        name=name, role=role, builder_module=GRID_BUILDERS[grid_format], runs=runs,
        noise_sigmas=np.array([answer_key["sigmas"]["P"], answer_key["sigmas"]["Q"]]),
        metadata=dict(answer_key.get("metadata", {})) | dict(entry.get("meta", {})),
        truth_submission=truth_spec_for(answer_key["device"], answer_key["params_used"], answer_key["device_rating_MVA"]),
        case_spec_text=case_spec_text)
    first = runs[0]
    for run in runs[1:]:
        if any(abs(first.clean_signals[signal][0] - run.clean_signals[signal][0]) > 1e-6 for signal in SIGNAL_COLUMNS):
            raise ValueError(f"{name}: runs do not share a pre-disturbance operating point")
    return grid


def load_scoring_config(path):
    """(settings, grids): settings is the config without its "grids" list (weights, floors, timeouts)."""
    with open(path) as file:
        config = json.load(file)
    config_dir = os.path.dirname(os.path.abspath(path))
    settings = {key: value for key, value in config.items() if key != "grids"}
    return settings, [load_grid(entry, config_dir) for entry in config["grids"]]
