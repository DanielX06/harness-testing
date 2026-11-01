"""Builds every rung of the information ladder: its harness (system.md, method.md, tools/) and, for the rungs
that add data columns, its copy of grid A's noise-free recordings.

    python information_ladder/build_ladder.py            # every rung; prints each harness fingerprint
    python information_ladder/build_ladder.py --check    # rebuild into a temporary folder and compare

The rungs are defined in RUNGS below. Each starts from harness_v0 and adds one kind of information. Harness
folders (rungs/<rung>/harness/) are small and committed; data folders (data/<name>/) are rebuilt from
test_cases/grid_A and ignored by git. Nothing here needs ANDES.
"""
import argparse
import filecmp
import json
import shutil
import sys
import tempfile
from pathlib import Path

LADDER_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = LADDER_DIR.parent
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(LADDER_DIR))
from common.harness_files import copy_harness, harness_fingerprint  # noqa: E402
from common.hidden_names import SIMULATOR_AND_DEVICE_NAMES  # noqa: E402
from common.project_paths import SOLVER_DATA_DIRS, STARTING_HARNESS_DIR, TEST_CASES_DIR  # noqa: E402

TOOL_SOURCES = LADDER_DIR / "harness_tools"
RUNGS_DIR = LADDER_DIR / "rungs"
DATA_DIR = LADDER_DIR / "data"
ANSWER_KEY = TEST_CASES_DIR / "grid_A" / "holdout" / "answer_key.json"

# ---- text added to harness_v0 ---------------------------------------------------------------------------
NETWORK_FACT = (
    "- Short-circuit study at the device terminal: at short time scales (tens of milliseconds) the rest of the "
    "network, seen from bus 3, behaves like a voltage source behind about 0.5 pu reactance on the device's 900 MVA "
    "rating (short-circuit ratio about 2). Slower behaviour (the generators' controls, machines swinging against "
    "each other) is not part of that equivalent. tools/grid_equivalent_replay.py uses it.")
DEVICE_LOG_FACT = (
    "- The device's own control log is attached to every recording: two extra columns, internal_angle_rad and "
    "internal_frequency_dev_rad_s, described in dataset.json. They are logged values, not inputs your model may "
    "use: a submission still takes only V, theta and Vset.")
INTERNAL_SIGNALS_FACT = (
    "- The device's internal control signals are attached to every recording as extra columns (internal angle and "
    "frequency, filtered power measurements, the outputs of its power loops, its inner voltage reference and its "
    "currents in its internal frame), each described in dataset.json. They are logged values, not inputs your model "
    "may use: a submission still takes only V, theta and Vset.")
MENU_FACT = (
    "- tools/structure_menu.py builds complete submissions from a menu of control blocks used in this kind of unit "
    "(how the internal angle moves, the reactive droop, the voltage control and the current loop). The device's own "
    "structure may or may not be one of them. tools/fit_structure.py fits a menu structure's parameters to the "
    "recordings.")
GIVEN_STRUCTURE_FACT = (
    "- The manufacturer documents the control structure, though not its gains and time constants. "
    "tools/structure_menu.py builds it (run python tools/structure_menu.py list): an internal angle driven by "
    "frequency droop with a PI power loop, a reactive droop with a PI reactive loop feeding the voltage reference, "
    "a PI voltage loop in the internal frame and a PI current loop behind a filter reactance. "
    "tools/fit_structure.py fits its parameters to the recordings.")

UNDOCUMENTED_STRUCTURE = "Its control structure, gains and time constants are not documented."

GRID_CHECK_STEP = (
    "4. Check each candidate as close to how it will be scored as you can: python tools/grid_equivalent_replay.py "
    "submission.json val/<file>.csv. It runs your model against a source behind the network's short-circuit "
    "reactance, built from the recording so that the real device would reproduce the recording exactly, so your "
    "model's P and Q move V and theta the way the grid does at short time scales. The open-loop replay in "
    "tools/check_submission.py holds V and theta at their measured values instead; a model whose control is only "
    "damped through the network can diverge there even when it is right, so trust the grid-equivalent numbers when "
    "the two disagree. A model that reacts too strongly can still destabilize the full grid.")
V0_CHECK_STEP_START = "4. Check each candidate as close to how it will be scored as you can:"
FINAL_STEP = (
    "7. Write the model to submission.json. Run python tools/check_submission.py submission.json val/<file>.csv on "
    "each validation file to confirm it parses and starts at rest, and python tools/grid_equivalent_replay.py "
    "submission.json val/<file>.csv for the errors. Fix anything they report, and then submit.")
