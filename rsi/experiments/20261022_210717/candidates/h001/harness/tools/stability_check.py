"""Closed-loop safety check for a submission, before you submit it.

    python tools/stability_check.py submission.json val/<file>.csv

1. Linearizes the model at the recording's first sample (V0, theta0, P0, Q0) and lists the eigenvalues of
   its state matrix with their time constants. Flags any unstable eigenvalue and any time constant under 5 ms.
2. Drives the model with a synthetic disturbance: a 1% voltage step at t = 1 s and a 0.01 rad angle step at
   t = 5 s, Vset held. Reports the largest P and Q excursion and the drift over the last second. A model that
   rings, grows or never settles will likely destabilize the grid it is put into, even if it replays well.

The grid is not simulated here, so a pass is necessary but not sufficient.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                      # noqa: E402
import pandas as pd                                     # noqa: E402
import submission_parser                                # noqa: E402
from open_loop_replay import ReplayFailure, replay_open_loop  # noqa: E402

MIN_TIME_CONSTANT_S = 0.005
STEP_DT_S = 0.002
DURATION_S = 10.0


def operating_point(csv_path):
    table = pd.read_csv(csv_path)
    if "run_id" in table:
        table = table[table["run_id"] == table["run_id"].iloc[0]]
    first = table.iloc[0]
    return [float(first["voltage_pu"]), float(first["bus_angle_rad"]),
            float(first["active_power_pu"]), float(first["reactive_power_pu"])]


def linear_report(model, point):
    if not model.state_names:
        print("linearization: no states (algebraic model)")
        return True
    lin = model.linearize(point)
    eig = np.linalg.eigvals(lin["A"])
    ok = True
    print("eigenvalues (real part, time constant s):")
    for value in sorted(eig, key=lambda z: -abs(z.real)):
        re_part = value.real
        tau = (1.0 / abs(re_part)) if abs(re_part) > 1e-12 else float("inf")
        print(f"   {value.real:+.4g} {value.imag:+.4g}j   tau {tau:.3g} s")
        if re_part >= 0:
            ok = False
    taus = [1.0 / abs(z.real) for z in eig if abs(z.real) > 1e-12]
    if taus and min(taus) < MIN_TIME_CONSTANT_S:
        print(f"WARNING: fastest time constant {min(taus):.3g} s is under {MIN_TIME_CONSTANT_S} s")
        ok = False
    if not ok:
        print("LINEARIZATION: UNSTABLE or too fast")
    else:
        print("linearization: stable, no time constant under the limit")
    return ok


def synthetic_step(model, point):
    times = np.arange(0.0, DURATION_S, STEP_DT_S)
    v0, th0 = point[0], point[1]
    volts = np.where(times >= 1.0, v0 * 1.01, v0)
    angles = th0 + np.where(times >= 5.0, 0.01, 0.0)
    inputs = np.column_stack([volts, angles])
    try:
        outputs, _ = replay_open_loop(model.bind(point), times, inputs, time_limit_s=60)
    except ReplayFailure as failure:
        print(f"synthetic step: FAILED ({failure})")
        return False
    dev = outputs - np.array([point[2], point[3]])
    tail = dev[times >= DURATION_S - 1.0]
    print(f"synthetic step: max |dP| {np.max(np.abs(dev[:, 0])):.3g} pu, max |dQ| {np.max(np.abs(dev[:, 1])):.3g} pu")
    print(f"   drift over last 1 s: dP {tail[:, 0].ptp():.3g} pu peak-to-peak, dQ {tail[:, 1].ptp():.3g} pu peak-to-peak")
    bounded = np.max(np.abs(dev)) < 1.0
    if not bounded:
        print("SYNTHETIC STEP: excursion too large")
    return bounded


def main(submission_path, csv_path):
    try:
        model = submission_parser.load_submission(submission_path)
    except submission_parser.SubmissionError as error:
        print(f"INVALID: {error}")
        return 1
    point = operating_point(csv_path)
    ok_lin = linear_report(model, point)
    ok_step = synthetic_step(model, point)
    print("PASS" if (ok_lin and ok_step) else "FAIL: fix the model before submitting")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
