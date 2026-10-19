"""
Builds the minimum test cases for the harness, deterministic from the seeds below.

    python build_cases.py                 # all three grids
    python build_cases.py --grids B --workers 4

grid_A  training grid: Kundur two-area, the device in GENROU 3's slot. Recorded data an operator
        would have: ambient PMU recordings, staged voltage-reference steps, natural events, at
        three operating points (one after a topology change). Noisy, internal angle removed.
        sandbox_data/ goes to the agent; holdout/ has the clean runs, case.json and answer key.
grid_B  selection grid: the same machines re-arranged (one 7-8 tie circuit out, a new load at
        the device's HV bus, different dispatch and voltage schedule). Held-out runs only; the
        agent never sees it. The scorer replays its runs closed loop with the submission.
grid_M  hidden monitor grid: re-arranged another way (one 5-6 circuit out, a heavier load at
        bus 10, different dispatch and voltage schedule). Held-out runs only. Nothing
        selects on it and neither the agent nor the RSI updater sees it; it is logged privately
        to show whether gains on grid B carry over to a grid nobody tuned on.

The same device (REGF1, parameters from the medium Kundur case) sits in every grid.
Every run is rebuilt by Harness_testing/scorer/grids/kundur_family.py from holdout/case.json,
so the scorer replays exactly these events.
"""
import argparse
import copy
import hashlib
import json
import multiprocessing as mp
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SCORER = HERE.parent / "scorer"
sys.path.insert(0, str(SCORER))

DEVICE = "REGF1"
SN = 900.0                      # device rating (MVA), GENROU 3's
SB = 100.0
TSTEP = 0.001
# ANDES inputs from medium_kundur_regf1/holdout/answer_key.json (seed 0): six parameters scaled by
# U[0.7, 1.3]; wdrp and Qdrp are converter-base droops x Sb/Sn (ANDES applies them to system-base
# P and Q); KPv = 6 for damping of the 0.85 Hz mode. Same device on every grid.
PARAMS = {"wdrp": 0.0039679823787738665, "Qdrp": 0.004309360141291611, "Tpm": 0.01811460285904292,
          "KPplim": 3.549582906585587, "KIplim": 35.638864305604905, "Tr": 0.006238266731833165,
          "KPv": 6.0}
SIGMAS = {"P": 0.001, "Q": 0.001, "V": 0.0005, "theta": 0.001}      # PMU grade
CHANNELS = [("P", "active_power_pu"), ("Q", "reactive_power_pu"), ("V", "voltage_pu"),
            ("theta", "bus_angle_rad"), ("Vset", "voltage_setpoint_pu")]
FORBIDDEN = re.compile(r"andes|regf|kundur|epri|grid.?forming|gfm|genrou|vsm|tgov|exdc", re.I)

AMB = ["PQ_0", "PQ_1", "PQ_2"]


def amb(seed, t1, sigma=0.003, loads=AMB):
    return {"kind": "ambient", "loads": loads, "sigma": sigma, "tau": 5.0, "dt": 0.5, "seed": seed, "t1": t1}


def vsteps(*pairs):
    return [{"kind": "vref_step", "t": t, "amount": a} for t, a in pairs]


