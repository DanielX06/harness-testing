"""Linear checks of a submission at its operating point, before it goes into the grid.

    python tools/stability_check.py submission.json val/<file>.csv

Uses the first sample of the given CSV as the operating point (V0, theta0, P0, Q0) and the scorer's own
linearization. Prints:
  - the eigenvalues of the state matrix, with the largest real part (must be negative);
  - the steady-state sensitivities dP/dV, dQ/dV, dP/dtheta, dQ/dtheta (V and theta held as inputs,
    states settled, Vset = V0);
  - warnings for: an eigenvalue with real part >= 0 (unstable), dQ/dV > 0 (Q rising with V is positive
    feedback through the grid), a time constant below 2 ms (faster than the 1 ms recording can resolve),
    and a singular state matrix (a pure integrator, which leaves the steady-state gain undefined).
A warning is a reason to look again at the structure, not a verdict on its own.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                      # noqa: E402
import pandas as pd                                     # noqa: E402
import submission_parser                                # noqa: E402


def main(submission_path, csv_path):
    model = submission_parser.load_submission(submission_path)
    first = pd.read_csv(csv_path).iloc[0]
    operating_point = [float(first["voltage_pu"]), float(first["bus_angle_rad"]),
                       float(first["active_power_pu"]), float(first["reactive_power_pu"])]
    lin = model.linearize(operating_point)
    A, B, C, D = lin["A"], lin["B"], lin["C"], lin["D"]
    warnings = []
    if A.size:
        eig = np.linalg.eigvals(A)
        real_parts = np.sort(eig.real)
        print("state eigenvalues (real, imag):")
        for lam in eig[np.argsort(eig.real)]:
            print(f"   {lam.real:+.4e} {lam.imag:+.4e}j")
        if real_parts[-1] >= 0:
            warnings.append(f"UNSTABLE linearization: largest real part {real_parts[-1]:.3e}")
        fast = np.abs(eig.real) > 1 / 0.002
        if np.any(fast):
            warnings.append("a pole faster than 2 ms (time constant below 2 ms): the 1 ms recording "
                            "cannot resolve it and replay may diverge")
        det = abs(np.linalg.det(A))
        if det < 1e-12:
            warnings.append("state matrix is singular (a pure integrator): steady-state gains are "
                            "computed with least squares and may be meaningless")
            G = -np.linalg.lstsq(A, B, rcond=None)[0]
        else:
            G = -np.linalg.solve(A, B)
    else:
        G = np.zeros((0, 2))
    S = D + C @ G
    print("steady-state sensitivities (rows P, Q; columns V, theta):")
    print(np.array2string(S, precision=4))
    if S[1, 0] > 0:
        warnings.append(f"dQ/dV = {S[1, 0]:.4g} > 0: Q rises with V, positive feedback in the grid")
    for message in warnings:
        print("WARNING:", message)
    if not warnings:
        print("no warnings")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2]))
