"""Checks for the information ladder. No API key, Docker or ANDES needed (numpy, scipy, pandas, sympy).

    python information_ladder/tests/test_ladder.py          # about 3 minutes

1. The menu's true combination, with the true parameters moved to the device base, is the truth model: same
   linearization, same replay to 1e-9 pu.
2. Every menu structure parses and starts at rest.
3. Grid-equivalent replay reproduces the recordings with the true model, where open-loop replay diverges, and
   it separates deliberately wrong versions of the truth.
4. The reconstructed internal signals agree with the true model's own states.
5. The committed rung harnesses match a fresh build, nothing names the simulator or the device, the data folders
   exist with the columns dataset.json lists, and run_rung.py hands the rung's data to the solver.
6. The tools work inside a sandbox filled the way the solver fills it: list, build, check, replay, a short fit.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

LADDER_DIR = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = LADDER_DIR.parent
sys.path[:0] = [str(REPOSITORY_ROOT), str(LADDER_DIR), str(LADDER_DIR / "harness_tools"),
                str(REPOSITORY_ROOT / "harness_v0" / "harness" / "tools")]
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import build_ladder  # noqa: E402
import grid_equivalent_replay as replay  # noqa: E402
import internal_signals  # noqa: E402
import run_rung  # noqa: E402
import structure_menu as menu  # noqa: E402
from common.project_paths import SUBMISSION_PARSER_FILE, TEST_CASES_DIR  # noqa: E402
from open_loop_replay import ReplayFailure, replay_open_loop  # noqa: E402
from scorer.score_components import droop_gains  # noqa: E402
from scorer.submission_parser import TerminalModel  # noqa: E402
from scorer.truth.regf1_as_submission import DEFAULT_PARAMS, regf1_truth_spec  # noqa: E402
from solver import solver_run  # noqa: E402
from solver.python_sandbox import LocalPythonSandbox  # noqa: E402

HOLDOUT = TEST_CASES_DIR / "grid_A" / "holdout"
KEY = json.loads((HOLDOUT / "answer_key.json").read_text())
TRUE_CHOICES = {"pf": "droop_with_power_loop", "qv": "droop_with_reactive_loop", "voltage": "pi_voltage_loop",
                "inner": "pi_current_loop"}
passed = 0


def check(condition, message):
    global passed
    if not condition:
        raise AssertionError(message)
    passed += 1
    print(f"ok  {message}")


def true_menu_params():
    """The truth's parameters on the device base (the truth works on the 100 MVA system base, k = 9)."""
    p = dict(DEFAULT_PARAMS)
    p.update(KEY["params_used"])
    k = KEY["device_rating_MVA"] / 100.0
    return dict(Tf=p["Tr"], m=p["wdrp"] * k, Tpl=p["Tpm"], Kpp=p["KPplim"], Kip=p["KIplim"], n=p["Qdrp"] * k,
                Tql=p["Tpm"], Kpq=p["KPqlim"], Kiq=p["KIqlim"], Kpv=p["KPv"] / k, Kiv=p["KIv"] / k, Kpi=p["KPi"] * k,
                Kii=p["KIi"] * k, Te=p["Te"], xf=0.2, rf=0.0)


def recording(name):
    return pd.read_csv(HOLDOUT / f"{name}_clean.csv")


def relative_errors(result):
    return {key: result["rmse"][key] / result["flat"][key] for key in ("P", "Q", "V")}


truth = TerminalModel(regf1_truth_spec(KEY["params_used"]))
operating_point = list(KEY["operating_point_per_run"]["A_val_vref_op2"].values())

# 1. the menu's true combination is the truth
true_menu = TerminalModel(menu.build_submission(TRUE_CHOICES, true_menu_params()))
truth_linear, menu_linear = truth.linearize(operating_point), true_menu.linearize(operating_point)
check(np.allclose(np.sort_complex(np.linalg.eigvals(truth_linear["A"])),
                  np.sort_complex(np.linalg.eigvals(menu_linear["A"])), atol=1e-6),
      "menu true combination has the truth's eigenvalues")
truth_gains = droop_gains(truth_linear["A"], truth_linear["B"], truth_linear["C"], truth_linear["D"])[0]
menu_gains = droop_gains(menu_linear["A"], menu_linear["B"], menu_linear["C"], menu_linear["D"])[0]
check(all(abs(menu_gains[key] / truth_gains[key] - 1) < 1e-3 for key in truth_gains),
      f"menu true combination has the truth's droops ({menu_gains} vs {truth_gains})")