# ---- grid A: Kundur (training) -------------------------------------------------------------
OP1 = {"pv": {"2": {"p0": 4.0}}, "pq": {"PQ_0": {"p0": 8.59}, "PQ_1": {"p0": 14.25}}}
GRID_A = {
    "format": "kundur_family_v1", "name": "grid_A",
    "description": "Kundur two-area (kundur_full.xlsx); device replaces GENROU 3 (bus 3); 150 MW of the "
                   "bus-8 load moved to a new load PQ_2 at bus 10; area 1 re-dispatched (GENROU 2 at "
                   "400 MW, bus-7 load -300 MW) as in the medium case so a generator trip stays in limits",
    "device": {"syn": 3},
    "network": {"extra_loads": [{"idx": "PQ_2", "bus": 10, "p0": 1.5, "q0": 0.0}]},
    "operating_points": {
        "op1": OP1,
        "op2": {"pv": {"2": {"p0": 4.0}, "3": {"p0": 4.5, "v0": 1.01}, "4": {"p0": 8.0}},
                "pq": OP1["pq"]},
        "op3": {"pv": {"2": {"p0": 4.0}}, "pq": {"PQ_0": {"p0": 8.59}, "PQ_1": {"p0": 15.25}},
                "lines_out": ["Line_9"]},
    },
    "runs": {
        "A_amb_op1": {"split": "train", "op": "op1", "tf": 60.0, "events": [amb(101, 60.0, 0.01)]},
        "A_amb_op2": {"split": "train", "op": "op2", "tf": 60.0, "events": [amb(102, 60.0, 0.01)]},
        "A_vref_op1": {"split": "train", "op": "op1", "tf": 60.0,
                       "events": [amb(103, 60.0)] + vsteps((5.0, 0.02), (20.0, -0.02), (35.0, -0.02), (50.0, 0.02))},
        "A_vref_op3": {"split": "train", "op": "op3", "tf": 45.0,
                       "events": [amb(104, 45.0)] + vsteps((5.0, 0.01), (15.0, -0.01), (25.0, -0.01), (35.0, 0.01))},
        "A_gentrip_op1": {"split": "train", "op": "op1", "tf": 40.0,
                          "events": [amb(105, 40.0), {"kind": "gen_trip", "t": 5.0, "syn": 2}]},
        "A_load_op2": {"split": "train", "op": "op2", "tf": 40.0,
                       "events": [amb(106, 40.0), {"kind": "load_scale", "t": 5.0, "load": "PQ_0", "p": 1.10, "q": 1.10}]},
        "A_fault_op1": {"split": "train", "op": "op1", "tf": 30.0,
                        "events": [amb(107, 30.0), {"kind": "fault", "t": 5.0, "bus": 8, "dur": 0.1, "xf": 0.1, "rf": 0.0}]},
        "A_line_op3": {"split": "train", "op": "op3", "tf": 30.0,
                       "events": [amb(108, 30.0), {"kind": "line_trip", "t": 5.0, "line": "Line_4"}]},
        "A_val_load_op1": {"split": "val", "op": "op1", "tf": 30.0,
                           "events": [amb(109, 30.0), {"kind": "load_scale", "t": 5.0, "load": "PQ_1", "p": 0.92, "q": 0.92}]},
        "A_val_vref_op2": {"split": "val", "op": "op2", "tf": 30.0,
                           "events": [amb(110, 30.0)] + vsteps((5.0, 0.015), (20.0, -0.015))},
        "A_test_line_op1": {"split": "holdout", "op": "op1", "tf": 20.0,
                            "events": [{"kind": "line_trip", "t": 2.0, "line": "Line_9"}]},
        "A_test_vref_op1": {"split": "holdout", "op": "op1", "tf": 20.0, "events": vsteps((2.0, -0.015), (12.0, 0.015))},
    },
}
LOG_A = {   # what the operator's log says, in the sandbox metadata
    "op1": "Normal topology. Device dispatched near 700 MW, voltage schedule 1.00 pu.",
    "op2": "Normal topology. Device re-dispatched near 450 MW, voltage schedule 1.01 pu; the generator at bus 4 picks up the difference.",
    "op3": "One circuit of the double line between buses 9 and 10 out of service for maintenance; bus-8 load about 100 MW heavier.",
}

