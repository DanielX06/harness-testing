"""Checks for the random grid pool: the sampler, the loop's draw assignments, the launcher's command, the names the
updater must not see on pool configs. No ANDES and no API: building a real pool is test_cases/build_grid_pool.py.

    python rsi/tests/test_grid_pool.py
"""
import json
import os
import shutil
import sys
import tempfile

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPOSITORY_ROOT)
sys.path.insert(0, os.path.join(REPOSITORY_ROOT, "test_cases"))
import sample_random_grids as S  # noqa: E402
from common.hidden_names import SIMULATOR_AND_DEVICE_NAMES  # noqa: E402
from rsi import rsi_experiment as R  # noqa: E402
from rsi import updater_context as U  # noqa: E402

passed = 0


def check(condition, description):
    global passed
    if not condition:
        raise AssertionError(description)
    passed += 1
    print("ok:", description)


# 1. the sampler: a pure function of (device, seed), inside the ranges, every event possible on its grid
first, again = S.sample_pair("REGF1", 11), S.sample_pair("REGF1", 11)
check(json.dumps(first) == json.dumps(again), "a draw is the same every time for the same device and seed")
check(json.dumps(S.sample_pair("REGF1", 11)[2]) != json.dumps(S.sample_pair("REGF2", 11)[2]),
      "the two devices draw different grids from the same seed")
slots, problems = set(), []
for device in ("REGF1", "REGF2"):
    for seed in range(150):
        x_spec, y_spec, summary = S.sample_pair(device, seed)
        slots.add(summary["X"]["slot"])
        if x_spec["device_under_test"] != S.device_under_test(device):
            problems.append(f"{device} {seed}: unit parameters differ from its training grid")
        for spec in (x_spec, y_spec):
            case = spec["case"]
            for point in case["operating_points"].values():
                if not S.SLACK_RANGE_PU[0] <= S.slack_estimate(point) <= S.SLACK_RANGE_PU[1] + 2.5:
                    problems.append(f"{device} {seed}: slack estimate {S.slack_estimate(point):.2f}")
                for corridor, circuits in S.CORRIDORS.items():
                    if all(circuit in point["lines_out"] for circuit in circuits):
                        problems.append(f"{device} {seed}: corridor {corridor} fully out")
            for name, run in case["runs"].items():
                lines_out = case["operating_points"][run["op"]]["lines_out"]
                for event in run["events"]:
                    if event["kind"] == "line_trip" and event["line"] not in S.trippable_circuits(lines_out):
                        problems.append(f"{name}: trips {event['line']}, which would cut its corridor")
                    if event["kind"] == "gen_trip" and event["syn"] == case["device"]["syn"]:
                        problems.append(f"{name}: trips the unit's own slot")
        if SIMULATOR_AND_DEVICE_NAMES.search(json.dumps(x_spec["operating_conditions_log"])):
            problems.append(f"{device} {seed}: a hidden name in the operator's log")
check(not problems, f"300 draws stay in range, keep every corridor connected and never trip the unit ({problems[:2]})")
check(slots == {2, 3, 4}, "the unit lands in generator 2's, 3's and 4's slots")
x_spec = S.sample_pair("REGF2", 5)[0]
labels = S.diagram_labels(x_spec)
check(labels["device_slot"] == x_spec["case"]["device"]["syn"] and "g1" not in labels
      and all(f"g{machine}" in labels for machine in (2, 3, 4) if machine != labels["device_slot"]),
      "the diagram labels every generator but the unit's slot")

