"""Checks submission.json before you submit it.

    python tools/check_submission.py submission.json [val/<file>.csv]

1. Parses the submission with the scorer's own rules (tools/submission_parser.py) and lists what it found.
2. With a CSV (columns [run_id,] time_s, active_power_pu, reactive_power_pu, voltage_pu, bus_angle_rad[,
   voltage_setpoint_pu]), checks that the model is at rest at each recording's first sample: the largest
   |d(state)/dt| there, and how far P and Q at t = 0 are from the measured ones. Both should be near zero.

It does not say how well the model fits. The scorer puts the model into a grid and reruns disturbances closed
loop, so the model's own P and Q feed back into V and theta. How to check that before submitting is up to you.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import submission_parser                                # noqa: E402

INPUT_COLUMNS = ["voltage_pu", "bus_angle_rad"]
OUTPUT_COLUMNS = ["active_power_pu", "reactive_power_pu"]


def recordings_in(table):
    """(recording id, rows) for each recording in the file: one per run_id, or the whole file."""
    return table.groupby("run_id") if "run_id" in table else [("run", table)]


def check_rest(model, recording_id, recording):
    """Print the steady-state check at the recording's first sample."""
    first = recording.iloc[0]
    operating_point = [float(first[INPUT_COLUMNS[0]]), float(first[INPUT_COLUMNS[1]]),
                       float(first[OUTPUT_COLUMNS[0]]), float(first[OUTPUT_COLUMNS[1]])]
    linearization = model.linearize(operating_point)
    print(f"{recording_id}: init residual max|dx/dt| = {linearization['init_residual']:.2e}, "
          f"output mismatch at t=0 = {linearization['init_output_mismatch']:.2e}")


def check_submission(submission_path, csv_path=None):
    """Returns 1 if the submission is invalid, 0 otherwise."""
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
        check_rest(model, recording_id, recording)
    return 0


if __name__ == "__main__":
    sys.exit(check_submission(*sys.argv[1:3]))
