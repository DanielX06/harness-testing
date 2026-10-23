"""Score a terminal-model submission closed loop on held-out grids.

    python scorer/score_submission.py submission.json [--config scorer/config_min.json] [--out DIR] [--workers N]

For every held-out run on every grid, the submitted model replaces the device in the ANDES network, the
same disturbance is applied, and the device's terminal P and Q are compared with the clean recording.
The submission is JSON (equations as strings) and is never executed, so no sandbox is needed; ANDES runs
in parallel worker processes.

Per grid:  score = w_td * TD + w_fr * FR + w_par * PAR, each component capped at 2
           (a flat prediction scores 1.0 on every component, the true device 0, a failure 2)
Per role:  (1 - w) * mean + w * worst over that role's grids

Writes DIR/public.json and DIR/private.json. "public" means the selection grids only: it still holds FR
and PAR, which the RSI updater must never see, so rsi/updater_context.py reads only the composite, TD and
failures from it. private.json holds every grid (monitor and train_holdout included) and every detail.
DIR/andes/ (private) gets an ANDES log per simulation and, for each failed simulation, its last DEBUG
lines (*.debug.log, gitignored) and the trajectory up to the failure (*_partial.npz).

A submission the parser rejects, or that cannot be built into an ANDES model, scores 2 on every grid;
this script never exits with an error because of what a submission contains.
"""
import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the repository root
from scorer import andes_closed_loop, score_components, submission_parser  # noqa: E402
from scorer.score_components import FAILURE_SCORE  # noqa: E402
from scorer.scoring_grids import load_scoring_config  # noqa: E402

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_min.json")


@dataclass
class ScoreReport:
    public: dict        # selection grids only (public.json)
    private: dict       # every grid and every detail (private.json)


def _frequency_references(linearization, settings):
    """(frequency response on the scoring frequencies, droop gains, droop convergence) of a linearization."""
    frequencies = np.logspace(np.log10(settings["fr"]["f_min"]), np.log10(settings["fr"]["f_max"]), settings["fr"]["n"])
    matrices = [linearization[name] for name in "ABCD"]
    gains, convergence = score_components.droop_gains(*matrices, lowest_frequency_hz=settings["droop"]["f_lo_hz"])
    return score_components.frequency_response(*matrices, frequencies), gains, convergence


def _role_scores(grid_scores, worst_grid_weight):
    """{role: (1 - w) * mean + w * worst} over each role's grid scores."""
    by_role = {}
    for role, score in grid_scores:
        by_role.setdefault(role, []).append(score)
    return {role: round(float((1 - worst_grid_weight) * np.mean(scores) + worst_grid_weight * np.max(scores)), 4)
            for role, scores in by_role.items()}


def _report(grid_rows, settings, submission_path, structure, started, error=None):
    """grid_rows: (grid name, role, score, public entry, private entry) for each grid."""
    role_scores = _role_scores([(role, score) for _, role, score, _, _ in grid_rows], settings["worst_weight"])
    public = {"score": role_scores.get("selection"),
              "grids": {name: entry for name, role, _, entry, _ in grid_rows if role == "selection"},
              "submission_error": error}
    private = {"submission": os.path.abspath(submission_path), "role_scores": role_scores,
               "grids": {name: entry for name, _, _, _, entry in grid_rows},
               "structure": structure, "submission_error": error,
               "wall_seconds": round(time.monotonic() - started, 1), "settings": settings}
    return ScoreReport(public, private)


def _failed_everywhere(grids, failure_kind, detail):
    """Every grid scores the failure value, with one failure entry naming why."""
    entry = {"score": FAILURE_SCORE, "td": FAILURE_SCORE, "fr": FAILURE_SCORE, "par": FAILURE_SCORE,
             "failures": [{"task": "submission", "failure": failure_kind, "detail": detail[-600:]}]}
    return [(name, role, FAILURE_SCORE, entry, {**entry, "role": role}) for name, role in grids]


def failure_report(config_path, submission_path, failure_kind, detail):
    """A score report in which every grid failed, without running anything. The solver runner writes one when
    the scorer itself did not finish (failure_kind "scoring_timeout"), so the run still counts as a 2."""
    with open(config_path) as file:
        config = json.load(file)
    settings = {key: value for key, value in config.items() if key != "grids"}
    grids = [(entry["name"], entry["role"]) for entry in config["grids"]]
    return _report(_failed_everywhere(grids, failure_kind, detail), settings, submission_path, None,
                   time.monotonic(), error=detail[-600:])


