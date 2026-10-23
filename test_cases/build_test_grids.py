"""Builds the test grids from their specs in grid_specs/, deterministic from the seeds in those specs.

    python test_cases/build_test_grids.py                        # grids A, B and M
    python test_cases/build_test_grids.py --grids B --workers 4
    python test_cases/build_test_grids.py --grids B --out /tmp/rebuilt    # somewhere else, to compare

Each grid_specs/grid_<X>.json holds
  purpose                   what the grid is for
  case                      the grid as the scorer rebuilds it: the device's slot, the network changes, the
                            operating points and every run's events. Written unchanged to holdout/case.json.
  device_under_test         the device model, its rating and its ANDES parameters (the same in every grid today).
                            A new device (REGF2, REGF3) needs its recording variables in DEVICE_RECORDING_VARIABLES
                            below, its voltage-setpoint variable in scorer/grids/kundur_family_builder.py and its
                            truth model in scorer/truth/; then it is a change to this field.
  operating_conditions_log  (a grid with training runs) what the operator's log says about each operating point
  design_notes              why the grid is the way it is

For each grid it writes holdout/ (every run's clean recording, case.json, answer_key.json, plots/) and, for a grid
with training or validation runs, sandbox_data/ (the noisy recordings the solver gets, runs.json, dataset.json).
draw_grid_diagrams.py draws system_diagram.png; make_noise_free_sandbox.py makes sandbox_data_clean/ from holdout/.
The scorer replays each held-out run from case.json with scorer/grids/kundur_family_builder.py, which is also what
simulates the runs here, so a held-out run is replayed with exactly the events that produced its recording.
"""
import argparse
import hashlib
import json
import multiprocessing
import sys
from pathlib import Path

import numpy as np

TEST_CASES_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_CASES_DIR.parent))          # the repository root
from common.hidden_names import SIMULATOR_AND_DEVICE_NAMES  # noqa: E402

GRID_SPECS_DIR = TEST_CASES_DIR / "grid_specs"
SAMPLE_PERIOD_S = 0.001
NOMINAL_FREQUENCY_HZ = 60.0
NOISE_SIGMAS = {"P": 0.001, "Q": 0.001, "V": 0.0005, "theta": 0.001}        # PMU grade
RECORDED_CHANNELS = [("P", "active_power_pu"), ("Q", "reactive_power_pu"), ("V", "voltage_pu"),
                     ("theta", "bus_angle_rad"), ("Vset", "voltage_setpoint_pu")]
NOISE_SEED = 0
# Per device model: the ANDES variables its P and Q are read from, and the limiters that must never bind in a
# recording, as (label, variable, "state" or "algebraic", lower-limit parameter, upper-limit parameter).
DEVICE_RECORDING_VARIABLES = {
    "REGF1": {"active_power": "Pe", "reactive_power": "Qe",
              "limiters": (("Psig", "Psig_y", "state", "Pmin", "Pmax"), ("Qsig", "Qsig_y", "state", "Qmin", "Qmax"),
                           ("dw", "dw_x", "algebraic", "dwmin", "dwmax"))},
}
# Kundur's loads and lines, as the operator's log names them
LOAD_BUS = {"PQ_0": 7, "PQ_1": 8, "PQ_2": 10, "PQ_3": 9}
LINE_BUSES = {"Line_0": (5, 6), "Line_1": (5, 6), "Line_2": (6, 7), "Line_3": (6, 7), "Line_4": (7, 8), "Line_5": (7, 8),
              "Line_6": (7, 8), "Line_7": (8, 9), "Line_8": (8, 9), "Line_9": (9, 10), "Line_10": (9, 10)}


def load_grid_spec(key):
    with open(GRID_SPECS_DIR / f"grid_{key}.json") as file:
        return json.load(file)