vref = recording("A_val_vref_op2")
truth_replay = replay.replay_recording(truth, vref, 0.5, 1, 1000)
menu_replay = replay.replay_recording(true_menu, vref, 0.5, 1, 1000)
check(max(np.max(np.abs(truth_replay["P"] - menu_replay["P"])), np.max(np.abs(truth_replay["Q"] - menu_replay["Q"])))
      < 1e-9, "menu true combination replays like the truth to 1e-9 pu")

# 2. every structure parses and starts at rest
count = 0
for pf in menu.BLOCKS["pf"]:
    for qv in menu.BLOCKS["qv"]:
        for voltage in menu.BLOCKS["voltage"]:
            for inner in (menu.BLOCKS["inner"] if voltage == "pi_voltage_loop" else [None]):
                choices = {"pf": pf, "qv": qv, "voltage": voltage, **({"inner": inner} if inner else {})}
                linear = TerminalModel(menu.build_submission(choices)).linearize(operating_point)
                assert linear["init_residual"] < 1e-9 and linear["init_output_mismatch"] < 1e-9, choices
                count += 1
check(count == 27, "all 27 menu structures parse and start at rest")

# 3. grid-equivalent replay: the truth reproduces the recordings, open-loop replay does not, wrong models stand out
for name in ("A_val_vref_op2", "A_val_load_op1"):
    errors = relative_errors(replay.replay_recording(truth, recording(name), 0.5, 1, 1000))
    check(max(errors.values()) < 0.03, f"truth reproduces {name} against the grid equivalent ({errors})")
try:
    replay_open_loop(truth.bind(operating_point), vref["time_s"].to_numpy(),
                     vref[["voltage_pu", "bus_angle_rad", "voltage_setpoint_pu"]].to_numpy(), time_limit_s=200)
    open_loop_failed = False
except ReplayFailure:
    open_loop_failed = True
check(open_loop_failed, "open-loop replay of the truth diverges (why the grid-equivalent checker exists)")
truth_errors = relative_errors(truth_replay)
for scale in ({"Qdrp": 3.0}, {"wdrp": 2.0}, {"KPv": 0.3}):
    wrong = TerminalModel(regf1_truth_spec(KEY["params_used"], parameter_scale=scale))
    wrong_errors = relative_errors(replay.replay_recording(wrong, vref, 0.5, 1, 1000))
    check(max(wrong_errors.values()) > 10 * max(truth_errors.values()),
          f"truth with {scale} replays at least 10x worse ({max(wrong_errors.values()):.3f})")

# 4. internal signals agree with the truth's own states
signals = internal_signals.reconstruct_internal_signals(vref, KEY["params_used"])
index = {name: position for position, name in enumerate(truth.state_names)}
states, k = truth_replay["states"], KEY["device_rating_MVA"] / 100.0
for column, reference in (("internal_angle_rad", states[:, index["delta"]]),
                          ("filtered_active_power_pu", states[:, index["Psen"]] / k),
                          ("filtered_reactive_power_pu", states[:, index["Qsen"]] / k)):
    rms = float(np.sqrt(np.mean((signals[column] - reference) ** 2)))
    check(rms < 0.01 * np.ptp(reference), f"{column} matches the truth's state (rms {rms:.2e}, range {np.ptp(reference):.2e})")