MENU_METHOD = """HOW TO WORK
1. Read runs.json and dataset.json, then look at the data before fitting anything. Check what moves after each event and on what time scales, how the device's P and Q relate to V, theta and the voltage setpoint, and how large the noise is.
2. Run python tools/structure_menu.py list. Decide from what the data show which structures are plausible: how P settles after a frequency event, whether Q follows the voltage setpoint with a droop, how fast the first response is.
3. Fit each candidate with python tools/fit_structure.py --pf ... --qv ... --voltage ... [--inner ...] --files <train file>:<from>:<to> ... --out fit_<name>.json. Use short windows (a few seconds) that start at t = 0 or just before an event and include events that excite both paths: staged voltage-reference steps for the reactive side, load or generator events for the frequency side. One call stops after about 100 s and saves the best parameters so far; repeat it with --start fit_<name>.json until the cost stops falling.
4. Build the fitted structure with python tools/structure_menu.py build ... --params fit_<name>.json --out cand_<name>.json and check it on every validation file with python tools/grid_equivalent_replay.py cand_<name>.json val/<file>.csv. That replay runs the model against a source behind the network's short-circuit reactance, so its P and Q move V and theta the way the grid does at short time scales.
5. Compare candidates on the validation errors, not the fit cost. Between two that do about equally well, keep the simpler one. Note any parameter that is poorly identified or trades off against another one.
6. You may also edit a built submission by hand, or write your own model, if no menu structure fits.
7. Copy the chosen model to submission.json. Run python tools/check_submission.py submission.json val/<file>.csv on each validation file to confirm it parses and starts at rest, fix anything it reports, and then submit.
"""
GIVEN_STRUCTURE_METHOD = MENU_METHOD.replace(
    "2. Run python tools/structure_menu.py list. Decide from what the data show which structures are plausible: "
    "how P settles after a frequency event, whether Q follows the voltage setpoint with a droop, how fast the first "
    "response is.",
    "2. Run python tools/structure_menu.py list. It offers only the documented structure; your job is its parameters.",
).replace("Fit each candidate", "Fit it").replace(
    "5. Compare candidates on the validation errors, not the fit cost. Between two that do about equally well, keep "
    "the simpler one.",
    "5. Judge fits on the validation errors, not the fit cost. Try more than one set of windows or starting values "
    "if the validation errors stay high.")

MENU_ALL = {"pf": ["droop", "droop_with_power_loop", "inertia"],
            "qv": ["droop", "droop_with_reactive_loop", "none"],
            "voltage": ["pi_voltage_loop", "voltage_behind_reactance"],
            "inner": ["ideal", "pi_current_loop"]}
# the true device's blocks taken out: what is left are 12 structures, none of them the device's
MENU_WITHOUT_TRUE = {"pf": ["droop", "inertia"], "qv": ["droop", "none"],
                     "voltage": ["pi_voltage_loop", "voltage_behind_reactance"], "inner": ["ideal", "pi_current_loop"]}
MENU_TRUE_ONLY = {"pf": ["droop_with_power_loop"], "qv": ["droop_with_reactive_loop"],
                  "voltage": ["pi_voltage_loop"], "inner": ["pi_current_loop"]}

GRID_TOOLS = ["grid_equivalent_replay.py"]
MENU_TOOLS = GRID_TOOLS + ["structure_menu.py", "fit_structure.py"]

# rung -> what it adds. data: None (harness_v0's data) or the name of a data variant built below.
RUNGS = {
    "r1_grid_equivalent": {"about": "the network's short-circuit reactance, and a checker that runs the model "
                                    "against it (realistic: an operator has the network model)",
                           "facts": [NETWORK_FACT], "tools": GRID_TOOLS, "data": None},
    "r2_device_log": {"about": "r1 plus the device's logged internal angle and frequency (borderline)",
                      "facts": [NETWORK_FACT, DEVICE_LOG_FACT], "tools": GRID_TOOLS, "data": "device_log"},
    "r3_internal_signals": {"about": "r1 plus every internal control signal (oracle)",
                            "facts": [NETWORK_FACT, INTERNAL_SIGNALS_FACT], "tools": GRID_TOOLS,
                            "data": "internal_signals"},
    "r4_menu_with_true": {"about": "r1 plus a menu of 27 structures that includes the true one, and a fitter",
                          "facts": [NETWORK_FACT, MENU_FACT], "tools": MENU_TOOLS, "data": None, "menu": MENU_ALL},
    "r5_menu_without_true": {"about": "r1 plus the same menu with the true blocks removed (12 structures)",
                             "facts": [NETWORK_FACT, MENU_FACT], "tools": MENU_TOOLS, "data": None,
                             "menu": MENU_WITHOUT_TRUE},
    "r6_structure_given": {"about": "r1 plus the true structure with unknown parameters, and a fitter (oracle)",
                           "facts": [NETWORK_FACT, GIVEN_STRUCTURE_FACT], "tools": MENU_TOOLS, "data": None,
                           "menu": MENU_TRUE_ONLY},
}


def check_names(folder):
    """Nothing the solver gets may name the simulator, the case or the device (as test_cases checks)."""
    for path in Path(folder).rglob("*"):
        if "__pycache__" in path.parts:
            continue
        if SIMULATOR_AND_DEVICE_NAMES.search(path.name):
            raise AssertionError(f"forbidden word in {path}")
        if path.is_file() and path.suffix in (".json", ".md", ".py", ".txt"):
            match = SIMULATOR_AND_DEVICE_NAMES.search(path.read_text())
            if match:
                raise AssertionError(f"forbidden word {match.group(0)!r} in {path}")


