"""Fast checks of the parser and the score arithmetic. No ANDES needed (the simulations are replaced by
fixed trajectories), so this runs in seconds anywhere numpy, pandas and sympy are installed.

    python scorer/tests/test_submission_parser.py
"""
import json
import os
import sys

import numpy as np

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPOSITORY_ROOT)
from scorer import score_components  # noqa: E402
from scorer.score_submission import SubmissionScorer  # noqa: E402
from scorer.submission_parser import SubmissionError, TerminalModel  # noqa: E402
from scorer.truth import truth_spec_for  # noqa: E402

GRID_B_KEY = os.path.join(REPOSITORY_ROOT, "test_cases", "grid_B", "holdout", "answer_key.json")
FLAT = os.path.join(REPOSITORY_ROOT, "scorer", "baselines", "flat.json")
passed = 0


def check(condition, description):
    global passed
    if not condition:
        raise AssertionError(description)
    passed += 1
    print("ok:", description)


def rejected(submission, expected_text):
    try:
        TerminalModel(submission)
    except SubmissionError as error:
        return expected_text in str(error)
    return False


def outputs(p_expression, q_expression="Q0", **extra):
    return {"outputs": {"P": p_expression, "Q": q_expression}, **extra}


# 1. what a submission cannot do, rejected with a SubmissionError (the scorer scores those 2, never crashes)
check(rejected(outputs("__import__('os').system('echo hi')"), "only calls to"), "code injection is rejected")
check(rejected(outputs("P0.real"), "'Attribute' not allowed"), "attribute access is rejected")
check(rejected(outputs("P0 + Kx*(V - V0)"), "unknown name 'Kx'"), "an unknown name is rejected")
check(rejected(outputs("sin()"), "sin takes 1 argument, got 0"), "a function with too few arguments is rejected")
check(rejected(outputs("atan2(V)"), "atan2 takes 2 arguments, got 1"), "atan2 with one argument is rejected")
check(rejected(outputs("Min()"), "Min takes at least 1 argument"), "Min with no arguments is rejected")
check(rejected(outputs("10**10**10"), "exponent 10000000000 is larger than"), "a huge numeric power is rejected")
check(rejected(outputs("P0", params={"k": 10 ** 400}), "param k must be a finite number"), "an overflowing param is rejected")
check(rejected(outputs("P0", params=["k"]), '"params" must be a JSON object'), "params given as a list are rejected")
check(rejected(outputs("P0\x00"), "contains a null byte"), "a null byte is rejected, with the same message on every Python")
chain = {"d1": "V*theta", **{f"d{k}": f"d{k - 1}*sin(d{k - 1})" for k in range(2, 41)}}
check(rejected({"defs": chain, "outputs": {"P": "P0 + 1e-9*d40", "Q": "Q0"}}, "once its defs are substituted in"),
      "a chain of defs that doubles at every step is rejected before it is written out")
inits = {f"x{k}": {"rhs": "0", "init": f"x{k - 1}*x{k - 1} + sin(x{k - 1})" if k else "P0"} for k in range(40)}
check(rejected({"states": inits, "outputs": {"P": "P0", "Q": "Q0"}}, "the other states' inits"),
      "a chain of inits that doubles at every step is rejected")
check(rejected({"states": {"x": {"rhs": "0", "init": "y"}, "y": {"rhs": "0", "init": "x"}},
                "outputs": {"P": "P0", "Q": "Q0"}}, "circular"), "circular inits are rejected")

# 2. unusual but valid expressions still parse
for expression in ("log(V, 10)", "Max(V, P0, Q0)", "P0 + 0*2**100", "V" + "+V" * 1999):
    TerminalModel(outputs(expression))
check(True, "log with a base, Max of three, a large integer power and a 2000-term sum all parse")

# 3. the true device: at rest at the operating point, with the answer key's droops
answer_key = json.load(open(GRID_B_KEY))
truth = TerminalModel(truth_spec_for(answer_key["device"], answer_key["params_used"], answer_key["device_rating_MVA"]))
scorer = SubmissionScorer(os.path.join(REPOSITORY_ROOT, "scorer", "config_min.json"))
grid_b = next(grid for grid in scorer.grids if grid.name == "grid_B")
linearization = truth.linearize(grid_b.operating_point)
check(linearization["init_residual"] < 1e-9 and linearization["init_output_mismatch"] < 1e-9,
      "the true device starts at rest at grid B's operating point")
gains, _ = score_components.droop_gains(*[linearization[name] for name in "ABCD"])
expected = answer_key["truth_droops_per_op"]["opB"]["gains"]
# the answer key's droops were computed when the case was built, so they agree to about 1e-5, not exactly
check(all(abs(gains[kind] - expected[kind]) <= 1e-4 * abs(expected[kind]) for kind in ("freq", "volt")),
      f"the true droops match the answer key ({gains})")
bound = truth.bind(grid_b.operating_point)
start = bound.initial_state()
check(np.max(np.abs(bound.state_derivative(0.0, start, grid_b.operating_point[:2]))) < 1e-9,
      "the numeric (bound) model is at rest at its initial state too")


# 4. the normalization contract, with the simulations replaced by fixed trajectories
def simulated(prediction):
    """Every held-out run 'simulated' with prediction(run) giving (P, Q)."""
    results = {}
    for grid in scorer.grids:
        for run in grid.runs:
            p, q = prediction(run)
            results[f"{grid.name}__{run.name}"] = {"ok": True, "t": run.times, "P": p, "Q": q,
                                                   "V": run.clean_signals["V"], "theta": run.clean_signals["theta"],
                                                   "seconds": 1.0}
    return results


exact = simulated(lambda run: (run.clean_signals["P"], run.clean_signals["Q"]))
score, public, _ = scorer._score_grid(grid_b, truth, exact)
check(score == 0 and public["td"] == 0 and public["fr"] == 0 and public["par"] == 0, "the true device scores 0")
flat_model = TerminalModel(json.load(open(FLAT)))
frozen = simulated(lambda run: (np.full_like(run.times, run.clean_signals["P"][0]),
                                np.full_like(run.times, run.clean_signals["Q"][0])))
score, public, _ = scorer._score_grid(grid_b, flat_model, frozen)
check(abs(public["td"] - 1) < 1e-9 and abs(public["fr"] - 1) < 1e-9 and abs(public["par"] - 1) < 1e-9,
      f"the flat prediction scores 1 on every component (td {public['td']}, fr {public['fr']}, par {public['par']})")
failed = dict(exact, **{f"grid_B__{run.name}": {"ok": False, "failure": "tds_failed", "detail": "x"} for run in grid_b.runs})
score, public, _ = scorer._score_grid(grid_b, truth, failed)
check(public["td"] == 2 and all(value.get("failure") == "tds_failed" for value in public["td_runs"].values()),
      "a failed simulation scores 2 on both channels of that run")

print(f"\nall {passed} checks passed")