# 5. harnesses, names, data, run_rung
with tempfile.TemporaryDirectory() as folder:
    build_ladder.build_everything(Path(folder) / "rungs", Path(folder) / "data", with_data=False)
    for rung in build_ladder.RUNGS:
        fresh, committed = Path(folder) / "rungs" / rung / "harness", build_ladder.RUNGS_DIR / rung / "harness"
        fresh_files = sorted(p.relative_to(fresh) for p in fresh.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        committed_files = sorted(p.relative_to(committed) for p in committed.rglob("*")
                                 if p.is_file() and "__pycache__" not in p.parts and not p.name.startswith("."))
        same = fresh_files == committed_files and all((fresh / p).read_bytes() == (committed / p).read_bytes()
                                                      for p in fresh_files)
        check(same, f"{rung}: committed harness matches a fresh build (rerun build_ladder.py if not)")
        build_ladder.check_names(committed)
for variant in sorted({spec["data"] for spec in build_ladder.RUNGS.values() if spec["data"]}):
    data_dir = build_ladder.DATA_DIR / variant
    check((data_dir / "runs.json").exists(), f"data/{variant} exists (python information_ladder/build_ladder.py builds it)")
    build_ladder.check_names(data_dir)
    columns = json.loads((data_dir / "dataset.json").read_text())["columns"]
    for run in json.loads((data_dir / "runs.json").read_text()).values():
        header = (data_dir / run["file"]).open().readline().strip().split(",")
        assert header == list(columns), (run["file"], header)
    check(True, f"data/{variant}: every CSV has exactly the columns dataset.json describes")

with tempfile.TemporaryDirectory() as folder:
    harness_dir, data_dir = run_rung.rung_paths("r3_internal_signals")
    original = solver_run.data_dir_for
    run_rung.use_rung_data(data_dir)
    try:
        settings = solver_run.SolverSettings(model_id="claude-haiku-5-5", effort="low", harness_dir=str(harness_dir),
                                             noise="clean", scorer_config=None)
        started = solver_run.SolverRun.start(settings, folder, client=object(), create_sandbox=LocalPythonSandbox.create)
        check(started.meta["data"] == str(data_dir) and
              (Path(started.sandbox.folder) / "train" / "A_vref_op1.csv").open().readline().count("current_d_pu") == 1,
              "run_rung hands the rung's data to the solver's sandbox")
    finally:
        solver_run.data_dir_for = original

# 6. the tools inside a sandbox, as the solver gets them
with tempfile.TemporaryDirectory() as folder:
    harness_dir, data_dir = run_rung.rung_paths("r4_menu_with_true")
    sandbox = LocalPythonSandbox.create(os.path.join(folder, "sandbox"), str(data_dir), str(harness_dir / "tools"),
                                        str(SUBMISSION_PARSER_FILE))

    def run(*command):
        result = sandbox.run(*command)
        return result.output

    listing = run("python", "tools/structure_menu.py", "list")
    check("27 structures in all." in listing, "structure_menu.py list in the sandbox")
    built = run("python", "tools/structure_menu.py", "build", "--pf", "droop", "--qv", "droop", "--voltage",
                "pi_voltage_loop", "--inner", "ideal", "--out", "cand.json")
    check("wrote cand.json" in built, "structure_menu.py build in the sandbox")
    checked = run("python", "tools/check_submission.py", "cand.json", "val/A_val_vref_op2.csv")
    check("OK:" in checked and "init residual" in checked, "check_submission.py accepts a built structure")
    replayed = run("python", "tools/grid_equivalent_replay.py", "cand.json", "val/A_val_vref_op2.csv", "--every", "2")
    check("RMSE" in replayed, "grid_equivalent_replay.py runs in the sandbox")
    fitted = run("python", "tools/fit_structure.py", "--pf", "droop", "--qv", "droop", "--voltage", "pi_voltage_loop",
                 "--inner", "ideal", "--files", "train/A_vref_op1.csv:4:6", "--seconds", "15", "--out", "fit.json")
    saved = json.loads(Path(sandbox.folder, "fit.json").read_text()) if Path(sandbox.folder, "fit.json").exists() else {}
    check(saved.get("cost", np.inf) < np.inf and "best cost" in fitted, f"fit_structure.py fits and saves ({fitted.strip().splitlines()[0]})")
    again = run("python", "tools/structure_menu.py", "build", "--pf", "droop", "--qv", "droop", "--voltage",
                "pi_voltage_loop", "--inner", "ideal", "--params", "fit.json", "--out", "fitted.json")
    check("wrote fitted.json" in again, "a fit result builds into a submission")
    restricted_harness, _ = run_rung.rung_paths("r5_menu_without_true")
    restricted = subprocess.run([sys.executable, str(restricted_harness / "tools" / "structure_menu.py"), "build", "--pf",
                                 "droop_with_power_loop", "--qv", "droop", "--voltage", "pi_voltage_loop", "--inner",
                                 "ideal", "--out", os.path.join(folder, "x.json")], capture_output=True, text=True)
    check("must be one of" in restricted.stdout, "r5's menu refuses the true blocks")

print(f"\n{passed} checks passed")
