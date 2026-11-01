"""Open-loop replay: drive a terminal model with measured V and theta (and the logged Vset) and return the
P and Q it produces.

Integration is implicit trapezoid on the recording's own time grid, so the inputs are only needed at the
recorded samples and nothing is interpolated. Newton iterations reuse a finite-difference Jacobian until
convergence slows, then refresh it.

A replay fails (ReplayFailure) on non-finite values, Newton not converging after a Jacobian refresh, states
or outputs beyond a bound, or the wall-clock limit running out.
"""
import time

import numpy as np


class ReplayFailure(Exception):
    def __init__(self, kind, detail=""):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


def _finite_difference_jacobian(derivative, time_now, state, inputs, derivative_at_state, step=1e-7):
    size = state.size
    jacobian = np.empty((size, size))
    for column in range(size):
        increment = step * max(1.0, abs(state[column]))
        nudged = state.copy()
        nudged[column] += increment
        jacobian[:, column] = (derivative(time_now, nudged, inputs) - derivative_at_state) / increment
    return jacobian


def replay_open_loop(model, times, inputs, initial_state=None, time_limit_s=120.0, output_bound=50.0,
                     state_bound=1e6, newton_tolerance=1e-10, max_newton_iterations=8):
    """Return (outputs, states): outputs is n_samples x 2 (P, Q), states n_samples x n_states.

    model: has initial_state(), state_derivative(t, state, inputs) and outputs(t, state, inputs), such as
           submission_parser.TerminalModel(...).bind(operating_point)
    times: the recording's time column (s); inputs: n_samples x 2 ([V, theta]) or x 3 ([V, theta, Vset])
    """
    wall_clock_start = time.monotonic()
    times = np.asarray(times, float)
    inputs = np.asarray(inputs, float)

    def derivative(time_now, state, sample_inputs):
        rates = np.asarray(model.state_derivative(time_now, state, sample_inputs), float).ravel()
        if rates.shape != state.shape:
            raise ReplayFailure("crash", f"rhs returned shape {rates.shape}, expected {state.shape}")
        return rates

    def outputs_at(time_now, state, sample_inputs):
        values = np.asarray(model.outputs(time_now, state, sample_inputs), float).ravel()
        if values.shape != (2,):
            raise ReplayFailure("crash", f"output returned shape {values.shape}, expected (2,)")
        return values

    state = np.asarray(model.initial_state() if initial_state is None else initial_state, float).ravel().copy()
    if not np.all(np.isfinite(state)):
        raise ReplayFailure("nan", "init returned a non-finite state")
    sample_count, state_count = times.size, state.size
    states = np.empty((sample_count, state_count))
    outputs = np.empty((sample_count, 2))
    states[0] = state
    outputs[0] = outputs_at(times[0], state, inputs[0])
    if state_count == 0:                                # a purely algebraic model
        for k in range(1, sample_count):
            outputs[k] = outputs_at(times[k], state, inputs[k])
        if not np.all(np.isfinite(outputs)):
            raise ReplayFailure("nan", "non-finite output")
        if np.max(np.abs(outputs)) > output_bound:
            raise ReplayFailure("unstable", f"|P| or |Q| > {output_bound:g} pu")
        return outputs, states
    rates = derivative(times[0], state, inputs[0])
    jacobian = None
    identity = np.eye(state_count)

    for k in range(1, sample_count):
        if (k & 255) == 0 and time.monotonic() - wall_clock_start > time_limit_s:
            raise ReplayFailure("timeout", f"at t={times[k]:.3f} s after {time_limit_s:.0f} s wall clock")
        step = times[k] - times[k - 1]
        sample_inputs = inputs[k]
        guess = state + step * rates                     # explicit Euler predictor
        refreshed = False
        while True:
            if jacobian is None:
                jacobian = _finite_difference_jacobian(derivative, times[k], guess, sample_inputs,
                                                       derivative(times[k], guess, sample_inputs))
                newton_matrix = (np.linalg.inv(identity - 0.5 * step * jacobian) if np.all(np.isfinite(jacobian))
                                 else None)
                if newton_matrix is None:
                    raise ReplayFailure("nan", f"non-finite Jacobian at t={times[k]:.4f} s")
            converged = False
            for iteration in range(max_newton_iterations):
                residual = guess - state - 0.5 * step * (rates + derivative(times[k], guess, sample_inputs))
                if not np.all(np.isfinite(residual)):
                    break
                correction = newton_matrix @ residual
                guess = guess - correction
                if np.max(np.abs(correction)) <= newton_tolerance * (1.0 + np.max(np.abs(guess))):
                    converged = True
                    break
            if converged:
                if iteration >= 3:
                    jacobian = None                     # converging slowly: refresh the Jacobian next step
                break
            if refreshed:
                raise ReplayFailure("diverged", f"Newton failed at t={times[k]:.4f} s")
            jacobian, refreshed = None, True
            guess = state + step * rates
        state = guess
        rates = derivative(times[k], state, sample_inputs)
        if not (np.all(np.isfinite(state)) and np.all(np.isfinite(rates))):
            raise ReplayFailure("nan", f"non-finite state at t={times[k]:.4f} s")
        if np.max(np.abs(state)) > state_bound:
            raise ReplayFailure("unstable", f"|x| > {state_bound:g} at t={times[k]:.4f} s")
        states[k] = state
        outputs[k] = outputs_at(times[k], state, sample_inputs)
        if not np.all(np.isfinite(outputs[k])):
            raise ReplayFailure("nan", f"non-finite output at t={times[k]:.4f} s")
        if np.max(np.abs(outputs[k])) > output_bound:
            raise ReplayFailure("unstable", f"|P| or |Q| > {output_bound:g} pu at t={times[k]:.4f} s")
    return outputs, states
