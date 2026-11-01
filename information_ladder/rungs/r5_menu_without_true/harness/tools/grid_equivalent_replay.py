"""Grid-equivalent replay: run a terminal model against a Thevenin equivalent of the grid instead of the
measured terminal voltage.

The open-loop replay in check_submission.py holds V and theta at their measured values, so the model's own
P and Q never move them. A device whose control is only damped through the network impedance can then
diverge even when the model is right. Here the grid is a voltage source E(t) behind a reactance X:

    V e^{j theta} = E(t) + j X I,        I = conj((P + j Q) / (V e^{j theta}))     (I injected by the device)

E(t) is backed out of the recording itself, E = V e^{j theta} - j X I_measured, so a model that reproduces
the measured P and Q also reproduces the measured V and theta, for any X. A model that injects different
P and Q pulls V and theta away from the recording through X, the way the real grid would at short time
scales. Slow grid behaviour (governors, exciters, the other machines swinging) is frozen into E(t), so
treat this as a closer check than open-loop replay, not as the score.

    python tools/grid_equivalent_replay.py submission.json val/<file>.csv [--x 0.5] [--every 1] [--plot out.png]

X is in pu on the device rating. --every N uses every Nth sample (faster, less accurate for fast dynamics).
Integration is implicit trapezoid for the states with the network equation solved at every step (Newton on
states, V and theta together).
"""
import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402

DEFAULT_REACTANCE = 0.5


class ReplayFailure(Exception):
    def __init__(self, kind, detail=""):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


def thevenin_source(voltage, angle, active_power, reactive_power, reactance):
    """E(t) behind jX that makes the recorded terminal quantities consistent: E = V e^{j theta} - j X I."""
    terminal = voltage * np.exp(1j * angle)
    current = np.conj((active_power + 1j * reactive_power) / terminal)
    return terminal - 1j * reactance * current


def replay_against_grid_equivalent(model, times, source, setpoint, reactance, initial_terminal, time_limit_s=110.0,
                                   newton_tolerance=1e-9, max_newton_iterations=10, output_bound=50.0,
                                   state_bound=1e6):
    """Returns (P, Q, V, theta, states), each one row per sample.

    model: a submission_parser BoundTerminalModel (TerminalModel(...).bind(operating_point))
    source: complex E(t) per sample; setpoint: Vset per sample; initial_terminal: (V0, theta0)
    """
    started = time.monotonic()
    times = np.asarray(times, float)
    count = times.size
    derivative_function, output_function, _, _ = model.model.numeric_functions()
    point, params = model.operating_point, model.param_values
    state = np.asarray(model.initial_state(), float).ravel().copy()
    n = state.size
    if not np.all(np.isfinite(state)):
        raise ReplayFailure("nan", "init returned a non-finite state")

    def rates(x, inputs):
        if n == 0:
            return np.zeros(0)
        return np.array(derivative_function(list(x), inputs, point, params), dtype=float).ravel()

    def residual_parts(x, v, th, vset, e):
        """(network mismatch real, imag) and the outputs, for the unknowns at one sample."""
        inputs = [v, th, vset]
        p, q = output_function(list(x), inputs, point, params)
        terminal = complex(v * math.cos(th), v * math.sin(th))
        current = (complex(p, q) / terminal).conjugate()
        mismatch = terminal - e - 1j * reactance * current
        return mismatch.real, mismatch.imag, float(p), float(q)

    voltage, angle = float(initial_terminal[0]), float(initial_terminal[1])
    out_p, out_q = np.empty(count), np.empty(count)
    out_v, out_theta = np.empty(count), np.empty(count)
    out_states = np.empty((count, n))
    _, _, out_p[0], out_q[0] = residual_parts(state, voltage, angle, setpoint[0], source[0])
    out_v[0], out_theta[0], out_states[0] = voltage, angle, state
    previous_rates = rates(state, [voltage, angle, setpoint[0]])
    jacobian_inverse = None
    residual_vector = np.empty(n + 2)

    for k in range(1, count):
        if (k & 255) == 0 and time.monotonic() - started > time_limit_s:
            raise ReplayFailure("timeout", f"at t={times[k]:.3f} s after {time_limit_s:.0f} s wall clock")
        half_step = 0.5 * (times[k] - times[k - 1])
        vset, e = float(setpoint[k]), complex(source[k])
        anchor = state + half_step * previous_rates

        def residual(unknowns):
            x, v, th = unknowns[:n], unknowns[n], unknowns[n + 1]
            residual_vector[:n] = x - anchor - half_step * rates(x, [v, th, vset])
            residual_vector[n], residual_vector[n + 1], _, _ = residual_parts(x, v, th, vset, e)
            return residual_vector.copy()

        guess = np.concatenate([state + 2 * half_step * previous_rates, [voltage, angle]])
        refreshed = False
        while True:
            if jacobian_inverse is None:
                base = residual(guess)
                jacobian = np.empty((n + 2, n + 2))
                for column in range(n + 2):
                    increment = 1e-7 * max(1.0, abs(guess[column]))
                    nudged = guess.copy()
                    nudged[column] += increment
                    jacobian[:, column] = (residual(nudged) - base) / increment
                if not np.all(np.isfinite(jacobian)):
                    raise ReplayFailure("nan", f"non-finite Jacobian at t={times[k]:.4f} s")
                try:
                    jacobian_inverse = np.linalg.inv(jacobian)
                except np.linalg.LinAlgError:
                    raise ReplayFailure("singular", f"singular Jacobian at t={times[k]:.4f} s")
            converged = False
            for iteration in range(max_newton_iterations):
                value = residual(guess)
                if not np.isfinite(value).all():
                    break
                correction = jacobian_inverse @ value
                guess -= correction
                if np.abs(correction).max() <= newton_tolerance * (1.0 + np.abs(guess).max()):
                    converged = True
                    break
            if converged:
                if iteration >= 3:
                    jacobian_inverse = None
                break
            if refreshed:
                raise ReplayFailure("diverged", f"Newton failed at t={times[k]:.4f} s")
            jacobian_inverse, refreshed = None, True
            guess = np.concatenate([state + 2 * half_step * previous_rates, [voltage, angle]])
        state, voltage, angle = guess[:n], float(guess[n]), float(guess[n + 1])
        previous_rates = rates(state, [voltage, angle, vset])
        _, _, p, q = residual_parts(state, voltage, angle, vset, e)
        if not (np.isfinite(previous_rates).all() and math.isfinite(p) and math.isfinite(q)):
            raise ReplayFailure("nan", f"non-finite value at t={times[k]:.4f} s")
        if (n and np.abs(state).max() > state_bound) or max(abs(p), abs(q)) > output_bound or not 0.05 < voltage < 3:
            raise ReplayFailure("unstable", f"model ran away at t={times[k]:.4f} s")
        out_p[k], out_q[k], out_v[k], out_theta[k], out_states[k] = p, q, voltage, angle, state
    return out_p, out_q, out_v, out_theta, out_states