def v0_method_with_grid_check():
    """harness_v0's method.md with its step 4 and step 7 pointed at the grid-equivalent replay."""
    lines = (STARTING_HARNESS_DIR / "method.md").read_text().splitlines()
    out = []
    for line in lines:
        if line.startswith(V0_CHECK_STEP_START):
            out.append(GRID_CHECK_STEP)
        elif line.startswith("7. "):
            out.append(FINAL_STEP)
        else:
            out.append(line)
    if GRID_CHECK_STEP not in out or FINAL_STEP not in out:
        raise AssertionError("harness_v0/method.md changed: update build_ladder.py's step replacements")
    return "\n".join(out) + "\n"


def build_harness(rung, spec, target):
    if target.exists():
        shutil.rmtree(target)
    copy_harness(STARTING_HARNESS_DIR, target)
    system = (STARTING_HARNESS_DIR / "system.md").read_text().rstrip("\n")
    if spec.get("menu") is MENU_TRUE_ONLY:
        if UNDOCUMENTED_STRUCTURE not in system:
            raise AssertionError("harness_v0/system.md changed: update UNDOCUMENTED_STRUCTURE in build_ladder.py")
        system = system.replace(UNDOCUMENTED_STRUCTURE, "Its gains and time constants are not documented.")
    (target / "system.md").write_text(system + "\n" + "\n".join(spec["facts"]) + "\n")
    if "menu" in spec:
        method = GIVEN_STRUCTURE_METHOD if spec["menu"] is MENU_TRUE_ONLY else MENU_METHOD
    else:
        method = v0_method_with_grid_check()
    (target / "method.md").write_text(method)
    for tool in spec["tools"]:
        shutil.copyfile(TOOL_SOURCES / tool, target / "tools" / tool)
    if "menu" in spec:
        (target / "tools" / "menu_options.json").write_text(json.dumps(spec["menu"], indent=1) + "\n")
    check_names(target)
    return harness_fingerprint(target)


def build_data(variant, target):
    """Grid A's noise-free recordings with internal-signal columns added."""
    import numpy as np
    import pandas as pd
    from internal_signals import DEVICE_LOG_COLUMNS, INTERNAL_SIGNAL_COLUMNS, reconstruct_internal_signals
    columns = DEVICE_LOG_COLUMNS if variant == "device_log" else INTERNAL_SIGNAL_COLUMNS
    source = Path(SOLVER_DATA_DIRS["clean"])
    params_used = json.loads(ANSWER_KEY.read_text())["params_used"]
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    runs = json.loads((source / "runs.json").read_text())
    for run in runs.values():
        table = pd.read_csv(source / run["file"])
        signals = reconstruct_internal_signals(table, params_used)
        for column in columns:
            table[column] = signals[column]
        (target / run["file"]).parent.mkdir(exist_ok=True)
        table.to_csv(target / run["file"], index=False, float_format="%.9g")
        assert np.all(np.isfinite(table.to_numpy(float))), run["file"]
    shutil.copyfile(source / "runs.json", target / "runs.json")
    shutil.copyfile(source / "system_diagram.png", target / "system_diagram.png")
    dataset = json.loads((source / "dataset.json").read_text())
    dataset["columns"].update(columns)
    dataset["notes"] += " The extra columns come from the device's own control log and carry no noise."
    (target / "dataset.json").write_text(json.dumps(dataset, indent=2))
    check_names(target)


def build_everything(rungs_dir, data_dir, with_data=True):
    fingerprints = {}
    for rung, spec in RUNGS.items():
        fingerprints[rung] = build_harness(rung, spec, rungs_dir / rung / "harness")
    if with_data:
        for variant in sorted({spec["data"] for spec in RUNGS.values() if spec["data"]}):
            build_data(variant, data_dir / variant)
    return fingerprints


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="rebuild elsewhere and compare with the committed harnesses")
    parser.add_argument("--no-data", action="store_true", help="harnesses only")
    options = parser.parse_args()
    if options.check:
        with tempfile.TemporaryDirectory() as folder:
            build_everything(Path(folder) / "rungs", Path(folder) / "data", with_data=False)
            for rung in RUNGS:
                comparison = filecmp.dircmp(Path(folder) / "rungs" / rung / "harness", RUNGS_DIR / rung / "harness",
                                            ignore=["__pycache__", ".DS_Store"])
                differ = comparison.diff_files + comparison.left_only + comparison.right_only
                for sub in comparison.subdirs.values():
                    differ += sub.diff_files + sub.left_only + sub.right_only
                print(f"{rung}: {'matches' if not differ else 'DIFFERS: ' + ', '.join(differ)}")
        return
    fingerprints = build_everything(RUNGS_DIR, DATA_DIR, with_data=not options.no_data)
    print(f"r0_v0 (harness_v0/harness, unchanged): {harness_fingerprint(STARTING_HARNESS_DIR)}")
    for rung, fingerprint in fingerprints.items():
        data = RUNGS[rung]["data"]
        print(f"{rung}: {fingerprint}   data: {'data/' + data if data else 'grid A noise-free (as harness_v0)'}")


if __name__ == "__main__":
    main()
