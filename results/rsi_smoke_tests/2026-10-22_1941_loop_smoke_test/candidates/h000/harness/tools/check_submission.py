"""Checks submission.json before you submit it.

    python tools/check_submission.py submission.json val/<file>.csv

1. Parses the submission with the scorer's own rules (tools/submission_parser.py) and lists what it found.
2. With a CSV (columns [run_id,] time_s, active_power_pu, reactive_power_pu, voltage_pu, bus_angle_rad[,
   voltage_setpoint_pu]), checks that each recording's first sample is a steady state of the model, then
   replays the recording open loop: the measured V and theta (and the logged voltage setpoint, if the file
   has one) drive the model, and its P and Q are compared with the measured ones.

The scorer does not replay. It puts the model into the grid and reruns the disturbances closed loop, so the
model's own P and Q feed back into V and theta. A model can replay well and still score badly closed loop
(or the reverse: a model with very fast internal dynamics can diverge in open-loop replay yet run fine in
the grid). Treat the replay numbers as a sanity check.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                      # noqa: E402
import submission_parser                                # noqa: E402
from open_loop_replay import ReplayFailure, replay_open_loop  # noqa: E402

INPUT_COLUMNS = ["voltage_pu", "bus_angle_rad"]
SETPOINT_COLUMN = "voltage_setpoint_pu"
OUTPUT_COLUMNS = ["active_power_pu", "reactive_power_pu"]


def recordings_in(table):
    """(recording id, rows) for each recording in the file: one per run_id, or the whole file."""
    return table.groupby("run_id") if "run_id" in table else [("run", table)]


def check_recording(model, recording_id, recording):
    """Print the steady-state check and the open-loop replay errors for one recording."""
    times = recording["time_s"].to_numpy(float)
    columns = INPUT_COLUMNS + ([SETPOINT_COLUMN] if SETPOINT_COLUMN in recording else [])
    inputs = recording[columns].to_numpy(float)
    measured = recording[OUTPUT_COLUMNS].to_numpy(float)
    operating_point = [inputs[0, 0], inputs[0, 1], measured[0, 0], measured[0, 1]]
    linearization = model.linearize(operating_point)
    print(f"{recording_id}: init residual max|dx/dt| = {linearization['init_residual']:.2e}, "
          f"output mismatch at t=0 = {linearization['init_output_mismatch']:.2e}")
    try:
        replayed, _ = replay_open_loop(model.bind(operating_point), times, inputs, time_limit_s=100)
        replay_rmse = np.sqrt(np.mean((replayed - measured) ** 2, axis=0))
        flat_rmse = np.sqrt(np.mean((measured - measured[0]) ** 2, axis=0))
        print(f"   open-loop replay RMSE  P {replay_rmse[0]:.2e} (flat {flat_rmse[0]:.2e})   "
              f"Q {replay_rmse[1]:.2e} (flat {flat_rmse[1]:.2e})")
    except ReplayFailure as failure:
        print(f"   open-loop replay failed: {failure}")


def check_submission(submission_path, csv_path=None):
    """Returns 1 if the submission is invalid, 0 otherwise (a failed replay is reported, not an error)."""
    try:
        model = submission_parser.load_submission(submission_path)
    except submission_parser.SubmissionError as error:
        print(f"INVALID: {error}")
        return 1
    print(f"OK: {len(model.state_names)} states {model.state_names}, {len(model.params)} params, {len(model.defs)} defs")
    if not csv_path:
        return 0
    import pandas as pd
    for recording_id, recording in recordings_in(pd.read_csv(csv_path)):
        check_recording(model, recording_id, recording)
    return 0


if __name__ == "__main__":
    sys.exit(check_submission(*sys.argv[1:3]))