# 2. a fake pool: two draws per device whose configs point at real grids (only case.json files are read here)
work = tempfile.mkdtemp(prefix="grid_pool_test_")
try:
    manifest = {"draws": {}}
    for device, training, scoring in (("REGF1", "grid_A", "grid_B"), ("REGF2", "grid_A2", "grid_B2")):
        for seed in (0, 1):
            folder = os.path.join(device, f"{device.lower()}_{seed:04d}")
            for which, source in (("X", training), ("Y", scoring)):
                os.makedirs(os.path.join(work, folder, which, "holdout"))
                shutil.copy(os.path.join(REPOSITORY_ROOT, "test_cases", source, "holdout", "case.json"),
                            os.path.join(work, folder, which, "holdout", "case.json"))
            monitor = "grid_M" if device == "REGF1" else "grid_M2"
            config = {"grids": [{"name": "grid_Y", "role": "selection", "format": "kundur_family_v1", "path": "Y"},
                                {"name": monitor, "role": "monitor", "format": "kundur_family_v1",
                                 "path": os.path.relpath(os.path.join(REPOSITORY_ROOT, "test_cases", monitor),
                                                         os.path.join(work, folder))},
                                {"name": "grid_X", "role": "train_holdout", "format": "kundur_family_v1", "path": "X"}]}
            with open(os.path.join(work, folder, "config_rsi.json"), "w") as file:
                json.dump(config, file)
            manifest["draws"][os.path.basename(folder)] = {"device": device, "seed": seed, "folder": folder}
    with open(os.path.join(work, "manifest.json"), "w") as file:
        json.dump(manifest, file)

    settings = R.ExperimentSettings(iters=1, out=os.path.join(work, "loop"), devices=["REGF1", "REGF2"], grid_pool=work)
    check(not settings.problems(), f"a pool with draws for both devices is accepted ({settings.problems()})")
    check(R.ExperimentSettings(iters=1, out="x", grid_pool=work, noise="noisy").problems(),
          "the pool needs --noise clean")
    check(R.ExperimentSettings(iters=1, out="x", grid_pool=os.path.join(work, "nowhere")).problems(),
          "a pool folder with no draws is refused")
    check([os.path.basename(os.path.dirname(c)) for c in settings.scorer_configs] == ["regf1_0000", "regf2_0000"],
          "each device's first draw stands for its configs")

    # 3. assignments: both arms share, every draw once before repeats, the same after a restart
    path = os.path.join(work, "grid_assignments.json")
    grids = R.GridAssignments(path, work, "loop")
    a = grids.draw_for("h000_baseline", 1, "REGF1")
    check(a == grids.draw_for("h000_baseline", 1, "REGF1"), "both arms of a pair get the same draw")
    b = grids.draw_for("h000_baseline", 3, "REGF1")
    c = grids.draw_for("h001_test", 1, "REGF1")
    check(a != b and c in (a, b), "a device's two draws are both used before either repeats")
    check(R.GridAssignments(path, work, "loop").draw_for("h000_baseline", 3, "REGF1") == b,
          "a resumed loop reads the same assignment back")
    check(a[0].endswith(os.path.join("X", "sandbox_data_clean")) and a[1].endswith("config_rsi.json"),
          "a draw gives the solver X's clean recordings and the scorer the draw's config")
    check(grids.draw_for("h000_baseline", 2, "REGF2")[1].split(os.sep)[-3] == "REGF2", "each device draws from its own folder")

    # 4. the launcher passes the draw to solver_run.py
    class Capture:
        def __init__(self, command, log_path):
            self.command = command
    original = R.LaunchedSolverProcess
    R.LaunchedSolverProcess = Capture
    try:
        launched = R.SolverLauncher(settings).start_new(work, {"device": "REGF1", "pair": 1}, "h", "log",
                                                        data_dir=a[0], config=a[1])
    finally:
        R.LaunchedSolverProcess = original
    command = launched.command
    check(command[command.index("--data-dir") + 1] == a[0] and command[command.index("--config") + 1] == a[1],
          "solver_run.py gets --data-dir and --config of the draw")

    # 5. names the updater must not see: the monitor and X's held-out runs, never X's own training data or grid_Y
    pattern = U.hidden_score_names_pattern(settings.scorer_configs)
    check(pattern.search("grid_X") and pattern.search("grid_M") and pattern.search("A_test_line_op1"),
          "grid_X, the monitor and X's held-out runs are hidden")
    check(not pattern.search("A_amb_op1") and not pattern.search("grid_Y") and not pattern.search("B_load"),
          "X's training runs, grid_Y and Y's runs stay visible")
    U.set_unit_data_dirs({"unit 1": "/somewhere"})
    check(U.unit_data_dir("unit 1", "clean") == "/somewhere" and U.RANDOM_GRIDS_NOTE.strip() in
          U.updater_instructions("claude-haiku-5-5", "low", "tools", 0.1, 1.0),
          "with a pool the updater sees one run's recordings and is told every run had its own grid")
    U.set_unit_data_dirs({})
    check(U.RANDOM_GRIDS_NOTE.strip() not in U.updater_instructions("claude-haiku-5-5", "low", "tools", 0.1, 1.0),
          "without a pool its instructions are unchanged")
finally:
    shutil.rmtree(work, ignore_errors=True)

print(f"\nall {passed} checks passed")