# ---- grid B: re-arranged Kundur (selection) ----------------------------------------------------
# Device dispatch matters for what the score can see: at 550 MW a 30% error in the voltage-loop gain
# KPv cost 0.02 to 0.06 on a line trip, at 700 MW 0.16 to 0.22 (and at grid A's op1 it saturates).
# 720 MW keeps that error visible without saturating and sits just above the training dispatch.
GRID_B = {
    "format": "kundur_family_v1", "name": "grid_B",
    "description": "Kundur two-area re-arranged: device in GENROU 3's slot; one of the three 7-8 tie circuits "
                   "(Line_6) out of service; a new 200 MW load PQ_3 at the device's HV bus 9; 150 MW load PQ_2 "
                   "at bus 10; loads moved from bus 8 to bus 7; device at 720 MW (above any training dispatch) with a "
                   "1.02 pu voltage schedule",
    "device": {"syn": 3},
    "network": {"extra_loads": [{"idx": "PQ_2", "bus": 10, "p0": 1.5, "q0": 0.0},
                                {"idx": "PQ_3", "bus": 9, "p0": 2.0, "q0": 0.3}]},
    "operating_points": {
        "opB": {"pv": {"2": {"p0": 4.0}, "3": {"p0": 7.2, "v0": 1.02}, "4": {"p0": 7.0}},
                "pq": {"PQ_0": {"p0": 9.0}, "PQ_1": {"p0": 12.0}}, "lines_out": ["Line_6"]},
    },
    "runs": {
        "B_vref": {"split": "holdout", "op": "opB", "tf": 25.0, "events": vsteps((2.0, 0.025), (14.0, -0.025))},
        "B_load": {"split": "holdout", "op": "opB", "tf": 25.0,
                   "events": [{"kind": "load_scale", "t": 2.0, "load": "PQ_3", "p": 1.5, "q": 1.5}]},
        "B_line": {"split": "holdout", "op": "opB", "tf": 25.0, "events": [{"kind": "line_trip", "t": 2.0, "line": "Line_7"}]},
    },
}

# ---- grid M: re-arranged Kundur (hidden monitor) ------------------------------------------------
# Nothing selects on this grid and neither the agent nor the updater ever sees it: score.py keeps
# it out of public.json, and an RSI loop only logs it. If the score on grid B keeps improving while
# grid M's stalls, the loop is tuning to B. The runs are the same three kinds as B's (a
# voltage-reference step, a load change, a line opening) but in other places, directions and sizes,
# on a different arrangement at a similar strength, so a real improvement should show on both grids.
# Damping decided the operating point. The first draft (680 MW, 0.99 pu schedule) left the true device
# with a 0.93 Hz mode at a damping ratio of 0.009, and its voltage-reference run swung V between 0.84
# and 1.15 pu. At 650 MW and 1.01 pu the least-damped mode is 0.92 Hz at 0.056, next to grid A's 0.058
# (0.59 Hz, op1) and grid B's 0.079 (0.53 Hz). ANDES EIG with the true device in the slot. Damping
# falls as the voltage drops, so the voltage-reference step goes down only 1.5%: at -2.5% the
# lowered setpoint sat in a less damped region and the 0.9 Hz swing barely decayed for 12 s.
# The line opening is a 6-7 circuit. Opening a 9-10 circuit moved the device's P by an RMSE of only
# 0.0019 pu, under the scorer's 3-sigma floor (0.003), so a flat model scored 0.97 instead of 1. The
# 6-7 circuit moves P and Q by 0.021 and 0.037 (B_line: 0.016 and 0.069). Deliberately wrong models
# cost within about 25% of what they cost on grid B, except a 30% low KPv, which saturates two of M's
# three runs (1.04 against 0.53 on B; grid A's held-out runs saturate too). See monitor_check.json.
GRID_M = {
    "format": "kundur_family_v1", "name": "grid_M",
    "description": "Kundur two-area re-arranged another way: device in GENROU 3's slot; all three 7-8 tie "
                   "circuits in service; one of the two 5-6 circuits (Line_1) out; PQ_2 at bus 10 doubled to "
                   "300 MW; bus-7 load 1000 MW, bus-8 load 1150 MW; GENROU 2 at 500 MW and GENROU 4 at 650 MW; "
                   "device at 650 MW with a 1.01 pu voltage schedule",
    "device": {"syn": 3},
    "network": {"extra_loads": [{"idx": "PQ_2", "bus": 10, "p0": 3.0, "q0": 0.0}]},
    "operating_points": {
        "opM": {"pv": {"2": {"p0": 5.0}, "3": {"p0": 6.5, "v0": 1.01}, "4": {"p0": 6.5}},
                "pq": {"PQ_0": {"p0": 10.0}, "PQ_1": {"p0": 11.5}}, "lines_out": ["Line_1"]},
    },
    "runs": {
        "M_vref": {"split": "holdout", "op": "opM", "tf": 25.0, "events": vsteps((2.0, -0.015), (14.0, 0.015))},
        "M_load": {"split": "holdout", "op": "opM", "tf": 25.0,
                   "events": [{"kind": "load_scale", "t": 2.0, "load": "PQ_2", "p": 0.6, "q": 0.6}]},
        "M_line": {"split": "holdout", "op": "opM", "tf": 25.0, "events": [{"kind": "line_trip", "t": 2.0, "line": "Line_2"}]},
    },
}
GRIDS = {"A": GRID_A, "B": GRID_B, "M": GRID_M}


