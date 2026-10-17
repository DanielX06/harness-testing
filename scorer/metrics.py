"""Score components. Pure numpy, trusted side only (never runs submission code).

Every component is an error normalised so a flat prediction (P, Q frozen at their t=0 values,
no response to anything) scores 1.0 and a perfect model 0.0. Each is capped at CAP so a model
that runs but is wildly wrong can never score worse than one that crashed (FAIL = CAP).
"""
import numpy as np

CAP = 2.0
FAIL = 2.0


# ---- time domain --------------------------------------------------------------------------
def td_run_error(Y_pred, Y_true, sigma, floor_sigmas=3.0):
    """Per-channel RMSE(pred - true) / max(RMSE(flat - true), floor_sigmas*sigma), capped.

    Y_*: n_t x 2 (P, Q). sigma: (sigma_P, sigma_Q). The floor stops a channel that barely moves
    in a run from dividing by almost nothing and dominating the score."""
    Y_pred, Y_true = np.asarray(Y_pred, float), np.asarray(Y_true, float)
    flat = np.sqrt(np.mean((Y_true - Y_true[0]) ** 2, axis=0))
    den = np.maximum(flat, floor_sigmas * np.asarray(sigma, float))
    err = np.sqrt(np.mean((Y_pred - Y_true) ** 2, axis=0))
    return {"P": float(min(err[0] / den[0], CAP)), "Q": float(min(err[1] / den[1], CAP)),
            "rmse_P": float(err[0]), "rmse_Q": float(err[1]),
            "flat_rmse_P": float(flat[0]), "flat_rmse_Q": float(flat[1]),
            "floor_active_P": bool(flat[0] < den[0]), "floor_active_Q": bool(flat[1] < den[1])}


# ---- frequency response -------------------------------------------------------------------
def transfer(A, B, C, D, f):
    """G(j w) for each f (Hz): array n_f x 2 x 2, rows (P, Q), columns (V, theta)."""
    A, B, C, D = (np.atleast_2d(np.asarray(M, float)) for M in (A, B, C, D))
    n = A.shape[0] if A.size else 0
    G = np.empty((len(f), 2, 2), complex)
    for k, fk in enumerate(f):
        if n == 0:
            G[k] = D
        else:
            G[k] = C @ np.linalg.solve(2j * np.pi * fk * np.eye(n) - A, B) + D
    return G


ENTRIES = (("P", "V"), ("P", "theta"), ("Q", "V"), ("Q", "theta"))


def fr_error(G_sub, G_true, floor_frac=0.1):
    """Per-entry error of the 2x2 frequency response, normalised so G = 0 scores 1.0.

    Pointwise relative error |dG| / max(|G_true|, floor) averaged over the log-spaced grid, then
    divided by the same quantity for G = 0. Every frequency and every one of the four entries
    counts equally, so Q-V behaviour cannot hide behind a large P-theta entry."""
    out = {}
    for (i, j), (yo, ui) in zip(np.ndindex(2, 2), ENTRIES):
        gt, gs = G_true[:, i, j], G_sub[:, i, j]
        den = np.maximum(np.abs(gt), floor_frac * np.sqrt(np.mean(np.abs(gt) ** 2)) + 1e-300)
        e_sub = np.mean(np.abs(gs - gt) / den)
        e_flat = np.mean(np.abs(gt) / den)
        out[f"{yo}/{ui}"] = float(min(e_sub / e_flat, CAP)) if e_flat > 0 else 0.0
    out["mean"] = float(np.mean([out[f"{a}/{b}"] for a, b in ENTRIES]))
    return out


# ---- droop gains from the linearization ---------------------------------------------------
def droop_gains(A, B, C, D, f_lo=1e-4):
    """Steady-state droop gains of a terminal model from its linearization at the operating point.

    freq: dP/d(omega) [pu per rad/s] = lim G_P,theta(jw) / (jw)   (a slow theta ramp is a frequency)
    volt: dQ/dV       [pu per pu]    = lim G_Q,V(jw)
    Evaluated at f_lo and f_lo/10; if the two differ by more than 1% the limit has not converged
    (e.g. an integrator with no droop), and that gain is reported as None."""
    out, conv = {}, {}
    vals = []
    for f in (f_lo, f_lo / 10):
        w = 2 * np.pi * f
        G = transfer(A, B, C, D, [f])[0]
        vals.append({"freq": (G[0, 1] / (1j * w)).real, "volt": G[1, 0].real})
    for k in ("freq", "volt"):
        a, b = vals[0][k], vals[1][k]
        ok = np.isfinite(a) and np.isfinite(b) and abs(a - b) <= 0.01 * max(abs(a), abs(b), 1e-12)
        out[k] = float(b) if ok else None
        conv[k] = float(abs(a - b) / max(abs(a), abs(b), 1e-12)) if np.isfinite(a) and np.isfinite(b) else None
    return out, conv


def par_error(gains_sub, gains_true):
    """Relative error of each droop gain; a model with no response (gain 0) scores 1.0."""
    out = {}
    for k in ("freq", "volt"):
        gt, gs = gains_true[k], gains_sub.get(k)
        out[k] = CAP if gs is None or not np.isfinite(gs) else float(min(abs(gs - gt) / abs(gt), CAP))
    out["mean"] = float(np.mean([out["freq"], out["volt"]]))
    return out


def readable(gains, f_nom=60.0):
    """Droops in the form an operator reads them, from the measured gains (converter base)."""
    w0 = 2 * np.pi * f_nom
    r = {}
    if gains.get("freq"):
        R = -1.0 / gains["freq"]                     # rad/s per pu P (positive for a droop)
        r["P_f_droop_rad_s_per_pu"] = R
        r["P_f_droop_percent"] = 100 * R / w0
    if gains.get("volt"):
        R = -1.0 / gains["volt"]                     # pu V per pu Q
        r["Q_V_droop_pu_per_pu"] = R
        r["Q_V_droop_percent"] = 100 * R
    return r
