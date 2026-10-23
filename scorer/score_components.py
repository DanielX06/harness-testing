"""The three score components and how each is normalized. Pure numpy; never runs submission code.

Every component is an error normalized so that a flat prediction (P and Q frozen at their t = 0 values,
no response to anything) scores 1.0 and a perfect model 0.0. Each is capped at COMPONENT_CAP, so a model
that runs but is wildly wrong never scores worse than one that failed (FAILURE_SCORE).
"""
import numpy as np

COMPONENT_CAP = 2.0
FAILURE_SCORE = 2.0

# the four entries of the 2x2 frequency response: (output, input)
FREQUENCY_RESPONSE_ENTRIES = (("P", "V"), ("P", "theta"), ("Q", "V"), ("Q", "theta"))


# ---- time domain (TD) ------------------------------------------------------------------------------------
def time_domain_error(predicted, recorded, noise_sigmas, floor_in_sigmas=3.0):
    """Per channel: RMSE(predicted - recorded) / max(RMSE(flat - recorded), floor_in_sigmas * sigma), capped.

    predicted, recorded: n_samples x 2 arrays (P, Q). noise_sigmas: (sigma_P, sigma_Q). The floor keeps a
    channel that barely moves in a run from dividing by almost nothing and dominating the score."""
    predicted, recorded = np.asarray(predicted, float), np.asarray(recorded, float)
    flat_rmse = np.sqrt(np.mean((recorded - recorded[0]) ** 2, axis=0))
    denominator = np.maximum(flat_rmse, floor_in_sigmas * np.asarray(noise_sigmas, float))
    rmse = np.sqrt(np.mean((predicted - recorded) ** 2, axis=0))
    return {"P": float(min(rmse[0] / denominator[0], COMPONENT_CAP)),
            "Q": float(min(rmse[1] / denominator[1], COMPONENT_CAP)),
            "rmse_P": float(rmse[0]), "rmse_Q": float(rmse[1]),
            "flat_rmse_P": float(flat_rmse[0]), "flat_rmse_Q": float(flat_rmse[1]),
            "floor_active_P": bool(flat_rmse[0] < denominator[0]), "floor_active_Q": bool(flat_rmse[1] < denominator[1])}


# ---- frequency response (FR) -----------------------------------------------------------------------------
def frequency_response(A, B, C, D, frequencies_hz):
    """G(j w) = C (j w I - A)^-1 B + D at each frequency: an n_f x 2 x 2 array, rows (P, Q), columns (V, theta)."""
    A, B, C, D = (np.atleast_2d(np.asarray(matrix, float)) for matrix in (A, B, C, D))
    state_count = A.shape[0] if A.size else 0
    response = np.empty((len(frequencies_hz), 2, 2), complex)
    for k, frequency in enumerate(frequencies_hz):
        if state_count == 0:
            response[k] = D
        else:
            response[k] = C @ np.linalg.solve(2j * np.pi * frequency * np.eye(state_count) - A, B) + D
    return response


def frequency_response_error(response, true_response, floor_fraction=0.1):
    """Per entry: the pointwise relative error |G - G_true| / max(|G_true|, floor), averaged over the
    log-spaced frequencies, divided by the same average for G = 0 (so a model with no response scores 1).
    Every frequency and every entry counts equally, so the Q-V behaviour cannot hide behind a large
    P-theta entry. Returns each entry ("P/V", ...) and their "mean"."""
    errors = {}
    for (row, column), (output, input_name) in zip(np.ndindex(2, 2), FREQUENCY_RESPONSE_ENTRIES):
        true_entry, entry = true_response[:, row, column], response[:, row, column]
        floor = floor_fraction * np.sqrt(np.mean(np.abs(true_entry) ** 2)) + 1e-300
        denominator = np.maximum(np.abs(true_entry), floor)
        model_error = np.mean(np.abs(entry - true_entry) / denominator)
        zero_model_error = np.mean(np.abs(true_entry) / denominator)
        errors[f"{output}/{input_name}"] = (float(min(model_error / zero_model_error, COMPONENT_CAP))
                                            if zero_model_error > 0 else 0.0)
    errors["mean"] = float(np.mean([errors[f"{output}/{input_name}"] for output, input_name in FREQUENCY_RESPONSE_ENTRIES]))
    return errors


# ---- droops (PAR) ----------------------------------------------------------------------------------------
def droop_gains(A, B, C, D, lowest_frequency_hz=1e-4):
    """Steady-state droop gains of a terminal model, from its linearization at the operating point.

    freq: dP/d(omega) [pu per rad/s] = lim G_P,theta(j w) / (j w)   (a slow theta ramp is a frequency)
    volt: dQ/dV       [pu per pu]    = lim G_Q,V(j w)
    Each is evaluated at lowest_frequency_hz and at a tenth of it. If the two differ by more than 1%, the
    limit has not converged (for example an integrator with no droop) and that gain is None.
    Returns (gains, relative change between the two frequencies)."""
    values = []
    for frequency in (lowest_frequency_hz, lowest_frequency_hz / 10):
        omega = 2 * np.pi * frequency
        response = frequency_response(A, B, C, D, [frequency])[0]
        values.append({"freq": (response[0, 1] / (1j * omega)).real, "volt": response[1, 0].real})
    gains, convergence = {}, {}
    for kind in ("freq", "volt"):
        first, second = values[0][kind], values[1][kind]
        both_finite = np.isfinite(first) and np.isfinite(second)
        converged = both_finite and abs(first - second) <= 0.01 * max(abs(first), abs(second), 1e-12)
        gains[kind] = float(second) if converged else None
        convergence[kind] = (float(abs(first - second) / max(abs(first), abs(second), 1e-12)) if both_finite else None)
    return gains, convergence


def droop_error(gains, true_gains):
    """Relative error of each droop gain, capped; a missing gain scores the cap and a zero gain scores 1."""
    errors = {}
    for kind in ("freq", "volt"):
        true_gain, gain = true_gains[kind], gains.get(kind)
        errors[kind] = (COMPONENT_CAP if gain is None or not np.isfinite(gain)
                        else float(min(abs(gain - true_gain) / abs(true_gain), COMPONENT_CAP)))
    errors["mean"] = float(np.mean([errors["freq"], errors["volt"]]))
    return errors


def droops_as_operators_read_them(gains, nominal_frequency_hz=60.0):
    """The gains as the droops an operator quotes (device base): rad/s per pu P and %, pu V per pu Q and %."""
    nominal_omega = 2 * np.pi * nominal_frequency_hz
    readable = {}
    if gains.get("freq"):
        droop = -1.0 / gains["freq"]                    # rad/s per pu P (positive for a droop)
        readable["P_f_droop_rad_s_per_pu"] = droop
        readable["P_f_droop_percent"] = 100 * droop / nominal_omega
    if gains.get("volt"):
        droop = -1.0 / gains["volt"]                    # pu V per pu Q
        readable["Q_V_droop_pu_per_pu"] = droop
        readable["Q_V_droop_percent"] = 100 * droop
    return readable