# ---- simulation ----------------------------------------------------------------------------
def simulate(args):
    spec, run = args
    import andes
    from grids import kundur_family as KF
    andes.config_logger(stream_level=50)
    r = spec["runs"][run]
    ss = KF.build(DEVICE, PARAMS, run, spec=spec)
    ss.TDS.config.tf, ss.TDS.config.tstep, ss.TDS.config.no_tqdm = r["tf"], TSTEP, 1
    ss.TDS.config.criteria = 0          # its angle test counts a tripped machine's free rotor
    ss.TDS.run()
    if ss.TDS.busted or ss.exit_code != 0 or ss.dae.t < r["tf"] - 1e-9:
        raise RuntimeError(f"{run}: TDS failed at t={float(ss.dae.t):.4f}")
    m, ts = getattr(ss, DEVICE), ss.dae.ts
    ib = ss.Bus.idx.v.index(m.bus.v[0])
    X = lambda v: np.asarray(ts.x[:, v.a]).ravel()
    Y = lambda v: np.asarray(ts.y[:, v.a]).ravel()
    raw_t = np.asarray(ts.t).ravel()
    lim = {}
    for var, sig, lo, hi in (("Psig", X(m.Psig_y), m.Pmin, m.Pmax), ("Qsig", X(m.Qsig_y), m.Qmin, m.Qmax),
                             ("dw", Y(m.dw_x), m.dwmin, m.dwmax)):
        lim[var] = {"min": float(sig.min()), "max": float(sig.max()), "lo": float(lo.v[0]), "hi": float(hi.v[0])}
        if not (lo.v[0] < sig.min() and sig.max() < hi.v[0]):
            raise RuntimeError(f"{run}: limiter {var} binds: {lim[var]}")
    t = np.arange(0.0, r["tf"] + TSTEP / 2, TSTEP)
    k = ss.config.mva / m.Sn.v[0]
    a = np.asarray(ts.y[:, ss.Bus.a.a[ib]]).ravel()
    clean = {"P": Y(m.Pe) * k, "Q": Y(m.Qe) * k, "V": np.asarray(ts.y[:, ss.Bus.v.a[ib]]).ravel(), "theta": a - a[0]}
    clean = {c: np.interp(t, raw_t, v) for c, v in clean.items()}
    vref0 = float(m.vref.v[0])
    # vref was altered during the run: recover the initial schedule from the spec
    vref0 = vref0 - sum(e["amount"] for e in r["events"] if e["kind"] == "vref_step")
    if abs(vref0 - clean["V"][0]) > 1e-6:
        raise RuntimeError(f"{run}: voltage schedule {vref0} differs from V0 {clean['V'][0]}")
    clean["Vset"] = KF.vset_series(spec, run, t, clean["V"][0])
    return run, t, clean, lim


def add_noise(clean, seed, r_index):
    out = {}
    for c, (k, _) in enumerate(CHANNELS):
        if k == "Vset":
            out[k] = clean[k].copy()            # a logged setpoint, not a measurement
        else:
            g = np.random.default_rng([seed, 1, r_index, c])
            out[k] = clean[k] + g.normal(0.0, SIGMAS[k], clean[k].size)
    return out


