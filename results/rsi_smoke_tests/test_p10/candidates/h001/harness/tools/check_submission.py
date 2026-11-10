"""Checker for submission.json.

    python tools/check_submission.py submission.json val/<file>.csv

1. Parses the submission with the same rules as the scorer and lists what it found.
2. With a CSV (columns [run_id,] time_s, active_power_pu, reactive_power_pu, voltage_pu,
   bus_angle_rad[, voltage_setpoint_pu]), checks that each run's first sample is a steady state of
   the model, then replays the run open loop: the measured V and theta (and the logged voltage
   setpoint, if the file has one) drive the model and its P, Q are compared with the measured ones.
3. With a CSV, also runs the linear closed-loop grid check (tools/grid_check.py). An UNSTABLE
   verdict means the model is likely to fail in the scorer's grid.

The scorer does not replay. It puts the model into the grid and reruns the disturbances closed
loop, so the model's own P and Q feed back into V and theta. A model can replay well and still
score badly closed loop (or the reverse: a model with very fast internal dynamics can diverge
in open-loop replay yet run fine in the grid). Treat the replay numbers as a sanity check.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                     # noqa: E402
import symbolic                        # noqa: E402
from replay import replay, ReplayFailure  # noqa: E402


def main(path, csv=None):
    try:
        m = symbolic.load(path)
    except symbolic.SubmissionError as e:
        print(f"INVALID: {e}")
        return 1
    print(f"OK: {len(m.state_names)} states {m.state_names}, {len(m.params)} params, {len(m.defs)} defs")
    if not csv:
        return 0
    import pandas as pd
    df = pd.read_csv(csv)
    groups = df.groupby("run_id") if "run_id" in df else [("run", df)]
    for rid, g in groups:
        t = g["time_s"].to_numpy(float)
        cols = ["voltage_pu", "bus_angle_rad"] + (["voltage_setpoint_pu"] if "voltage_setpoint_pu" in g else [])
        U = g[cols].to_numpy(float)
        Y = g[["active_power_pu", "reactive_power_pu"]].to_numpy(float)
        op = [U[0, 0], U[0, 1], Y[0, 0], Y[0, 1]]
        lin = m.linearize(op)
        print(f"{rid}: init residual max|dx/dt| = {lin['init_residual']:.2e}, "
              f"output mismatch at t=0 = {lin['init_output_mismatch']:.2e}")
        try:
            Yp, _ = replay(m.bind(op), t, U, Y[0], timeout_s=100)
            rmse = np.sqrt(np.mean((Yp - Y) ** 2, axis=0))
            flat = np.sqrt(np.mean((Y - Y[0]) ** 2, axis=0))
            print(f"   open-loop replay RMSE  P {rmse[0]:.2e} (flat {flat[0]:.2e})   "
                  f"Q {rmse[1]:.2e} (flat {flat[1]:.2e})")
        except ReplayFailure as e:
            print(f"   open-loop replay failed: {e}")
    print("--- linear closed-loop grid check ---")
    try:
        import grid_check
        grid_check.report(m, csv)
    except Exception as e:  # the check is advisory; never hide the replay results
        print(f"grid check failed to run: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