class SubmissionScorer:
    """Scores submissions on the grids in one scorer config."""

    def __init__(self, config_path=DEFAULT_CONFIG, worker_count=None, andes_log_dir=None):
        """andes_log_dir: where each simulation's ANDES log (and, for a failure, its partial trajectory) goes.
        Private: give it a folder beside private.json, never one the RSI loop reads."""
        self.settings, self.grids = load_scoring_config(config_path)
        self.simulator = andes_closed_loop.ParallelSimulator(worker_count, self.settings["run_timeout_s"])
        self.andes_log_dir = andes_log_dir
        self._truth_references = {}

    def score(self, submission_path):
        started = time.monotonic()
        grid_names = [(grid.name, grid.role) for grid in self.grids]
        try:
            with open(submission_path, encoding="utf-8") as file:
                text = file.read()
            submission = json.loads(text)
            model = submission_parser.TerminalModel(submission)
        except Exception as error:                  # the submission's fault, whatever it is: it scores 2
            message = str(error) if isinstance(error, (submission_parser.SubmissionError, json.JSONDecodeError)) \
                else f"{type(error).__name__}: {error}"
            return _report(_failed_everywhere(grid_names, "invalid_submission", message), self.settings,
                           submission_path, None, started, error=message)
        structure = {"states": model.state_names, "params": model.params, "n_defs": len(model.defs)}

        submission_text = json.dumps(submission)    # keeps key order: defs are sequential
        class_name = andes_closed_loop.andes_class_name(submission_text)
        pycode_path = None
        try:
            try:
                andes_closed_loop.register_andes_class(model, class_name)
                pycode_path = andes_closed_loop.make_private_pycode_folder()
                andes_closed_loop.generate_numerical_code(pycode_path)
            except Exception as error:
                message = f"{type(error).__name__}: {error}"
                return _report(_failed_everywhere(grid_names, "codegen", message), self.settings, submission_path,
                               structure, started, error=str(error))
            finally:
                andes_closed_loop.unregister_andes_class(class_name)
            tasks = [{"id": f"{grid.name}__{run.name}", "builder_module": grid.builder_module, "run": run.name,
                      "case_spec_text": grid.case_spec_text, "end_time": float(run.times[-1]),
                      "time_step": float(run.times[1] - run.times[0]), "log_dir": self.andes_log_dir}
                     for grid in self.grids for run in grid.runs]
            results = self.simulator.run(tasks, submission_text, class_name, pycode_path)
        finally:
            if pycode_path:
                shutil.rmtree(os.path.dirname(pycode_path), ignore_errors=True)
        rows = [(grid.name, grid.role, *self._score_grid(grid, model, results)) for grid in self.grids]
        return _report(rows, self.settings, submission_path, structure, started)

    def _truth_frequency_references(self, grid):
        """(frequency response, droop gains) of the true device on a grid; computed once per grid."""
        if grid.name not in self._truth_references:
            linearization = submission_parser.TerminalModel(grid.truth_submission).linearize(grid.operating_point)
            response, gains, convergence = _frequency_references(linearization, self.settings)
            if any(value is None for value in gains.values()):
                raise RuntimeError(f"{grid.name}: truth droop gains did not converge {convergence}")
            self._truth_references[grid.name] = (response, gains)
        return self._truth_references[grid.name]

    def _score_grid(self, grid, model, results):
        """(score, public entry, private entry) for one grid, from the simulation results and the linearization."""
        failures, td_by_run, terminal_errors = [], {}, {}
        for run in grid.runs:
            result = results[f"{grid.name}__{run.name}"]
            if result["ok"]:
                n = min(len(result["P"]), len(run.times))
                predicted = np.column_stack([result["P"][:n], result["Q"][:n]])
                recorded = np.column_stack([run.clean_signals["P"][:n], run.clean_signals["Q"][:n]])
                td_by_run[run.name] = score_components.time_domain_error(predicted, recorded, grid.noise_sigmas,
                                                                         self.settings["td"]["floor_sigmas"])
                terminal_errors[run.name] = {
                    **{f"rmse_{signal}": float(np.sqrt(np.mean((result[signal][:n] - run.clean_signals[signal][:n]) ** 2)))
                       for signal in ("V", "theta")},
                    "seconds": round(result["seconds"], 1)}
            else:
                td_by_run[run.name] = {"P": FAILURE_SCORE, "Q": FAILURE_SCORE, "failure": result["failure"]}
                failures.append({"task": run.name, "failure": result["failure"], "detail": result.get("detail", "")})
        td = float(np.mean([errors[channel] for errors in td_by_run.values() for channel in ("P", "Q")]))

        true_response, true_gains = self._truth_frequency_references(grid)
        linearization_info = {}
        try:
            linearization = model.linearize(grid.operating_point)
            response, gains, convergence = _frequency_references(linearization, self.settings)
            if not np.all(np.isfinite(response)):
                raise ValueError("non-finite frequency response")
            fr_detail = score_components.frequency_response_error(response, true_response, self.settings["fr"]["floor_frac"])
            fr = fr_detail["mean"]
            linearization_info = {
                "n_states": int(linearization["A"].shape[0]), "init_residual": linearization["init_residual"],
                "init_output_mismatch": linearization["init_output_mismatch"],
                "max_real_eig_open_loop": (float(np.max(np.linalg.eigvals(linearization["A"]).real))
                                           if linearization["A"].size else None),
                "droop_convergence": convergence}
            for kind, gain in gains.items():
                if gain is None:
                    failures.append({"task": f"droop_{kind}", "failure": "no_steady_gain",
                                     "detail": "low-frequency gain did not converge (no droop, or a pure integrator)"})
        except Exception as error:
            fr, fr_detail, gains = FAILURE_SCORE, {"failure": "linearize"}, {}
            failures.append({"task": "linearize", "failure": "crash", "detail": f"{type(error).__name__}: {error}"[-400:]})
        par_detail = score_components.droop_error(gains, true_gains)
        par = par_detail["mean"]

        weights = self.settings["weights"]
        score = float(weights["td"] * td + weights["fr"] * fr + weights["par"] * par)
        nominal_frequency = grid.metadata.get("nominal_frequency_Hz", 60.0)
        public = {"score": round(score, 4), "td": round(td, 4), "fr": round(fr, 4), "par": round(par, 4),
                  "td_runs": {name: {"P": round(errors["P"], 4), "Q": round(errors["Q"], 4),
                                     **({"failure": errors["failure"]} if "failure" in errors else {})}
                              for name, errors in td_by_run.items()},
                  "fr_entries": {name: round(value, 4) for name, value in fr_detail.items() if name not in ("mean", "failure")},
                  "par_entries": {name: round(par_detail[name], 4) for name in ("freq", "volt")},
                  "failures": [{"task": failure["task"], "failure": failure["failure"], "detail": failure["detail"][-300:]}
                               for failure in failures]}
        private = {**public, "role": grid.role, "td_runs_full": td_by_run, "terminal_errors": terminal_errors,
                   "fr_detail": fr_detail, "par_detail": par_detail,
                   "droop_submission": score_components.droops_as_operators_read_them(gains, nominal_frequency),
                   "droop_truth": score_components.droops_as_operators_read_them(true_gains, nominal_frequency),
                   "gains_submission": gains, "gains_truth": true_gains, "linearization": linearization_info}
        return score, public, private


def write_score_files(report, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for name, content in (("public", report.public), ("private", report.private)):
        with open(os.path.join(out_dir, f"{name}.json"), "w") as file:
            json.dump(content, file, indent=1, default=float)


def main():
    parser = argparse.ArgumentParser(description="Score a submission closed loop on the grids in a scorer config.")
    parser.add_argument("submission")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--out", default=None, help="folder for public.json and private.json")
    parser.add_argument("--workers", type=int, default=None, help="ANDES simulations at once")
    options = parser.parse_args()
    import logging
    import andes
    log_dir = os.path.join(options.out, "andes") if options.out else None
    if log_dir:                                     # code generation's log; each worker writes its own
        os.makedirs(log_dir, exist_ok=True)
        andes.config_logger(stream_level=40, log_path=log_dir, log_file="codegen.log", file_level=logging.INFO)
    else:
        andes.config_logger(stream_level=40, file=False)
    report = SubmissionScorer(options.config, options.workers, log_dir).score(options.submission)
    print(json.dumps(report.public, indent=1))
    print("role scores (private):", report.private["role_scores"], f"in {report.private['wall_seconds']} s")
    if options.out:
        write_score_files(report, options.out)


if __name__ == "__main__":
    main()
