"""Checks for the true device models written as submissions (scorer/truth/). No ANDES: the closed-loop check that
a truth spec reproduces its grid's recordings is test_cases/score_wrong_models_on_grid.py (truth must score 0).

    python scorer/tests/test_truth_specs.py
"""
import json
import os
import sys

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPOSITORY_ROOT)
from scorer.score_components import droop_gains  # noqa: E402
from scorer.submission_parser import TerminalModel  # noqa: E402
from scorer.truth import TRUTH_SPEC_BUILDERS, truth_spec_for  # noqa: E402

passed = 0


def check(condition, description):
    global passed
    if not condition:
        raise AssertionError(description)
    passed += 1
    print("ok:", description)


def spec_params(grid):
    with open(os.path.join(REPOSITORY_ROOT, "test_cases", "grid_specs", f"grid_{grid}.json")) as file:
        return json.load(file)["device_under_test"]


def gains_at(spec, operating_point):
    linearization = TerminalModel(spec).linearize(operating_point)
    return linearization, droop_gains(linearization["A"], linearization["B"], linearization["C"], linearization["D"])[0]


OPERATING_POINTS = [[1.0, 0.3, 0.78, 0.05], [1.02, -0.4, 0.8, -0.1], [1.01, 0.0, 0.5, 0.2]]
regf1, regf2 = spec_params("A"), spec_params("A2")
check(regf1["model"] == "REGF1" and regf2["model"] == "REGF2", "grids A and A2 hold REGF1 and REGF2")
for grid in ("B2", "M2"):
    check(spec_params(grid) == regf2, f"grid {grid} holds the same REGF2 unit as A2")
check(all(regf1["params"][name] != regf2["params"][name] for name in ("wdrp", "Qdrp", "Tpm", "KPplim", "KIplim", "Tr")),
      "REGF2's six drawn parameters differ from REGF1's (seed 1, not 0)")

# 1. every truth spec parses and starts at rest wherever it is put
for device in (regf1, regf2):
    for inner_loop in ("full", "ideal"):
        spec = TRUTH_SPEC_BUILDERS[device["model"]](device["params"], inner_loop=inner_loop, rating_mva=device["rating_mva"])
        worst = max(max(TerminalModel(spec).linearize(point)["init_residual"],
                        TerminalModel(spec).linearize(point)["init_output_mismatch"]) for point in OPERATING_POINTS)
        check(worst < 1e-9, f"{device['model']} ({inner_loop} inner loop) is at rest at every operating point ({worst:.1e})")
model = TerminalModel(truth_spec_for("REGF2", regf2["params"], regf2["rating_mva"]))
check(len(model.state_names) == 16 and {"INTw", "xpll", "am"} <= set(model.state_names),
      "REGF2 has REGF1's 13 states plus the VSM lag and the PLL's two")

# 2. at DC the VSM lag drops out: with no PLL damping (dd = 0) REGF2's droops are REGF1's for the same parameters
point = OPERATING_POINTS[0]
shared = dict(regf2["params"])
_, regf1_gains = gains_at(TRUTH_SPEC_BUILDERS["REGF1"](shared), point)
_, undamped = gains_at(TRUTH_SPEC_BUILDERS["REGF2"](shared, parameter_scale={"dd": 0.0}), point)
check(abs(undamped["freq"] / regf1_gains["freq"] - 1) < 1e-6 and abs(undamped["volt"] / regf1_gains["volt"] - 1) < 1e-6,
      "with dd = 0, REGF2's steady-state droops equal REGF1's")
# with dd > 0 the PLL feeds the measured frequency back into the lag: dP/d(omega) shrinks by (1 - dd*wdrp)
_, damped = gains_at(TRUTH_SPEC_BUILDERS["REGF2"](shared), point)
expected = 1 - 0.11 * shared["wdrp"]
check(abs(damped["freq"] / regf1_gains["freq"] - expected) < 1e-6, f"dd = 0.11 scales dP/d(omega) by 1 - dd*wdrp = {expected:.6f}")