# ---- simulation (one ANDES run per process) --------------------------------------------------------------------
def simulate_run(job):
    """job: (grid spec, run name). Returns (run name, times, clean signals, limiter ranges)."""
    grid_spec, run_name = job
    import andes
    from scorer.grids.kundur_family_builder import VOLTAGE_SETPOINT_VARIABLE, build_system, voltage_setpoint_series
    andes.config_logger(stream_level=50)
    case, device = grid_spec["case"], grid_spec["device_under_test"]
    model_name = device["model"]
    if model_name not in DEVICE_RECORDING_VARIABLES:
        raise ValueError(f"add {model_name}'s recording variables to DEVICE_RECORDING_VARIABLES")
    variables = DEVICE_RECORDING_VARIABLES[model_name]
    run = case["runs"][run_name]
    system = build_system(model_name, device["params"], run_name, case_spec=case)
    system.TDS.config.tf, system.TDS.config.tstep, system.TDS.config.no_tqdm = run["tf"], SAMPLE_PERIOD_S, 1
    system.TDS.config.criteria = 0          # its angle test counts a tripped machine's free rotor
    system.TDS.run()
    if system.TDS.busted or system.exit_code != 0 or system.dae.t < run["tf"] - 1e-9:
        raise RuntimeError(f"{run_name}: the time-domain simulation failed at t={float(system.dae.t):.4f}")

    device_model, series = getattr(system, model_name), system.dae.ts
    bus_position = system.Bus.idx.v.index(device_model.bus.v[0])

    def recorded(variable, kind):
        values = series.x if kind == "state" else series.y
        return np.asarray(values[:, getattr(device_model, variable).a]).ravel()

    limiter_ranges = {}
    for label, variable, kind, lower_name, upper_name in variables["limiters"]:
        signal = recorded(variable, kind)
        lower, upper = getattr(device_model, lower_name).v[0], getattr(device_model, upper_name).v[0]
        limiter_ranges[label] = {"min": float(signal.min()), "max": float(signal.max()), "lo": float(lower), "hi": float(upper)}
        if not (lower < signal.min() and signal.max() < upper):
            raise RuntimeError(f"{run_name}: limiter {label} binds: {limiter_ranges[label]}")

    raw_times = np.asarray(series.t).ravel()
    times = np.arange(0.0, run["tf"] + SAMPLE_PERIOD_S / 2, SAMPLE_PERIOD_S)
    to_device_base = system.config.mva / device_model.Sn.v[0]
    angle = np.asarray(series.y[:, system.Bus.a.a[bus_position]]).ravel()
    clean = {"P": recorded(variables["active_power"], "algebraic") * to_device_base,
             "Q": recorded(variables["reactive_power"], "algebraic") * to_device_base,
             "V": np.asarray(series.y[:, system.Bus.v.a[bus_position]]).ravel(), "theta": angle - angle[0]}
    clean = {signal: np.interp(times, raw_times, values) for signal, values in clean.items()}
    # the setpoint was altered during the run: recover its schedule from the events
    schedule = float(getattr(device_model, VOLTAGE_SETPOINT_VARIABLE[model_name]).v[0])
    schedule -= sum(event["amount"] for event in run["events"] if event["kind"] == "vref_step")
    if abs(schedule - clean["V"][0]) > 1e-6:
        raise RuntimeError(f"{run_name}: voltage schedule {schedule} differs from V0 {clean['V'][0]}")
    clean["Vset"] = voltage_setpoint_series(case, run_name, times, clean["V"][0])
    return run_name, times, clean, limiter_ranges


def add_measurement_noise(clean, run_index):
    """PMU-grade noise on P, Q, V and theta; the setpoint is a logged value, not a measurement."""
    noisy = {}
    for channel_index, (signal, _) in enumerate(RECORDED_CHANNELS):
        if signal == "Vset":
            noisy[signal] = clean[signal].copy()
        else:
            generator = np.random.default_rng([NOISE_SEED, 1, run_index, channel_index])
            noisy[signal] = clean[signal] + generator.normal(0.0, NOISE_SIGMAS[signal], clean[signal].size)
    return noisy


def write_recording(path, times, signals):
    """The recording as CSV; returns its SHA-256."""
    np.savetxt(path, np.column_stack([times] + [signals[signal] for signal, _ in RECORDED_CHANNELS]), fmt="%.9g",
               delimiter=",", header=",".join(["time_s"] + [column for _, column in RECORDED_CHANNELS]), comments="")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plot_recording(path, run_name, times, clean, noisy, event_times):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(len(RECORDED_CHANNELS), 1, sharex=True, figsize=(10, 10))
    for axis, (signal, column) in zip(axes, RECORDED_CHANNELS):
        if noisy is not None and signal != "Vset":
            axis.plot(times, noisy[signal], color="#9db8d9", lw=0.4, label="noisy")
        axis.plot(times, clean[signal], color="#c4441a", lw=1.0, label="clean")
        for event_time in event_times:
            axis.axvline(event_time, color="#888", lw=0.6, ls=":")
        axis.set_ylabel(column, fontsize=8)
        axis.grid(alpha=0.3)
    axes[0].legend(frameon=False, fontsize=8)
    axes[0].set_title(run_name, loc="left")
    axes[-1].set_xlabel("time_s")
    figure.tight_layout()
    figure.savefig(path, dpi=100)
    plt.close(figure)