def replay_recording(model, recording, reactance=DEFAULT_REACTANCE, every=1, time_limit_s=110.0):
    """Replay one recording (a pandas table with the standard columns). Returns a dict of arrays and RMSEs."""
    table = recording.iloc[::every] if every > 1 else recording
    times = table["time_s"].to_numpy(float)
    voltage = table["voltage_pu"].to_numpy(float)
    angle = table["bus_angle_rad"].to_numpy(float)
    active, reactive = table["active_power_pu"].to_numpy(float), table["reactive_power_pu"].to_numpy(float)
    setpoint = (table["voltage_setpoint_pu"].to_numpy(float) if "voltage_setpoint_pu" in table
                else np.full(times.size, voltage[0]))
    source = thevenin_source(voltage, angle, active, reactive, reactance)
    operating_point = [voltage[0], angle[0], active[0], reactive[0]]
    p, q, v, th, states = replay_against_grid_equivalent(model.bind(operating_point), times, source, setpoint,
                                                         reactance, (voltage[0], angle[0]), time_limit_s)
    def rmse(a, b):
        return float(np.sqrt(np.mean((a - b) ** 2)))
    return {"times": times, "P": p, "Q": q, "V": v, "theta": th, "states": states,
            "rmse": {"P": rmse(p, active), "Q": rmse(q, reactive), "V": rmse(v, voltage), "theta": rmse(th, angle)},
            "flat": {"P": rmse(active, active[0]), "Q": rmse(reactive, reactive[0]),
                     "V": rmse(voltage, voltage[0]), "theta": rmse(angle, angle[0])},
            "measured": {"P": active, "Q": reactive, "V": voltage, "theta": angle}}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Replay a recording with the model against a grid equivalent.")
    parser.add_argument("submission")
    parser.add_argument("csv")
    parser.add_argument("--x", type=float, default=DEFAULT_REACTANCE, help="grid reactance, pu on the device rating")
    parser.add_argument("--every", type=int, default=1, help="use every Nth sample")
    parser.add_argument("--plot", help="save a plot of measured and replayed P, Q, V, theta")
    options = parser.parse_args(argv)
    import pandas as pd
    import submission_parser
    try:
        model = submission_parser.load_submission(options.submission)
    except submission_parser.SubmissionError as error:
        print(f"INVALID: {error}")
        return 1
    recording = pd.read_csv(options.csv)
    try:
        result = replay_recording(model, recording, options.x, options.every)
    except ReplayFailure as failure:
        print(f"grid-equivalent replay failed: {failure}")
        return 0
    print(f"grid-equivalent replay (X = {options.x:g} pu), RMSE (flat in brackets):")
    for key in ("P", "Q", "V", "theta"):
        print(f"   {key:5s} {result['rmse'][key]:.2e}  ({result['flat'][key]:.2e})")
    if options.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        figure, axes = plt.subplots(4, 1, sharex=True, figsize=(10, 8))
        for axis, key in zip(axes, ("P", "Q", "V", "theta")):
            axis.plot(result["times"], result["measured"][key], lw=0.8, label="measured")
            axis.plot(result["times"], result[key], lw=0.8, label="model")
            axis.set_ylabel(key)
        axes[0].legend()
        figure.tight_layout()
        figure.savefig(options.plot, dpi=90)
        print(f"plot saved to {options.plot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
