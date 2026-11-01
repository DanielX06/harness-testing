"""Fit the parameters of a menu structure (tools/structure_menu.py) to recordings, by replaying them against the
grid equivalent (tools/grid_equivalent_replay.py) and minimizing the P and Q error.

    python tools/fit_structure.py --pf droop --qv droop --voltage pi_voltage_loop --inner ideal \\
        --files train/<a>.csv:0:8 train/<b>.csv:3:12 --out fit.json

Each --files entry is FILE:T_FROM:T_TO. The replay always starts at t = 0 (where the model is at rest) and runs
to T_TO; the error counts from T_FROM. Keep windows short (a few seconds around an event): every evaluation
replays every window. Each window's P and Q errors are divided by that window's flat-prediction error, so
every window and channel weighs the same.

A call stops after --seconds (default 100, under the 120 s limit) and saves the best parameters so far to
--out. Run it again with --start <that file> to carry on. Parameters are fitted in log space, so they stay
positive; a parameter whose value is 0 (rf by default) and any named in --fix stay where they are.
Finally it builds submission.json-style output with structure_menu.py build --params <out>.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402

import grid_equivalent_replay as replay  # noqa: E402
import structure_menu as menu  # noqa: E402
import submission_parser  # noqa: E402

FAILED_RESIDUAL = 3.0          # per sample, in units of the flat error: a replay that fails costs this much
RESIDUAL_STRIDE = 10           # every Nth replayed sample enters the residual vector


class OutOfTime(Exception):
    pass


def parse_window(text):
    path, _, rest = text.partition(":")
    parts = rest.split(":") if rest else []
    t_from = float(parts[0]) if len(parts) > 0 and parts[0] else 0.0
    t_to = float(parts[1]) if len(parts) > 1 and parts[1] else None
    return path, t_from, t_to


def load_windows(entries, every):
    import pandas as pd
    windows = []
    for entry in entries:
        path, t_from, t_to = parse_window(entry)
        table = pd.read_csv(path)
        if t_to is not None:
            table = table[table["time_s"] <= t_to + 1e-9].reset_index(drop=True)
        counted = table["time_s"].to_numpy(float)[::every] >= t_from - 1e-9
        measured = table[["active_power_pu", "reactive_power_pu"]].to_numpy(float)[::every]
        flat = np.sqrt(np.mean((measured[counted] - measured[0]) ** 2, axis=0))
        windows.append({"name": entry, "table": table, "counted": counted, "measured": measured,
                        "scale": np.maximum(flat, 1e-6)})
    return windows


class StructureFit:
    def __init__(self, choices, windows, reactance, every, start_params, fixed, deadline):
        self.choices, self.windows, self.reactance, self.every = choices, windows, reactance, every
        self.deadline = deadline
        defaults = menu.parameter_defaults(choices)
        self.params = {**defaults, **{name: float(value) for name, value in (start_params or {}).items()
                                      if name in defaults}}
        self.free = [name for name, value in self.params.items() if name not in fixed and value > 0]
        self.best = (np.inf, dict(self.params), None)
        self.evaluations = 0

    def window_errors(self, params):
        """Per window: (P error, Q error) as rmse / flat rmse; None for a window whose replay failed."""
        model = submission_parser.TerminalModel(menu.build_submission(self.choices, params))
        results = []
        for window in self.windows:
            try:
                result = replay.replay_recording(model, window["table"], self.reactance, self.every,
                                                 time_limit_s=max(1.0, self.deadline - time.monotonic()))
                replayed = np.column_stack([result["P"], result["Q"]])
                results.append((replayed - window["measured"]) / window["scale"])
            except replay.ReplayFailure as failure:
                if failure.kind == "timeout":
                    raise OutOfTime()
                results.append(None)
        return results

    def residual(self, log_values):
        if time.monotonic() > self.deadline:
            raise OutOfTime()
        params = dict(self.params)
        params.update({name: float(np.exp(value)) for name, value in zip(self.free, log_values)})
        self.evaluations += 1
        pieces = []
        for window, errors in zip(self.windows, self.window_errors(params)):
            size = int(np.count_nonzero(window["counted"][::RESIDUAL_STRIDE])) * 2
            if errors is None:
                pieces.append(np.full(size, FAILED_RESIDUAL))
            else:
                pieces.append(errors[window["counted"]][::RESIDUAL_STRIDE].ravel()
                              if size else np.zeros(0))
        vector = np.concatenate(pieces) if pieces else np.zeros(1)
        vector = vector / np.sqrt(max(vector.size, 1))
        cost = float(vector @ vector)
        if cost < self.best[0]:
            self.best = (cost, params, None)
        return vector

    def run(self):
        from scipy.optimize import least_squares
        start = np.log([self.params[name] for name in self.free])
        stopped = "converged"
        try:
            self.residual(start)
            least_squares(self.residual, start, method="trf", diff_step=1e-3, max_nfev=200 * (len(self.free) + 1))
        except OutOfTime:
            stopped = "out of time"
        return stopped


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fit a menu structure's parameters by grid-equivalent replay.")
    for slot in ("pf", "qv", "voltage"):
        parser.add_argument(f"--{slot}", required=True)
    parser.add_argument("--inner")
    parser.add_argument("--files", nargs="+", required=True, metavar="FILE:T_FROM:T_TO")
    parser.add_argument("--start", help="JSON with starting parameters (an earlier --out)")
    parser.add_argument("--out", default="fit.json")
    parser.add_argument("--fix", nargs="*", default=[], help="parameters to hold at their starting values")
    parser.add_argument("--x", type=float, default=replay.DEFAULT_REACTANCE, help="grid reactance, pu on the rating")
    parser.add_argument("--every", type=int, default=2, help="use every Nth sample (1 ms recordings)")
    parser.add_argument("--seconds", type=float, default=100.0)
    options = parser.parse_args(argv)
    started = time.monotonic()
    choices = menu.choices_from(options)
    try:
        menu.check_choices(choices)
    except menu.MenuError as error:
        print(f"ERROR: {error}")
        return 1
    start_params = None
    if options.start:
        with open(options.start) as file:
            loaded = json.load(file)
        start_params = loaded.get("params", loaded)
        if loaded.get("choices") not in (None, choices):
            print(f"note: {options.start} was fitted for {loaded.get('choices')}; using its matching parameters only")
    windows = load_windows(options.files, options.every)
    fit = StructureFit(choices, windows, options.x, options.every, start_params, set(options.fix),
                       started + options.seconds)
    stopped = fit.run()
    cost, params, _ = fit.best
    with open(options.out, "w") as file:
        json.dump({"choices": choices, "params": params, "cost": cost, "stopped": stopped,
                   "evaluations": fit.evaluations, "windows": options.files, "x": options.x, "every": options.every},
                  file, indent=1)
    print(f"{stopped} after {fit.evaluations} evaluations, {time.monotonic() - started:.0f} s; best cost {cost:.4g}")
    print(f"fitted parameters (saved to {options.out}): " + json.dumps({k: float(f'{v:.6g}') for k, v in params.items()}))
    print(f"free: {fit.free}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