# ---- the operator's log -------------------------------------------------------------------------------------
def describe_event(event, ambient_only=True):
    kind = event["kind"]
    if kind == "vref_step":
        return f"t={event['t']:.3f} s: staged test, device voltage reference stepped {event['amount'] * 100:+.1f}% of nominal"
    if kind == "load_scale":
        return f"t={event['t']:.3f} s: load at bus {LOAD_BUS[event['load']]} changed by {(event['p'] - 1) * 100:+.0f}% (P and Q)"
    if kind == "line_trip":
        first_bus, second_bus = LINE_BUSES[event["line"]]
        return f"t={event['t']:.3f} s: one circuit of the line between buses {first_bus} and {second_bus} opened"
    if kind == "gen_trip":
        return f"t={event['t']:.3f} s: generator at bus {event['syn']} tripped"
    if kind == "fault":
        return (f"t={event['t']:.3f} s: three-phase fault at bus {event['bus']} through {event['xf']} pu reactance, "
                f"cleared after {event['dur'] * 1000:.0f} ms")
    if kind == "ambient":
        return ("ambient recording: normal operation, random load variation, no switching" if ambient_only else
                "background: normal random load variation throughout the recording")
    raise ValueError(kind)


def operator_log(events):
    """The run's events as the operator's log lists them, with the setpoint after each staged step."""
    lines, setpoint_offset = [], 0.0
    for event in events:
        line = describe_event(event, ambient_only=len(events) == 1)
        if event["kind"] == "vref_step":
            setpoint_offset += event["amount"]
            line += f" (setpoint now {setpoint_offset * 100:+.1f}% from schedule)"
        lines.append(line)
    return lines


# ---- the answer key ---------------------------------------------------------------------------------------------
def truth_droops(device, operating_point):
    """Steady-state droops of the true device at an operating point (V0, theta0, P0, Q0), from its exact
    linearization."""
    from scorer.score_components import droop_gains, droops_as_operators_read_them
    from scorer.submission_parser import TerminalModel
    from scorer.truth import truth_spec_for
    model = TerminalModel(truth_spec_for(device["model"], device["params"], device["rating_mva"]))
    linearization = model.linearize(operating_point)
    gains, _ = droop_gains(linearization["A"], linearization["B"], linearization["C"], linearization["D"])
    return {"gains": gains, **droops_as_operators_read_them(gains, NOMINAL_FREQUENCY_HZ)}


def check_sandbox_names(sandbox_dir):
    """Nothing the solver gets may name the simulator, the case or the device."""
    for path in sandbox_dir.rglob("*"):
        assert not SIMULATOR_AND_DEVICE_NAMES.search(path.name), f"forbidden word in {path.name}"
        if path.suffix == ".json":
            assert not SIMULATOR_AND_DEVICE_NAMES.search(path.read_text()), f"forbidden word in {path}"


