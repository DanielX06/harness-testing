"""Compares a model's small-signal frequency response with the one measured in the recordings.

    python tools/freq_response.py                    # data only: the device's measured response
    python tools/freq_response.py submission.json    # data vs your model (linearized like the scorer does)

For each quiet train recording (ambient, or staged voltage-reference tests only) it fits a linear
ARX model of the differenced, 10 ms-decimated data, inputs (V, theta, Vset) -> outputs (P, Q), and reads
off the frequency response from V and theta to P and Q between 0.1 and 10 Hz. The recordings are
noise-free, so this is the device's own small-signal response at that recording's operating point.
With a submission, it linearizes the model at the same operating point (V, theta, Vset held, as the
scorer's check does) and prints both, with an error per channel:
    err = mean_f |H_model - H_data| / mean_f |H_data|     (0 = match, 1 = a model that never moves; capped at 2)
Gains are |dP/dV|, |dP/dtheta|, |dQ/dV|, |dQ/dtheta| in pu per pu or pu per rad; phases in degrees.
Below about 0.2 Hz the data estimate is rough (recordings are 30-60 s); above that it is reliable.
Runs in a few seconds.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
FREQS = [0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0]
CHANNELS = [("P/V", 0, 0), ("P/theta", 0, 1), ("Q/V", 1, 0), ("Q/theta", 1, 1)]
NA = NB = 8
DEC = 10


def quiet_recordings():
    runs = json.load(open("runs.json"))
    out = []
    for name, run in runs.items():
        if run.get("split") != "train":
            continue
        log = " ".join(run.get("operator_log", [])).lower()
        events = [e for e in run.get("operator_log", []) if e.lower().startswith("t=")]
        if "ambient" in log or (events and all("staged test" in e.lower() for e in events)):
            out.append((name, run["file"]))
    return out


def data_fr(path, freqs=FREQS):
    d = pd.read_csv(path).iloc[::DEC]
    dt = float(d.time_s.iloc[1] - d.time_s.iloc[0])
    vset = d.voltage_setpoint_pu if "voltage_setpoint_pu" in d else d.voltage_pu * 0
    u = np.c_[d.voltage_pu.diff(), d.bus_angle_rad.diff(), vset.diff()][1:]
    y = np.c_[d.active_power_pu.diff(), d.reactive_power_pu.diff()][1:]
    n, k0 = len(y), max(NA, NB)
    X = np.hstack([y[k0 - i:n - i] for i in range(1, NA + 1)] + [u[k0 - j:n - j] for j in range(0, NB + 1)])
    scale = np.sqrt((X ** 2).mean(0)) + 1e-30
    th = np.linalg.lstsq(X / scale, y[k0:], rcond=None)[0] / scale[:, None]
    H = []
    for f in freqs:
        z = np.exp(2j * np.pi * f * dt)
        a = np.eye(2, dtype=complex)
        b = np.zeros((2, 3), complex)
        for i in range(1, NA + 1):
            a -= th[(i - 1) * 2:i * 2].T * z ** -i
        for j in range(NB + 1):
            b += th[2 * NA + 3 * j:2 * NA + 3 * (j + 1)].T * z ** -j
        H.append(np.linalg.solve(a, b)[:, :2])
    first = d.iloc[0]
    op = [float(first.voltage_pu), float(first.bus_angle_rad), float(first.active_power_pu), float(first.reactive_power_pu)]
    return np.array(H), op


def model_fr(model, op, freqs=FREQS):
    lin = model.linearize(op)
    A, B, C, D = lin["A"], lin["B"], lin["C"], lin["D"]
    n = A.shape[0]
    out = []
    for f in freqs:
        s = 2j * np.pi * f
        out.append(D + (C @ np.linalg.solve(s * np.eye(n) - A, B) if n else 0))
    return np.array(out), lin


def channel_error(Hm, Hd, o, c):
    return min(2.0, float(np.mean(np.abs(Hm[:, o, c] - Hd[:, o, c])) / np.mean(np.abs(Hd[:, o, c]))))


def main(sub=None):
    model = None
    if sub:
        import submission_parser
        try:
            model = submission_parser.load_submission(sub)
        except submission_parser.SubmissionError as error:
            print(f"INVALID: {error}")
            return 1
    print("freq Hz: " + "  ".join(f"{f:>6}" for f in FREQS))
    errs = {name: [] for name, _, _ in CHANNELS}
    for name, path in quiet_recordings():
        Hd, op = data_fr(path)
        print(f"\n== {name}  (V0={op[0]:.3f}, P0={op[2]:.3f}, Q0={op[3]:.3f})")
        Hm = None
        if model is not None:
            Hm, lin = model_fr(model, op)
            eig = np.linalg.eigvals(lin["A"]) if lin["A"].size else np.array([])
            if eig.size and eig.real.max() > 1e-6:
                print(f"   WARNING: model unstable on its own at this point, max Re(eig) = {eig.real.max():.3g}")
        for ch, o, c in CHANNELS:
            print(f"  {ch:8s} data |H| " + " ".join(f"{abs(Hd[i, o, c]):6.3f}" for i in range(len(FREQS)))
                  + "   phase " + " ".join(f"{np.degrees(np.angle(Hd[i, o, c])):5.0f}" for i in range(len(FREQS))))
            if Hm is not None:
                e = channel_error(Hm, Hd, o, c)
                errs[ch].append(e)
                print(f"  {'':8s} model|H| " + " ".join(f"{abs(Hm[i, o, c]):6.3f}" for i in range(len(FREQS)))
                      + "   phase " + " ".join(f"{np.degrees(np.angle(Hm[i, o, c])):5.0f}" for i in range(len(FREQS)))
                      + f"   err {e:.2f}")
    if model is not None:
        print("\nMEAN ERROR per channel (0 = matches the data, 1 = no better than a model that never moves):")
        for ch in errs:
            print(f"  {ch:8s} {np.mean(errs[ch]):.2f}")
        print(f"  overall  {np.mean([np.mean(v) for v in errs.values()]):.2f}")
        print("A channel whose model gain is several times the data's (or the reverse) means the structure or a")
        print("parameter is wrong there, even if the time-domain replay looks fine.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