def write_csv(path, t, d):
    np.savetxt(path, np.column_stack([t] + [d[k] for k, _ in CHANNELS]), fmt="%.9g", delimiter=",",
               header=",".join(["time_s"] + [col for _, col in CHANNELS]), comments="")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plot(path, run, t, clean, noisy, marks):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(len(CHANNELS), 1, sharex=True, figsize=(10, 10))
    for a, (k, col) in zip(ax, CHANNELS):
        if noisy is not None and k != "Vset":
            a.plot(t, noisy[k], color="#9db8d9", lw=0.4, label="noisy")
        a.plot(t, clean[k], color="#c4441a", lw=1.0, label="clean")
        for m in marks:
            a.axvline(m, color="#888", lw=0.6, ls=":")
        a.set_ylabel(col, fontsize=8)
        a.grid(alpha=0.3)
    ax[0].legend(frameon=False, fontsize=8)
    ax[0].set_title(run, loc="left")
    ax[-1].set_xlabel("time_s")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def describe(ev, alone=True):
    k = ev["kind"]
    if k == "vref_step":
        return f"t={ev['t']:.3f} s: staged test, device voltage reference stepped {ev['amount'] * 100:+.1f}% of nominal"
    if k == "load_scale":
        return f"t={ev['t']:.3f} s: load at bus {LOAD_BUS[ev['load']]} changed by {(ev['p'] - 1) * 100:+.0f}% (P and Q)"
    if k == "line_trip":
        a, b = LINE_BUSES[ev["line"]]
        return f"t={ev['t']:.3f} s: one circuit of the line between buses {a} and {b} opened"
    if k == "gen_trip":
        return f"t={ev['t']:.3f} s: generator at bus {ev['syn']} tripped"
    if k == "fault":
        return (f"t={ev['t']:.3f} s: three-phase fault at bus {ev['bus']} through {ev['xf']} pu reactance, "
                f"cleared after {ev['dur'] * 1000:.0f} ms")
    if k == "ambient":
        return ("ambient recording: normal operation, random load variation, no switching" if alone else
                "background: normal random load variation throughout the recording")
    raise ValueError(k)


def operator_log(events):
    alone = len(events) == 1
    out, v = [], 0.0
    for e in events:
        line = describe(e, alone)
        if e["kind"] == "vref_step":
            v += e["amount"]
            line += f" (setpoint now {v * 100:+.1f}% from schedule)"
        out.append(line)
    return out


LOAD_BUS = {"PQ_0": 7, "PQ_1": 8, "PQ_2": 10, "PQ_3": 9}
LINE_BUSES = {"Line_0": (5, 6), "Line_1": (5, 6), "Line_2": (6, 7), "Line_3": (6, 7),
              "Line_4": (7, 8), "Line_5": (7, 8), "Line_6": (7, 8), "Line_7": (8, 9), "Line_8": (8, 9),
              "Line_9": (9, 10), "Line_10": (9, 10)}


def truth_droops(op):
    """Steady-state droops of the true device at operating point op, from its exact linearization."""
    import metrics as M
    import symbolic
    from truth import regf1_spec
    m = symbolic.Model(regf1_spec.spec(PARAMS, inner="full", Sn=SN))
    lin = m.linearize(op)
    gains, _ = M.droop_gains(lin["A"], lin["B"], lin["C"], lin["D"])
    return {"gains": gains, **M.readable(gains, 60.0)}