# 3. the VSM lag sits where REGF2's parameters put it: Tint = mf*wdrp
tint = regf2["params"]["mf"] * regf2["params"]["wdrp"]
check(0.05 < tint < 0.2, f"Tint = mf*wdrp = {tint:.4f} s, a VSM lag rather than REGF1's droop law")
fast = TRUTH_SPEC_BUILDERS["REGF2"](regf2["params"], parameter_scale={"mf": 0.001})
check(TerminalModel(fast).params["mf"] == regf2["params"]["mf"] * 0.001, "parameter_scale reaches REGF2's own parameters")

# 4. REGF3 (dVOC): the held-out device sits in A3, B3 and M3; REGF1's 13 states plus the vref2 integrator
regf3 = spec_params("A3")
check(regf3["model"] == "REGF3" and all(spec_params(grid) == regf3 for grid in ("B3", "M3")),
      "grids A3, B3 and M3 hold the same REGF3 unit")
check(all(regf3["params"][name] != other["params"][name] for other in (regf1, regf2)
          for name in ("wdrp", "Qdrp", "Tpm", "KPplim", "KIplim", "Tr")),
      "REGF3's six drawn parameters differ from REGF1's and REGF2's (seed 2)")
for inner_loop in ("full", "ideal"):
    spec = TRUTH_SPEC_BUILDERS["REGF3"](regf3["params"], inner_loop=inner_loop, rating_mva=regf3["rating_mva"])
    worst = max(max(TerminalModel(spec).linearize(point)["init_residual"],
                    TerminalModel(spec).linearize(point)["init_output_mismatch"]) for point in OPERATING_POINTS)
    check(worst < 1e-9, f"REGF3 ({inner_loop} inner loop) is at rest at every operating point ({worst:.1e})")
model = TerminalModel(truth_spec_for("REGF3", regf3["params"], regf3["rating_mva"]))
check(len(model.state_names) == 14 and "vref2" in model.state_names, "REGF3 has REGF1's 13 states plus vref2")
check(abs(model.params["Kdvoc"]) < 1e-8, f"ANDES's dVOC gain is negligible (Kdvoc = {model.params['Kdvoc']:.2e})")
# REGF3's P-f droop is REGF1's divided by vref2**2 = V0**2 in steady state; it has no Q-V droop (Q is held)
for point in OPERATING_POINTS:
    _, regf1_same = gains_at(TRUTH_SPEC_BUILDERS["REGF1"](regf3["params"]), point)
    _, dvoc = gains_at(TRUTH_SPEC_BUILDERS["REGF3"](regf3["params"]), point)
    check(abs(dvoc["freq"] / regf1_same["freq"] - point[0] ** 2) < 1e-6,
          f"at V0 = {point[0]}, REGF3's dP/d(omega) is REGF1's times V0**2")
    check(dvoc["volt"] is None, f"at V0 = {point[0]}, REGF3 has no steady-state Q-V gain (it returns Q to Q0)")
strong = TRUTH_SPEC_BUILDERS["REGF3"](regf3["params"], parameter_scale={"Kdvoc": 1e6})
check(TerminalModel(strong).params["Kdvoc"] == model.params["Kdvoc"] * 1e6, "parameter_scale reaches Kdvoc")

# 5. on REGF3's grids the droop component leaves the Q-V droop out (scorer/truth DROOPS_ABSENT)
from scorer.score_components import droop_error  # noqa: E402
from scorer.truth import DROOPS_ABSENT  # noqa: E402
check(DROOPS_ABSENT.get("REGF3") == ("volt",) and "REGF1" not in DROOPS_ABSENT and "REGF2" not in DROOPS_ABSENT,
      "only REGF3 lacks a droop, and only the Q-V one")
_, truth_gains = gains_at(TRUTH_SPEC_BUILDERS["REGF3"](regf3["params"]), OPERATING_POINTS[0])
_, droop_model = gains_at(TRUTH_SPEC_BUILDERS["REGF1"](regf3["params"]), OPERATING_POINTS[0])
both = droop_error(droop_model, truth_gains, absent=("volt",))
check(both["volt"] is None and both["mean"] == both["freq"], "a model with a Q-V droop is scored on its P-f droop alone")
exact = droop_error(truth_gains, truth_gains, absent=("volt",))
check(exact["mean"] == 0.0, "the truth itself scores 0 on the droop component")
same_as_before = droop_error(droop_model, droop_model)
check(same_as_before["mean"] == 0.0 and same_as_before["volt"] == 0.0, "with nothing absent the component is unchanged")

print(f"\nall {passed} checks passed")
