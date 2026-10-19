"""Closed-loop screen for a submission.

    python tools/screen.py submission.json val/<file>.csv

The CSV only supplies the operating point (its first row). The screen linearises the submission
there and prints:
  1. The device's own poles, and the fastest time constants.
  2. Static gains with Vset held: dP/dV, dQ/dV, dQ/dVset, and dP/dw at 0.1 Hz. The documented
     behaviour is voltage regulation by reactive-power droop (dQ/dV < 0 at fixed Vset) and
     active-power droop (dP/dw < 0). Wrong signs are the usual cause of closed-loop failure.
  3. Frequency response |H| of (V, theta, Vset) -> (P, Q) at 0.1, 1 and 10 Hz.
  4. Closed-loop poles with the device connected to a generic test network: a voltage source
     behind a reactance, with an inertial swing of the source (several reactances and inertias,
     plus an infinite bus). Any pole with Re >= 0 means the model destabilises that network.
This test network is only a generic stability probe. It is not the scoring grid.
Exit code 1 if any test network is unstable, otherwise 0.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                     # noqa: E402
import sympy as sp                     # noqa: E402
import symbolic                        # noqa: E402
from symbolic import OPPOINT           # noqa: E402

WB = 2 * np.pi * 60.0
PS0, QS0 = 1.0, 0.2                    # generic power carried by the test source (pu)
REACTANCES = [0.05, 0.2, 0.6]          # pu, generic test strengths
INERTIAS = [2.0, 6.0]                  # s, source inertia
DAMPING = 0.0                          # source damping (pu power per pu speed)


def op_from_csv(path):
    import pandas as pd
    df = pd.read_csv(path)
    if "run_id" in df:
        df = df[df["run_id"] == df["run_id"].iloc[0]]
    g = df.iloc[0]
    return [float(g["voltage_pu"]), float(g["bus_angle_rad"]),
            float(g["active_power_pu"]), float(g["reactive_power_pu"])]


def linearize3(m, op):
    """A, B, C, D with inputs (V, theta, Vset) at operating point op = V0, theta0, P0, Q0."""
    X = [m.sym[n] for n in m.state_names]
    U = [m.sym["V"], m.sym["theta"], m.sym["Vset"]]
    pt = {m.sym[k]: float(v) for k, v in zip(OPPOINT, op)}
    pt.update({m.sym[k]: float(v) for k, v in m.params.items()})
    x0 = [float(m.init[n].subs(pt)) for n in m.state_names]
    pt.update(dict(zip(X, x0)))
    pt.update({U[0]: float(op[0]), U[1]: float(op[1]), U[2]: float(op[0])})
    n = len(X)
    G = sp.Matrix([m.out["P"], m.out["Q"]])
    ev = lambda M, r, c: np.array(M.subs(pt).evalf(), dtype=float).reshape(r, c)
    if n == 0:
        return np.zeros(0), np.zeros((0, 0)), np.zeros((0, 3)), np.zeros((2, 0)), ev(G.jacobian(U), 2, 3)
    F = sp.Matrix([m.rhs[k] for k in m.state_names])
    A = ev(F.jacobian(X), n, n)
    B = ev(F.jacobian(U), n, 3)
    C = ev(G.jacobian(X), 2, n)
    D = ev(G.jacobian(U), 2, 3)
    return np.array(x0), A, B, C, D


def net(V, th, E, X):
    """Power (P, Q) that the test source delivers into the terminal node.
    V, th: terminal voltage magnitude and angle. E: complex source phasor. X: reactance."""
    Vt = V * np.exp(1j * th)
    I = (E - Vt) / (1j * X)
    S = Vt * np.conj(I)
    return np.array([S.real, S.imag])


def closed_loop(A, B, C, D, X, H, V0, th0, infinite=False):
    """Linear closed loop of the device with the test network. States: device x, then source
    angle and speed (omitted when infinite)."""
    n = A.shape[0]
    Vt0 = V0 * np.exp(1j * th0)
    I0 = np.conj((PS0 + 1j * QS0) / Vt0)
    E = Vt0 + 1j * X * I0              # complex source voltage at the operating point
    h = 1e-7
    rot = lambda ph: E * np.exp(1j * ph)
    Gz = np.zeros((2, 2))
    Gz[:, 0] = (net(V0 + h, th0, E, X) - net(V0 - h, th0, E, X)) / (2 * h)
    Gz[:, 1] = (net(V0, th0 + h, E, X) - net(V0, th0 - h, E, X)) / (2 * h)
    # derivative with respect to the source angle
    Gd = (net(V0, th0, rot(h), X) - net(V0, th0, rot(-h), X)) / (2 * h)
    B2, D2 = B[:, :2], D[:, :2]
    Minv = np.linalg.inv(D2 + Gz)
    Kx = -Minv @ C                     # z = Kx x + Kd ddelta
    Kd = -Minv @ Gd
    if infinite:
        return A + B2 @ Kx
    N = n + 2
    Acl = np.zeros((N, N))
    Acl[:n, :n] = A + B2 @ Kx
    Acl[:n, n] = B2 @ Kd
    Acl[n, n + 1] = WB
    pe_x = Gz[0] @ Kx
    pe_d = Gz[0] @ Kd + Gd[0]
    Acl[n + 1, :n] = -pe_x / (2 * H)
    Acl[n + 1, n] = -pe_d / (2 * H)
    Acl[n + 1, n + 1] = -DAMPING / (2 * H)
    return Acl


def damping_min(lam):
    zetas = [-l.real / abs(l) for l in lam if abs(l.imag) > 1e-6 and l.real < 0]
    return min(zetas) if zetas else None


def main(path, csv=None):
    try:
        m = symbolic.load(path)
    except symbolic.SubmissionError as e:
        print(f"INVALID: {e}")
        return 1
    if not csv:
        print("need a CSV to get the operating point")
        return 1
    op = op_from_csv(csv)
    V0, th0, P0, Q0 = op
    x0, A, B, C, D = linearize3(m, op)
    n = A.shape[0]
    warnings, unstable = [], []

    print(f"operating point V0={V0:.4f} theta0={th0:.3f} P0={P0:.4f} Q0={Q0:.4f}; states {m.state_names}")
    if n:
        lam = np.linalg.eigvals(A)
        lam = lam[np.argsort(-lam.real)]
        print("device poles (Re, Im) and time constants:")
        for l in lam:
            tau = 1 / abs(l.real) if abs(l.real) > 1e-12 else float("inf")
            print(f"   {l.real:+.4g} {l.imag:+.4g}j   tau={tau:.4g} s")
            if abs(l.real) > 1e-12 and tau < 0.002:
                warnings.append(f"fast pole tau={tau:.2g} s (below 2 ms; the grid integrator may struggle)")
        if np.max(lam.real) > 1e-9:
            warnings.append("device alone is unstable at this operating point")

    singular = n > 0 and np.min(np.abs(np.linalg.eigvals(A))) < 1e-9
    if n == 0 or not singular:
        K = D if n == 0 else D - C @ np.linalg.solve(A, B)
        print("static gains with Vset held (columns V, theta, Vset):")
        print(f"   dP: {np.array2string(K[0], precision=4)}")
        print(f"   dQ: {np.array2string(K[1], precision=4)}")
        if K[1, 0] >= 0:
            warnings.append(f"dQ/dV = {K[1,0]:+.3g} at fixed Vset: Q rises with V. Documented droop needs dQ/dV < 0. "
                            "Positive values are the usual cause of closed-loop failure.")
    else:
        print("integral action on a variable: no steady dQ/dV or dP/dw with Vset held")
        warnings.append("a state has integral action (zero pole). The documented reactive-power droop "
                        "needs a proportional voltage path with negative dQ/dV.")

    print("frequency response |H| from (V, theta, Vset) to (P, Q):")
    for f in [0.1, 1.0, 10.0]:
        w = 2 * np.pi * f
        Hs = D if n == 0 else C @ np.linalg.solve(1j * w * np.eye(n) - A, B) + D
        print(f"   {f:5.1f} Hz  |P/V|={abs(Hs[0,0]):.3g} |P/th|={abs(Hs[0,1]):.3g} |Q/V|={abs(Hs[1,0]):.3g} "
              f"|Q/th|={abs(Hs[1,1]):.3g} |Q/Vset|={abs(Hs[1,2]):.3g}")
    w = 2 * np.pi * 0.1
    Hpt = D[0, 1] if n == 0 else (C @ np.linalg.solve(1j * w * np.eye(n) - A, B) + D)[0, 1]
    dPdw = float(np.real(Hpt / (1j * w)) * WB)
    print(f"dP/dw (0.1 Hz, pu on rating per pu frequency) = {dPdw:+.4g}")
    if dPdw >= 0:
        warnings.append(f"dP/dw = {dPdw:+.3g}: P does not fall as frequency rises. "
                        "Documented active-power droop needs dP/dw < 0.")

    print("closed loop with a generic test network (source behind reactance, inertial swing):")
    for X in REACTANCES:
        for H in INERTIAS + [None]:
            tag = "inf-bus" if H is None else f"H={H:g}s"
            try:
                Acl = closed_loop(A, B, C, D, X, H if H else 1.0, V0, th0, infinite=H is None)
                lam = np.linalg.eigvals(Acl)
                wr = float(np.max(lam.real))
                zmin = damping_min(lam)
                zs = f"{zmin:.3f}" if zmin is not None else "n/a"
                print(f"   X={X:<5g} {tag:<8} max Re={wr:+.4g}  min damping={zs}")
                if wr > 1e-9:
                    unstable.append(f"X={X} {tag} max Re={wr:.3g}")
                elif zmin is not None and zmin < 0.02:
                    warnings.append(f"lightly damped closed loop (zeta={zmin:.3f}) at X={X} {tag}")
            except np.linalg.LinAlgError:
                unstable.append(f"X={X} {tag} singular closed loop")
                print(f"   X={X} {tag} singular closed loop")

    for w_ in warnings:
        print("WARNING:", w_)
    if unstable:
        print("SCREEN: UNSTABLE in " + "; ".join(unstable))
        return 1
    print("SCREEN: stable in all test networks" + (" (with warnings above)" if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