def build_grid(key, spec, results, out):
    hold = out / "holdout"
    (hold / "plots").mkdir(parents=True, exist_ok=True)
    has_sandbox = any(r["split"] in ("train", "val") for r in spec["runs"].values())
    sbx = out / "sandbox_data"
    sha, snr, lims, ops = {}, {}, {}, {}
    meta_runs = {}
    for i, (run, r) in enumerate(spec["runs"].items()):
        _, t, clean, lim = results[run]
        lims[run] = lim
        noisy = add_noise(clean, 0, i)
        snr[run] = {k: float(np.ptp(clean[k]) / SIGMAS[k]) for k in SIGMAS}
        ops[run] = [float(clean["V"][0]), 0.0, float(clean["P"][0]), float(clean["Q"][0])]
        sha[f"holdout/{run}_clean.csv"] = write_csv(hold / f"{run}_clean.csv", t, clean)
        from grids import kundur_family as KF
        plot(hold / "plots" / f"{run}.png", run, t, clean, noisy if r["split"] != "holdout" else None,
             KF.switching_times(spec, run))
        if r["split"] in ("train", "val"):
            d = sbx / r["split"]
            d.mkdir(parents=True, exist_ok=True)
            sha[f"sandbox_data/{r['split']}/{run}.csv"] = write_csv(d / f"{run}.csv", t, noisy)
            meta_runs[run] = {"split": r["split"], "file": f"{r['split']}/{run}.csv", "duration_s": r["tf"],
                              "operating_conditions": LOG_A[r["op"]],
                              "operator_log": operator_log(r["events"])}
    if has_sandbox:
        (sbx / "runs.json").write_text(json.dumps(meta_runs, indent=2))
        (sbx / "dataset.json").write_text(json.dumps({
            "device": "one inverter-based unit, terminal measurements at its point of connection",
            "rating_MVA": SN, "nominal_frequency_Hz": 60.0, "sample_period_s": TSTEP,
            "columns": {"time_s": "s from the start of the recording",
                        "active_power_pu": "P injected by the device, pu on its rating",
                        "reactive_power_pu": "Q injected by the device, pu on its rating",
                        "voltage_pu": "terminal voltage magnitude, pu",
                        "bus_angle_rad": "terminal voltage angle, rad, relative to its value at t = 0",
                        "voltage_setpoint_pu": "device voltage setpoint from the control log, pu (not a measurement, no noise)"},
            "measurement_noise_std": {"active_power_pu": SIGMAS["P"], "reactive_power_pu": SIGMAS["Q"],
                                      "voltage_pu": SIGMAS["V"], "bus_angle_rad": SIGMAS["theta"]},
            "notes": "PMU-grade measurements. Staged voltage-reference tests are logged with their times. "
                     "Ambient recordings have no switching events.",
        }, indent=2))
        for f in sbx.rglob("*.json"):
            assert not FORBIDDEN.search(f.read_text()), f"forbidden word in {f}"
        for f in sbx.rglob("*"):
            assert not FORBIDDEN.search(f.name), f"forbidden word in {f.name}"
    (hold / "case.json").write_text(json.dumps(spec, indent=1))
    droops = {op: truth_droops(v) for op, v in {spec["runs"][r]["op"]: ops[r] for r in spec["runs"]}.items()}
    answer = {
        "grid": spec["name"], "device": DEVICE, "device_rating_MVA": SN, "params_used": PARAMS,
        "params_note": "ANDES inputs. wdrp and Qdrp are converter-base droops x Sb/Sn; converter-base "
                       f"values: wdrp {PARAMS['wdrp'] * SN / SB:.6g}, Qdrp {PARAMS['Qdrp'] * SN / SB:.6g}",
        "sigmas": SIGMAS, "metadata": {"rating_MVA": SN, "nominal_frequency_Hz": 60.0, "sample_period_s": TSTEP},
        "operating_point_per_run": {r: dict(zip(("V0", "theta0", "P0", "Q0"), v)) for r, v in ops.items()},
        "truth_droops_per_op": droops,
        "runs": {r: {"split": v["split"], "op": v["op"], "tf": v["tf"],
                     "events": operator_log(v["events"])} for r, v in spec["runs"].items()},
        "snr_ptp_over_sigma": snr, "limiter_ranges": lims, "sha256": sha,
        "regenerate": "python build_cases.py --grids " + key,
    }
    (hold / "answer_key.json").write_text(json.dumps(answer, indent=2, default=float))
    return answer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grids", default="A,B,M")
    ap.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    ap.add_argument("--out", default=str(HERE))
    a = ap.parse_args()
    keys = a.grids.split(",")
    jobs = [(GRIDS[k], run) for k in keys for run in GRIDS[k]["runs"]]
    jobs.sort(key=lambda j: -j[0]["runs"][j[1]]["tf"])         # longest first
    with mp.get_context("spawn").Pool(a.workers) as pool:
        res = {}
        for run, t, clean, lim in pool.imap_unordered(simulate, jobs):
            res[run] = (run, t, clean, lim)
            print(f"  done {run}", flush=True)
    for k in keys:
        spec = copy.deepcopy(GRIDS[k])
        ans = build_grid(k, spec, res, Path(a.out) / spec["name"])
        low = [(r, c) for r, d in ans["snr_ptp_over_sigma"].items() for c, v in d.items() if v < 10]
        print(f"{spec['name']}: {len(spec['runs'])} runs; low SNR (<10): {low or 'none'}")


if __name__ == "__main__":
    main()
