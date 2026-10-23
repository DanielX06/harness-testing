"""Linearizes a submission at a recording's first sample and reports whether it is safe to put in a grid.

    python tools/stability_check.py submission.json val/<file>.csv

Prints:
- the eigenvalues of the model's internal dynamics, with their time constants;
- the steady-state gains dP/dV, dP/dtheta, dQ/dV, dQ/dtheta with V, theta and Vset held (when they exist).

Flags (each one is a reason to revise the model before submitting):
- an eigenvalue with positive real part (the model is unstable on its own);
- a steady-state dQ/dV above zero (more Q when the terminal voltage rises: positive feedback through the grid);
- a time constant below 0.002 s (too fast to be a real device dynamic; it makes the replay stiff).
A zero eigenvalue (an integrator) is reported as a note, not a flag: the steady gains are then undefined,
so judge the voltage response from the staged-test replay instead.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                      # noqa: E402
import pandas as pd                                     # noqa: E402
import submission_parser                                # noqa: E402


def main(submission_path, csv_path):
    try:
        model = submission_parser.load_submission(submission_path)
    except submission_parser.SubmissionError as error:
        print(f"INVALID: {error}")
        return 1
    recording = pd.read_csv(csv_path).iloc[0]
    point = [float(recording["voltage_pu"]), float(recording["bus_angle_rad"]),
             float(recording["active_power_pu"]), float(recording["reactive_power_pu"])]
    lin = model.linearize(point)
    A, B, C, D = lin["A"], lin["B"], lin["C"], lin["D"]
    flags, notes = [], []
    integrator = False
    if A.size:
        eig = np.linalg.eigvals(A)
        print("eigenvalues (real, imag) and time constant 1/|real| [s]:")
        for value in sorted(eig, key=lambda z: -z.real):
            tau = (1.0 / abs(value.real)) if abs(value.real) > 1e-12 else float("inf")
            print(f"  {value.real:+.5g} {value.imag:+.5g}j   tau {tau:.4g}")
        if np.max(eig.real) > 1e-9:
            flags.append("unstable internal dynamics (eigenvalue with positive real part)")
        integrator = bool(np.min(np.abs(eig.real)) <= 1e-9)
        if integrator:
            notes.append("zero eigenvalue (integrator): steady gains are undefined; check the staged-test replay")
        if np.any(np.abs(eig.real[np.abs(eig.real) > 1e-12]) > 500):
            flags.append("a time constant below 0.002 s")
    if A.size and not integrator:
        gains = D - C @ np.linalg.solve(A, B)
        print("steady-state gains (rows P, Q; columns V, theta), V, theta, Vset held:")
        print(np.array2string(gains, precision=4))
        if gains[1, 0] > 0:
            flags.append(f"steady dQ/dV = {gains[1, 0]:.3g} > 0 (positive Q-V feedback)")
    else:
        print("direct gains D (rows P, Q; columns V, theta):")
        print(np.array2string(D, precision=4))
        if D[1, 0] > 0:
            flags.append(f"dQ/dV = {D[1, 0]:.3g} > 0 (positive Q-V feedback)")
    for note in notes:
        print("NOTE: " + note)
    if flags:
        print("FLAGS:")
        for flag in flags:
            print("  - " + flag)
        return 0
    print("no flags")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
