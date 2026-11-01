"""The device's internal signals for a recording, reconstructed from its terminal measurements and the true
model (trusted side: the solver never sees this file, only the columns it writes).

The true device's controls form a feed-forward chain from the measured P and Q: two measurement filters,
two power loops, the frequency command and the internal angle that integrates it, and the inner voltage
reference. The internal-frame voltages then follow from V, theta and that angle, and the frame currents from
P and Q. So every signal here is an exact function of the recorded columns plus the true structure and
parameters, integrated with the trapezoid rule on the recording's own 1 ms grid. Nothing is simulated
closed loop, so the signals are consistent with the recorded P and Q to integration accuracy.

The signals are written in pu on the device rating (P, Q and currents) and rad or rad/s (angle, frequency).
The true model works on the 100 MVA system base; k = rating / system base converts.
"""
import math

import numpy as np

from scorer.truth.regf1_as_submission import DEFAULT_PARAMS

# column name -> what dataset.json says about it
DEVICE_LOG_COLUMNS = {
    "internal_angle_rad": "the device's internal angle reference, rad, on the same reference as bus_angle_rad "
                          "(equal to it at t = 0)",
    "internal_frequency_dev_rad_s": "the device's internal frequency command (rate of change of its internal "
                                    "angle), rad/s deviation from nominal",
}
INTERNAL_SIGNAL_COLUMNS = {
    **DEVICE_LOG_COLUMNS,
    "filtered_active_power_pu": "the device's filtered measurement of its own active power, pu on its rating",
    "filtered_reactive_power_pu": "the device's filtered measurement of its own reactive power, pu on its rating",
    "power_loop_output_pu": "output of the device's active-power loop (the power its frequency command compares "
                            "against the filtered measurement), pu on its rating",
    "reactive_loop_output_pu": "output of the device's reactive-power loop (the reactive power its voltage reference "
                               "compares against the filtered measurement), pu on its rating",
    "inner_voltage_reference_pu": "the voltage magnitude reference its voltage control tracks after the reactive "
                                  "droop, pu",
    "current_d_pu": "device current along its internal angle (in phase with the internal reference), pu on its rating",
    "current_q_pu": "device current 90 degrees ahead of its internal angle, pu on its rating",
}


def first_order_lag(signal, times, time_constant, initial):
    """y' = (u - y)/T, trapezoid rule (exact for a piecewise-linear u)."""
    output = np.empty_like(signal)
    output[0] = initial
    for k in range(1, signal.size):
        a = 0.5 * (times[k] - times[k - 1]) / time_constant
        output[k] = ((1 - a) * output[k - 1] + a * (signal[k] + signal[k - 1])) / (1 + a)
    return output


def integral(signal, times, initial):
    steps = np.diff(times)
    return initial + np.concatenate([[0.0], np.cumsum(0.5 * steps * (signal[1:] + signal[:-1]))])


def reconstruct_internal_signals(table, params_used, rating_mva=900.0, system_base_mva=100.0,
                                 nominal_frequency_hz=60.0):
    """{column: array} for one recording (a pandas table with the standard columns)."""
    p = dict(DEFAULT_PARAMS)
    p.update({name: float(value) for name, value in params_used.items() if name in DEFAULT_PARAMS})
    k = rating_mva / system_base_mva
    w0 = 2 * math.pi * nominal_frequency_hz
    times = table["time_s"].to_numpy(float)
    active, reactive = table["active_power_pu"].to_numpy(float), table["reactive_power_pu"].to_numpy(float)
    voltage, angle = table["voltage_pu"].to_numpy(float), table["bus_angle_rad"].to_numpy(float)
    setpoint = table["voltage_setpoint_pu"].to_numpy(float)

    # measurement filters and power loops, in device pu (the loops are linear, so the base cancels)
    filtered_p = first_order_lag(active, times, p["Tr"], active[0])
    filtered_q = first_order_lag(reactive, times, p["Tr"], reactive[0])
    lagged_p = first_order_lag(filtered_p, times, p["Tpm"], active[0])
    lagged_q = first_order_lag(filtered_q, times, p["Tpm"], reactive[0])
    integrator_p = integral(p["KIplim"] * (lagged_p - filtered_p), times, active[0])
    integrator_q = integral(p["KIqlim"] * (lagged_q - filtered_q), times, reactive[0])
    power_loop = p["KPplim"] * (lagged_p - filtered_p) + integrator_p
    reactive_loop = p["KPqlim"] * (lagged_q - filtered_q) + integrator_q

    # frequency command and internal angle: dw = w0*wdrp*(PIplim - Psen) on the system base
    frequency = w0 * p["wdrp"] * k * (power_loop - filtered_p)
    internal_angle = integral(frequency, times, angle[0])
    voltage_reference = setpoint + p["Qdrp"] * k * (reactive_loop - filtered_q)

    # internal-frame voltages and currents: P = vd*Id + vq*Iq, Q = -vd*Iq + vq*Id
    vd = voltage * np.cos(internal_angle - angle)
    vq = -voltage * np.sin(internal_angle - angle)
    squared = vd ** 2 + vq ** 2
    current_d = (active * vd + reactive * vq) / squared
    current_q = (active * vq - reactive * vd) / squared
    return {"internal_angle_rad": internal_angle, "internal_frequency_dev_rad_s": frequency,
            "filtered_active_power_pu": filtered_p, "filtered_reactive_power_pu": filtered_q,
            "power_loop_output_pu": power_loop, "reactive_loop_output_pu": reactive_loop,
            "inner_voltage_reference_pu": voltage_reference, "current_d_pu": current_d, "current_q_pu": current_q}
