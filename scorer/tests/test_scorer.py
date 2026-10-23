"""Closed-loop checks of the scorer in ANDES. Plain script, no pytest needed.

    python scorer/tests/test_scorer.py [--quick] [--config scorer/config_min.json]

1. the flat baseline scores exactly 1.0 on every component
2. the true REGF1 written as a submission scores 0 (the ceiling), closed loop in ANDES, including runs with
   staged voltage-reference steps (the scorer steps the submission's Vset)
3. REGF1 with the current loop made ideal scores close to 0
4. the true model with wdrp or Qdrp scaled scores worse the further the scale is from 1 (skipped by --quick)
5. invalid submissions, code injection and a timeout each score 2; a destabilizing model crashes ANDES on
   every disturbance it sees and never beats flat
Each closed-loop score takes one to three minutes (every held-out run is a full ANDES simulation).
scorer/tests/test_submission_parser.py has the fast checks that need no ANDES.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPOSITORY_ROOT)
from scorer.score_submission import SubmissionScorer  # noqa: E402
from scorer.truth import regf1_as_submission  # noqa: E402

BROKEN_SUBMISSIONS = {
    "not_json": "{this is not json",
    "unknown_name": json.dumps({"states": {}, "outputs": {"P": "P0 + Kx*(V - V0)", "Q": "Q0"}}),
    "code_injection": json.dumps({"states": {}, "outputs": {"P": "__import__('os').system('echo hi')", "Q": "Q0"}}),
    "attribute_access": json.dumps({"states": {}, "outputs": {"P": "P0.real", "Q": "Q0"}}),
    "wrong_argument_count": json.dumps({"states": {}, "outputs": {"P": "sin()", "Q": "Q0"}}),
    # unstable through the network on any grid: extra Q raises V, which grows x further
    "destabilizing": json.dumps({"params": {"a": 5.0}, "states": {"x": {"rhs": "a*x + 10*(V - V0)", "init": "0"}},
                                 "outputs": {"P": "P0", "Q": "Q0 + x"}}),
}
passed_all = True


def check(name, condition, message=""):
    global passed_all
    print(f"  [{'PASS' if condition else 'FAIL'}] {name} {message}")
    passed_all &= bool(condition)


def selection_grid(public):
    return next(iter(public["grids"].values()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.path.join(REPOSITORY_ROOT, "scorer", "config_min.json"))
    parser.add_argument("--quick", action="store_true", help="skip the sensitivity sweep")
    options = parser.parse_args()

    import andes
    andes.config_logger(stream_level=40)
    with open(options.config) as file:
        config = json.load(file)
    config_dir = os.path.dirname(os.path.abspath(options.config))
    answer_key = os.path.join(os.path.normpath(os.path.join(config_dir, config["grids"][0]["path"])), "holdout",
                              "answer_key.json")
    scorer = SubmissionScorer(options.config)
    folder = tempfile.mkdtemp(prefix="scorer_test_")
    try:
        print("1. flat baseline")
        report = scorer.score(os.path.join(REPOSITORY_ROOT, "scorer", "baselines", "flat.json"))
        grid = selection_grid(report.public)
        check("flat", all(abs(grid[component] - 1.0) < 1e-9 for component in ("td", "fr", "par")),
              f"td {grid['td']} fr {grid['fr']} par {grid['par']} ({report.private['wall_seconds']} s)")

        print("2. true REGF1 (13 states) as a submission: the ceiling")
        report = scorer.score(regf1_as_submission.write_truth_spec(os.path.join(folder, "full.json"), answer_key, "full"))
        grid = selection_grid(report.public)
        terminal_errors = next(iter(report.private["grids"].values()))["terminal_errors"]
        check("truth", grid["score"] < 1e-3, f"score {grid['score']} td {grid['td']} fr {grid['fr']} par {grid['par']}; "
                                             f"V/theta RMSE {terminal_errors}")

        print("3. REGF1 with an ideal current loop (9 states)")
        report = scorer.score(regf1_as_submission.write_truth_spec(os.path.join(folder, "ideal.json"), answer_key, "ideal"))
        grid = selection_grid(report.public)
        check("ideal loop", grid["score"] < 0.05, f"score {grid['score']} td {grid['td']} fr {grid['fr']} par {grid['par']}")

        if not options.quick:
            print("4. sensitivity (true structure, one parameter scaled)")
            params_used = json.load(open(answer_key))["params_used"]
            for param in ("wdrp", "Qdrp"):
                rows = []
                for scale in (0.8, 1.0, 1.25):
                    path = os.path.join(folder, f"{param}_{scale}.json")
                    json.dump(regf1_as_submission.regf1_truth_spec(params_used, "full", parameter_scale={param: scale}),
                              open(path, "w"))
                    grid = selection_grid(scorer.score(path).public)
                    rows.append((scale, grid["score"]))
                    print(f"     {param} x{scale:<5} score {grid['score']:.4f}  td {grid['td']:.4f}  "
                          f"fr {grid['fr']:.4f}  par {grid['par']:.4f}")
                check(param, rows[0][1] > rows[1][1] < rows[2][1])

        print("5. failures")
        for name, text in BROKEN_SUBMISSIONS.items():
            path = os.path.join(folder, f"{name}.json")
            open(path, "w").write(text)
            grid = selection_grid(scorer.score(path).public)
            kinds = sorted({failure["failure"] for failure in grid["failures"]})
            if name != "destabilizing":
                condition = grid["score"] == 2.0
            else:
                # every run with a network disturbance crashes ANDES; a voltage-reference run is a no-op for a
                # model that ignores Vset, so it scores exactly like flat (1.0)
                runs = grid["td_runs"].values()
                condition = (any(run.get("failure") in ("tds_failed", "unstable", "nan") for run in runs)
                             and all(min(run["P"], run["Q"]) >= 1.0 for run in runs))
            check(name, condition, f"score {grid['score']} td {grid['td']} failures {kinds}")
        fast = dict(config, run_timeout_s=3.0)
        for entry in fast["grids"]:
            entry["path"] = os.path.normpath(os.path.join(config_dir, entry["path"]))
        fast_config = os.path.join(folder, "fast.json")
        json.dump(fast, open(fast_config, "w"))
        grid = selection_grid(SubmissionScorer(fast_config).score(
            os.path.join(REPOSITORY_ROOT, "scorer", "baselines", "flat.json")).public)
        check("timeout", grid["td"] == 2.0 and {failure["failure"] for failure in grid["failures"]} == {"timeout"},
              f"td {grid['td']} failures {[failure['failure'] for failure in grid['failures']]}")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print("ALL PASS" if passed_all else "SOME CHECKS FAILED")
    sys.exit(0 if passed_all else 1)


if __name__ == "__main__":
    main()
