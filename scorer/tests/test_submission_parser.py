"""Fast checks of the parser and the score arithmetic. No ANDES needed (the simulations are replaced by
fixed trajectories), so this runs in seconds anywhere numpy, pandas and sympy are installed.

    python scorer/tests/test_submission_parser.py
"""
import inspect
import json
import os
import sys

import numpy as np
import sympy as sp
from sympy.core.function import AppliedUndef

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPOSITORY_ROOT)
from scorer import andes_closed_loop, score_components  # noqa: E402
from scorer.score_submission import SubmissionScorer  # noqa: E402
from scorer.submission_parser import ALLOWED_FUNCTIONS, SubmissionError, TerminalModel  # noqa: E402
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


# 6. every whitelisted function survives ANDES's code generation. ANDES lambdifies each model's equations and
# Jacobian with sympy's numpy printer and writes the source into a pycode .py file under a fixed header (copied here
# from andes/core/symprocessor.py, ANDES 2.0) that ends with `from andes.thirdparty.npfunc import *`; the scorer adds
# andes_closed_loop.GENERATED_CODE_EXTRAS to npfunc. A name the printer uses that neither provides is a NameError in
# every simulation: until Oct 31 tanh, Abs, Min and Max all failed this way. Emulated here without ANDES (inputs as
# one-entry arrays, as ANDES passes them); check 6 of scorer/tests/test_scorer.py runs the same functions in ANDES.
ANDES_PYCODE_HEADER = """
from numpy import ones_like, zeros_like, full, array
from numpy import nan, pi, sin, cos, tan, sqrt, exp, select
from numpy import greater_equal, less_equal, greater, less, equal
from numpy import logical_and, logical_or, logical_not
from numpy import real, imag, conj, angle, radians, abs
from numpy import arcsin, arccos, arctan, arctan2
from numpy import log
def safe_div(a, b, out=None):   # andes.thirdparty.npfunc
    return a / b
"""
FUNCTION_USES = {"sin": "sin(theta - x)", "cos": "cos(theta - x)", "tan": "tan(0.1*(theta - x))", "exp": "exp(-x)",
                 "log": "log(V + 1) + log(V + 1, 10)", "sqrt": "sqrt(V)", "tanh": "tanh(3*(V - x))",
                 "atan": "atan(V - x)", "atan2": "atan2(V, x + 1)", "Abs": "Abs(V - x)",
                 "Min": "Min(V, x) + Min(V, x, 1.2)", "Max": "Max(Min(V, 1.1), x) + Max(V, x, 0.9)"}
check(set(FUNCTION_USES) == set(ALLOWED_FUNCTIONS), "the code-generation check covers every whitelisted function")


def generated_code_problem(model, extras):
    """Print the outputs and state equations as the scorer does, lambdify them and their Jacobian as ANDES does,
    exec the source under the pycode header plus `extras`, and call it. '' if it runs and the outputs and state
    equations match sympy's own values, else what went wrong."""
    printed = andes_closed_loop._to_andes_names(model)
    texts = [printed(model.outputs["P"]), printed(model.outputs["Q"])]
    texts += [printed(model.state_derivatives[name]) for name in model.state_names]
    expressions = [sp.sympify(text) for text in texts]
    unknown = sorted({str(call.func) for expression in expressions for call in expression.atoms(AppliedUndef)})
    if unknown:
        return f"unknown functions in the printed equations: {unknown}"
    names = sorted({str(symbol) for expression in expressions for symbol in expression.free_symbols})
    real = {name: sp.Symbol(name, real=True) for name in names}            # ANDES's DAE variables are real
    expressions = [expression.xreplace({sp.Symbol(name): real[name] for name in names}) for expression in expressions]
    jacobian = [sp.diff(expression, real[name]) for expression in expressions for name in names]
    function = sp.lambdify([real[name] for name in names], tuple(expressions + jacobian), modules=[{}, "numpy"])
    source = inspect.getsource(function).replace("def _lambdifygenerated(", "def generated(")
    namespace = {}
    exec(ANDES_PYCODE_HEADER, namespace)
    namespace.update(extras)                                                # what the star import brings in
    exec(source, namespace)
    point = {real[name]: 0.37 + 0.11 * k for k, name in enumerate(names)}
    try:
        values = namespace["generated"](*[np.array([point[real[name]]]) for name in names])
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    values = [np.asarray(value, dtype=float).ravel()[0] for value in values]
    if not all(np.isfinite(values)):
        return "non-finite values"
    expected = [float(expression.subs(point)) for expression in expressions]
    worst = max(abs(got - want) for got, want in zip(values, expected))
    return "" if worst < 1e-12 else f"values differ from sympy's by {worst:.1e}"


for name, use in FUNCTION_USES.items():
    model = TerminalModel({"params": {"T": 0.1}, "states": {"x": {"rhs": "(V - x)/T", "init": "V0"}},
                           "outputs": {"P": f"P0 + 0.1*({use})", "Q": "Q0 + (V - x)"}})
    problem = generated_code_problem(model, andes_closed_loop.GENERATED_CODE_EXTRAS)
    check(problem == "", f"{name} runs in ANDES's generated code{': ' + problem if problem else ''}")
    if name in ("tanh", "Abs", "Min", "Max"):
        check(generated_code_problem(model, {}).startswith("NameError"),
              f"without the extra names, {name} is still the NameError it was (so the check above tests the fix)")

print(f"\nall {passed} checks passed")