def write_grid_files(key, grid_spec, simulations, grid_dir):
    """Every file of one grid, from its runs' simulations. Returns the answer key."""
    case, device = grid_spec["case"], grid_spec["device_under_test"]
    holdout_dir, sandbox_dir = grid_dir / "holdout", grid_dir / "sandbox_data"
    (holdout_dir / "plots").mkdir(parents=True, exist_ok=True)
    from scorer.grids.kundur_family_builder import switching_times
    hashes, signal_to_noise, limiter_ranges, operating_points, sandbox_runs = {}, {}, {}, {}, {}
    for run_index, (run_name, run) in enumerate(case["runs"].items()):
        _, times, clean, limiter_ranges[run_name] = simulations[run_name]
        noisy = add_measurement_noise(clean, run_index)
        signal_to_noise[run_name] = {signal: float(np.ptp(clean[signal]) / NOISE_SIGMAS[signal]) for signal in NOISE_SIGMAS}
        operating_points[run_name] = [float(clean["V"][0]), 0.0, float(clean["P"][0]), float(clean["Q"][0])]
        hashes[f"holdout/{run_name}_clean.csv"] = write_recording(holdout_dir / f"{run_name}_clean.csv", times, clean)
        plot_recording(holdout_dir / "plots" / f"{run_name}.png", run_name, times, clean,
                       noisy if run["split"] != "holdout" else None, switching_times(case, run_name))
        if run["split"] in ("train", "val"):
            split_dir = sandbox_dir / run["split"]
            split_dir.mkdir(parents=True, exist_ok=True)
            hashes[f"sandbox_data/{run['split']}/{run_name}.csv"] = write_recording(split_dir / f"{run_name}.csv", times, noisy)
            sandbox_runs[run_name] = {"split": run["split"], "file": f"{run['split']}/{run_name}.csv", "duration_s": run["tf"],
                                      "operating_conditions": grid_spec["operating_conditions_log"][run["op"]],
                                      "operator_log": operator_log(run["events"])}
    if sandbox_runs:
        (sandbox_dir / "runs.json").write_text(json.dumps(sandbox_runs, indent=2))
        (sandbox_dir / "dataset.json").write_text(json.dumps({
            "device": "one inverter-based unit, terminal measurements at its point of connection",
            "rating_MVA": device["rating_mva"], "nominal_frequency_Hz": NOMINAL_FREQUENCY_HZ,
            "sample_period_s": SAMPLE_PERIOD_S,
            "columns": {"time_s": "s from the start of the recording",
                        "active_power_pu": "P injected by the device, pu on its rating",
                        "reactive_power_pu": "Q injected by the device, pu on its rating",
                        "voltage_pu": "terminal voltage magnitude, pu",
                        "bus_angle_rad": "terminal voltage angle, rad, relative to its value at t = 0",
                        "voltage_setpoint_pu": "device voltage setpoint from the control log, pu (not a measurement, no noise)"},
            "measurement_noise_std": {"active_power_pu": NOISE_SIGMAS["P"], "reactive_power_pu": NOISE_SIGMAS["Q"],
                                      "voltage_pu": NOISE_SIGMAS["V"], "bus_angle_rad": NOISE_SIGMAS["theta"]},
            "notes": "PMU-grade measurements. Staged voltage-reference tests are logged with their times. "
                     "Ambient recordings have no switching events.",
        }, indent=2))
        check_sandbox_names(sandbox_dir)
    (holdout_dir / "case.json").write_text(json.dumps(case, indent=1))
    droops = {op: truth_droops(device, point)
              for op, point in {case["runs"][run_name]["op"]: operating_points[run_name] for run_name in case["runs"]}.items()}
    params, rating, system_base = device["params"], device["rating_mva"], device["system_base_mva"]
    params_note = "ANDES inputs."
    if "wdrp" in params and "Qdrp" in params:
        params_note += (" wdrp and Qdrp are converter-base droops x Sb/Sn; converter-base values: "
                        f"wdrp {params['wdrp'] * rating / system_base:.6g}, Qdrp {params['Qdrp'] * rating / system_base:.6g}")
    answer_key = {
        "grid": case["name"], "device": device["model"], "device_rating_MVA": rating, "params_used": params,
        "params_note": params_note, "sigmas": NOISE_SIGMAS,
        "metadata": {"rating_MVA": rating, "nominal_frequency_Hz": NOMINAL_FREQUENCY_HZ, "sample_period_s": SAMPLE_PERIOD_S},
        "operating_point_per_run": {run_name: dict(zip(("V0", "theta0", "P0", "Q0"), point))
                                    for run_name, point in operating_points.items()},
        "truth_droops_per_op": droops,
        "runs": {run_name: {"split": run["split"], "op": run["op"], "tf": run["tf"], "events": operator_log(run["events"])}
                 for run_name, run in case["runs"].items()},
        "snr_ptp_over_sigma": signal_to_noise, "limiter_ranges": limiter_ranges, "sha256": hashes,
        "regenerate": "python test_cases/build_test_grids.py --grids " + key,
    }
    (holdout_dir / "answer_key.json").write_text(json.dumps(answer_key, indent=2, default=float))
    return answer_key


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--grids", default="A,B,M", help="comma-separated grid letters")
    parser.add_argument("--workers", type=int, default=max(1, (multiprocessing.cpu_count() or 2) - 1))
    parser.add_argument("--out", default=str(TEST_CASES_DIR), help="where the grid_<X>/ folders go")
    options = parser.parse_args()
    keys = options.grids.split(",")
    grid_specs = {key: load_grid_spec(key) for key in keys}
    jobs = [(grid_specs[key], run_name) for key in keys for run_name in grid_specs[key]["case"]["runs"]]
    jobs.sort(key=lambda job: -job[0]["case"]["runs"][job[1]]["tf"])           # longest first
    simulations = {}
    with multiprocessing.get_context("spawn").Pool(options.workers) as pool:
        for result in pool.imap_unordered(simulate_run, jobs):
            simulations[result[0]] = result
            print(f"  done {result[0]}", flush=True)
    for key in keys:
        name = grid_specs[key]["case"]["name"]
        answer_key = write_grid_files(key, grid_specs[key], simulations, Path(options.out) / name)
        low = [(run_name, signal) for run_name, ratios in answer_key["snr_ptp_over_sigma"].items()
               for signal, ratio in ratios.items() if ratio < 10]
        print(f"{name}: {len(grid_specs[key]['case']['runs'])} runs; low SNR (<10): {low or 'none'}")


if __name__ == "__main__":
    main()
