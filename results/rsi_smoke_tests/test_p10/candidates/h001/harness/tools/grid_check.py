"""Linear closed-loop check of a submission against a stiff source behind a reactance.

Command line:
    python tools/grid_check.py submission.json val/<file>.csv [X1 X2 ...]

The operating point (V0, P0, Q0) is read from the first row of the CSV. For each reactance X
(in pu on the device rating; default 0.1 0.3 0.6 1.0) the script:
  1. places a constant voltage E behind X so that the device's (P0, Q0) is the flow at its terminal;
  2. linearizes the model at that point (inputs V and theta, Vset held);
  3. closes the loop: the network takes P, Q from the device as a function of (V, theta), and the
     closed-loop state matrix is A + B (Jn - D)^-1 C;
  4. prints the closed-loop poles and flags UNSTABLE, MARGINAL, LIGHTLY DAMPED and FAST ones.
It also prints the open-loop static gains dP/dV, dP/dtheta, dQ/dV, dQ/dtheta at fixed Vset.
This is a linear proxy at one operating point. Passing it is necessary, not sufficient.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import symbolic  # noqa: E402

DEFAULT_X = [0.1, 0.3, 0.6, 1.0]
FAST_RAD_S = 500.0


def operating_point(csv):
    import pandas as pd
    r = pd.read_csv(csv).iloc[0]
    return float(r["voltage_pu"]), float(r["active_power_pu"]), float(r["reactive_power_pu"])


def source_behind_reactance(V0, P0, Q0, X):
    """Constant source E and angle phi0 such that the terminal flow equals (P0, Q0).

    Terminal flow into a source E (angle 0) behind X: P = V E sin(phi)/X, Q = (V^2 - V E cos(phi))/X.
    """
    a = V0 ** 2 - Q0 * X
    b = P0 * X
    E = float(np.hypot(a, b)) / V0
    phi0 = float(np.arctan2(b, a))
    return E, phi0


def network_jacobian(V, th, E, X):
    """Jacobian of the network's (P, Q) demand with respect to (V, theta)."""
    s, c = np.sin(th), np.cos(th)
    return np.array([[E * s / X, V * E * c / X],
                     [(2 * V - E * c) / X, V * E * s / X]])


def pole_flags(lam):
    re, mag = lam.real, abs(lam)
    flags = []
    if re > 1e-9:
        flags.append("UNSTABLE")
    elif re >= -1e-9:
        flags.append("MARGINAL(zero pole or undamped)")
    elif -re / mag < 0.05:
        flags.append("LIGHTLY DAMPED")
    if mag > FAST_RAD_S:
        flags.append("FAST(time constant < 2 ms)")
    return flags


def report_static(A, B, C, D, out):
    n = A.shape[0]
    if n == 0:
        G = D
    else:
        try:
            G = D - C @ np.linalg.solve(A, B)
        except np.linalg.LinAlgError:
            out("open-loop static gains: undefined, A is singular (a pure integrator with no "
                "proportional path).")
            return
    out(f"open-loop static gains at fixed Vset: dP/dV={G[0, 0]:.4g}  dP/dtheta={G[0, 1]:.4g}  "
        f"dQ/dV={G[1, 0]:.4g}  dQ/dtheta={G[1, 1]:.4g}")
    if G[1, 0] > 0:
        out("  WARNING: dQ/dV > 0. Q rising with V is positive voltage feedback; a reactive droop "
            "makes it negative.")


def analyse(m, V0, P0, Q0, Xs, out=print):
    unstable_at = []
    for k, X in enumerate(Xs):
        E, phi0 = source_behind_reactance(V0, P0, Q0, X)
        lin = m.linearize([V0, phi0, P0, Q0])
        A, B, C, D = lin["A"], lin["B"], lin["C"], lin["D"]
        n = A.shape[0]
        if k == 0:
            report_static(A, B, C, D, out)
        if n == 0:
            out(f"X={X:g}: model has no states; nothing to close.")
            continue
        try:
            K = np.linalg.solve(network_jacobian(V0, phi0, E, X) - D, C)
        except np.linalg.LinAlgError:
            out(f"X={X:g}: network and device Jacobians cancel; the loop cannot be closed here.")
            continue
        lams = sorted(np.linalg.eigvals(A + B @ K), key=lambda z: -z.real)
        out(f"X={X:g} pu (source E={E:.4f}, angle {phi0:.4f} rad): closed-loop poles, most unstable first")
        flagged = False
        for lam in lams[:12]:
            fl = pole_flags(lam)
            zeta = -lam.real / abs(lam) if abs(lam) > 0 else 0.0
            out(f"   {lam.real:+.4g} {lam.imag:+.4g}j  |w|={abs(lam):.4g} rad/s  zeta={zeta:.3f}  "
                f"{' '.join(fl)}")
            if "UNSTABLE" in fl:
                flagged = True
        if flagged:
            unstable_at.append(X)
    if unstable_at:
        out(f"VERDICT: UNSTABLE in the closed loop at X = {unstable_at}. Fix this before submitting.")
    else:
        out("VERDICT: no unstable closed-loop pole at the tested X values. Read the FLAG column too.")
    return unstable_at


def report(m, csv, Xs=None, out=print):
    V0, P0, Q0 = operating_point(csv)
    out(f"grid check at V0={V0:.4f} P0={P0:.4f} Q0={Q0:.4f} ({os.path.basename(csv)})")
    return analyse(m, V0, P0, Q0, list(Xs) if Xs else DEFAULT_X, out)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    try:
        model = symbolic.load(sys.argv[1])
    except symbolic.SubmissionError as e:
        print(f"INVALID: {e}")
        sys.exit(1)
    Xs = [float(x) for x in sys.argv[3:]] or DEFAULT_X
    report(model, sys.argv[2], Xs)
