"""Open-loop replay: drive a terminal model with measured V, theta and return its P, Q.

Integration is implicit trapezoid on the data grid (the recordings' own sample period).
Newton iterations reuse a
finite-difference Jacobian until convergence slows, then refresh it. Inputs are only needed on
the grid points, so there is no interpolation of V or theta.

A model "fails" (ReplayFailure) on: non-finite values, Newton not converging after a Jacobian
refresh, states or outputs beyond a bound, or the wall-clock budget running out.
"""
import time
import numpy as np


class ReplayFailure(Exception):
    def __init__(self, kind, detail=""):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


def _jac(f, t, x, u, fx, eps=1e-7):
    n = x.size
    J = np.empty((n, n))
    for i in range(n):
        h = eps * max(1.0, abs(x[i]))
        xp = x.copy()
        xp[i] += h
        J[:, i] = (f(t, xp, u) - fx) / h
    return J


def replay(model, t, U, y0, meta=None, x0=None, timeout_s=120.0, y_bound=50.0, x_bound=1e6,
           newton_tol=1e-10, max_newton=8):
    """Return (Y, X): outputs (n_t x 2) and states (n_t x n_x) on the grid t.

    model: object with init(u0, y0, meta), rhs(t, x, u), output(t, x, u)
    t: uniform-ish time grid (s); U: n_t x 2 inputs [V, theta]; y0: [P0, Q0] first sample
    """
    t0_wall = time.monotonic()
    t = np.asarray(t, float)
    U = np.asarray(U, float)

    def f(tt, x, u):
        dx = np.asarray(model.rhs(tt, x, u), float).ravel()
        if dx.shape != x.shape:
            raise ReplayFailure("crash", f"rhs returned shape {dx.shape}, expected {x.shape}")
        return dx

    def g(tt, x, u):
        y = np.asarray(model.output(tt, x, u), float).ravel()
        if y.shape != (2,):
            raise ReplayFailure("crash", f"output returned shape {y.shape}, expected (2,)")
        return y

    x = np.asarray(model.init(U[0], np.asarray(y0, float), meta or {}) if x0 is None else x0,
                   float).ravel().copy()
    if not np.all(np.isfinite(x)):
        raise ReplayFailure("nan", "init returned a non-finite state")
    n_t, n_x = t.size, x.size
    X = np.empty((n_t, n_x))
    Y = np.empty((n_t, 2))
    X[0] = x
    Y[0] = g(t[0], x, U[0])
    if n_x == 0:                                         # purely algebraic model
        for k in range(1, n_t):
            Y[k] = g(t[k], x, U[k])
        if not np.all(np.isfinite(Y)):
            raise ReplayFailure("nan", "non-finite output")
        if np.max(np.abs(Y)) > y_bound:
            raise ReplayFailure("unstable", f"|P| or |Q| > {y_bound:g} pu")
        return Y, X
    fx = f(t[0], x, U[0])
    J = None
    I = np.eye(n_x)

    for k in range(1, n_t):
        if (k & 255) == 0 and time.monotonic() - t0_wall > timeout_s:
            raise ReplayFailure("timeout", f"at t={t[k]:.3f} s after {timeout_s:.0f} s wall clock")
        h = t[k] - t[k - 1]
        uk = U[k]
        xn = x + h * fx                                  # explicit Euler predictor
        refreshed = False
        while True:
            if J is None:
                J = _jac(f, t[k], xn, uk, f(t[k], xn, uk))
                M = np.linalg.inv(I - 0.5 * h * J) if np.all(np.isfinite(J)) else None
                if M is None:
                    raise ReplayFailure("nan", f"non-finite Jacobian at t={t[k]:.4f} s")
            ok = False
            for it in range(max_newton):
                fn = f(t[k], xn, uk)
                r = xn - x - 0.5 * h * (fx + fn)
                if not np.all(np.isfinite(r)):
                    break
                dx = M @ r
                xn = xn - dx
                if np.max(np.abs(dx)) <= newton_tol * (1.0 + np.max(np.abs(xn))):
                    ok = True
                    break
            if ok:
                if it >= 3:
                    J = None                             # slow: refresh next step
                break
            if refreshed:
                raise ReplayFailure("diverged", f"Newton failed at t={t[k]:.4f} s")
            J, refreshed = None, True
            xn = x + h * fx
        x = xn
        fx = f(t[k], x, uk)
        if not (np.all(np.isfinite(x)) and np.all(np.isfinite(fx))):
            raise ReplayFailure("nan", f"non-finite state at t={t[k]:.4f} s")
        if np.max(np.abs(x)) > x_bound:
            raise ReplayFailure("unstable", f"|x| > {x_bound:g} at t={t[k]:.4f} s")
        X[k] = x
        Y[k] = g(t[k], x, uk)
        if not np.all(np.isfinite(Y[k])):
            raise ReplayFailure("nan", f"non-finite output at t={t[k]:.4f} s")
        if np.max(np.abs(Y[k])) > y_bound:
            raise ReplayFailure("unstable", f"|P| or |Q| > {y_bound:g} pu at t={t[k]:.4f} s")
    return Y, X
