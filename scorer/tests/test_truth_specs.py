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

print(f"\nall {passed} checks passed")
