"""Linear screen of a submission before you submit it. Prints the eigenvalues of the model's linearization at
the operating point of a recording, the fastest time constant, and the steady-state gains from V and theta to
P and Q (with the internal states settled). Flags anything that would likely destabilize the grid.

    python tools/linear_screen.py submission.json val/<file>.csv

Reading the output:
- Any eigenvalue with real part > 0 is an unstable model. Reject it.
- A time constant under 5 ms (eigenvalue real part below -200 /s) is a warning: the model reacts faster than
  the device's measured dynamics, and it often fails closed loop.
- Steady-state dQ/dV should be negative for a reactive droop. A positive value is a warning: a positive
  instantaneous voltage path into Q is a known cause of grid instability. Only keep it if the data strongly
  require it and the eigenvalues stay stable.
- Steady-state dP/dtheta should be a small, finite value. A large value means the frequency path is too stiff.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                   # noqa: E402
import pandas as pd                                  # noqa: E402
import submission_parser                             # noqa: E402


def screen(submission_path, csv_path):
    model = submission_parser.load_submission(submission_path)
    recording = pd.read_csv(csv_path)
    if "run_id" in recording:
        recording = next(rows for _, rows in recording.groupby("run_id"))
    first = recording.iloc[0]
    operating_point = [float(first["voltage_pu"]), float(first["bus_angle_rad"]),
                       float(first["active_power_pu"]), float(first["reactive_power_pu"])]
    lin = model.linearize(operating_point)
    A, B, C, D = lin["A"], lin["B"], lin["C"], lin["D"]
    print(f"init residual {lin['init_residual']:.2e}, output mismatch {lin['init_output_mismatch']:.2e}")
    warnings = []
    if A.size:
        eig = np.linalg.eigvals(A)
        print("eigenvalues (1/s):", np.round(np.sort_complex(eig), 3).tolist())
        if np.max(eig.real) > 0:
            warnings.append("UNSTABLE: an eigenvalue has positive real part")
        fast = [abs(e.real) for e in eig if abs(e.real) > 0]
        if fast and max(fast) > 200:
            warnings.append(f"fast mode: time constant {1 / max(fast) * 1000:.2f} ms (under 5 ms)")
        try:
            x_ss = -np.linalg.solve(A, B)
            G = D + C @ x_ss
            print(f"steady state: dP/dV {G[0,0]:.4f}  dP/dtheta {G[0,1]:.4f}  "
                  f"dQ/dV {G[1,0]:.4f}  dQ/dtheta {G[1,1]:.4f}")
            if G[1, 0] > 0:
                warnings.append("dQ/dV steady-state is positive")
        except np.linalg.LinAlgError:
            warnings.append("A is singular: no unique steady state")
    else:
        D_ss = D
        print(f"algebraic model: dP/dV {D_ss[0,0]:.4f} dP/dtheta {D_ss[0,1]:.4f} "
              f"dQ/dV {D_ss[1,0]:.4f} dQ/dtheta {D_ss[1,1]:.4f}")
        if D_ss[1, 0] > 0:
            warnings.append("dQ/dV is positive")
    for warning in warnings:
        print("WARNING:", warning)
    print("screen result:", "FLAGGED" if warnings else "clean")
    return 1 if any(w.startswith("UNSTABLE") for w in warnings) else 0


if __name__ == "__main__":
    sys.exit(screen(*sys.argv[1:3]))
