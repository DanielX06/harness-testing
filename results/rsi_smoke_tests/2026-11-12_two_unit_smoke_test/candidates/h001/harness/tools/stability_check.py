"""Linearizes submission.json at a recording's first sample and reports whether the model is stable and how fast it is.

    python tools/stability_check.py submission.json train/<file>.csv

Prints:
  - the eigenvalues of the model's own linear dynamics (state rates), with time constants in s and frequency in Hz;
  - UNSTABLE if any eigenvalue has a positive real part (the grid simulation may then fail);
  - FAST if any eigenvalue has |real part| above 1/(0.01 s), i.e. a loop faster than the filters the
    documentation allows (a sign of an overly fast inner path that can destabilize the grid);
  - the instantaneous output sensitivities dP/dV, dP/dtheta, dQ/dV, dQ/dtheta at the operating point.
Neutral modes (eigenvalue near 0, such as an angle state with no restoring term) are expected and are not flagged.
Nothing is fitted; this only reports what the submission already says.
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
    print(f"states: {model.state_names}")
    print(f"init residual {lin['init_residual']:.2e}, output mismatch {lin['init_output_mismatch']:.2e}")
    flags = []
    if A.size:
        eig = np.linalg.eigvals(A)
        order = np.argsort(-np.real(eig))
        for k in order:
            re, im = np.real(eig[k]), np.imag(eig[k])
            tau = (1.0 / abs(re)) if abs(re) > 1e-12 else float("inf")
            print(f"  eig {re:+.4g} {im:+.4g}j   tau={tau:.4g} s   f={abs(im)/(2*np.pi):.4g} Hz")
        if np.any(np.real(eig) > 0):
            flags.append("UNSTABLE: an eigenvalue has a positive real part")
        if np.any(np.abs(np.real(eig)) > 100.0):
            flags.append("FAST: an eigenvalue faster than 100 rad/s (time constant under 0.01 s)")
    print("instantaneous sensitivities (rows P, Q; columns V, theta):")
    print(np.array2string(D, precision=4))
    print("flags:", flags if flags else "none")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    sys.exit(main(sys.argv[1], sys.argv[2]))
