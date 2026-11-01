"""One solver run on one rung of the information ladder: solver/solver_run.py with the rung's harness and data.

    python information_ladder/run_rung.py r3_internal_signals haiku low [solver_run.py options]
    python information_ladder/run_rung.py r0_v0 sonnet low --config scorer/config_rsi.json --out runs/x

Every solver_run.py option works (--config, --out, --workers, --label, --no-score). The rung is stored as the
label rung=<name> in meta.json. The data are always noise-free: the rungs that add columns only have a
noise-free copy, and every rung uses the same noise setting so they compare. A crashed or stopped run is
resumed with solver/solver_run.py --resume <run folder> as usual (the sandbox already holds the rung's data).
"""
import os
import sys
from pathlib import Path

LADDER_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = LADDER_DIR.parent
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(LADDER_DIR))
from build_ladder import DATA_DIR, RUNGS, RUNGS_DIR  # noqa: E402
from common.project_paths import SOLVER_DATA_DIRS, STARTING_HARNESS_DIR  # noqa: E402
from solver import solver_run  # noqa: E402

RUNG_NAMES = ["r0_v0"] + list(RUNGS)


def rung_paths(rung):
    """(harness folder, data folder) for a rung."""
    if rung == "r0_v0":
        return STARTING_HARNESS_DIR, Path(SOLVER_DATA_DIRS["clean"])
    if rung not in RUNGS:
        sys.exit(f"unknown rung {rung!r}; one of {RUNG_NAMES}")
    data = RUNGS[rung]["data"]
    return RUNGS_DIR / rung / "harness", (DATA_DIR / data if data else Path(SOLVER_DATA_DIRS["clean"]))


def use_rung_data(data_dir):
    """Point solver_run at the rung's data folder (it otherwise picks grid A's folder from --noise)."""
    original_data_dir_for = solver_run.data_dir_for

    def rung_data_dir(noise):
        original_data_dir_for(noise)                 # the usual checks on the standard folder
        noise_levels = solver_run.read_json(os.path.join(data_dir, "dataset.json"))["measurement_noise_std"].values()
        if noise != "clean" or any(noise_levels):
            sys.exit(f"the ladder uses noise-free data ({data_dir})")
        return str(data_dir)

    solver_run.data_dir_for = rung_data_dir


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 3 or argv[0].startswith("-"):
        sys.exit(__doc__)
    rung, model, effort, rest = argv[0], argv[1], argv[2], argv[3:]
    if any(option == "--harness" or option.startswith("--harness=") or option == "--noise" or option.startswith("--noise=")
           for option in rest):
        sys.exit("the rung sets --harness and --noise; leave them out")
    harness_dir, data_dir = rung_paths(rung)
    if not (data_dir / "runs.json").exists():
        sys.exit(f"{data_dir} is missing; build it with python information_ladder/build_ladder.py")

    use_rung_data(data_dir)
    return solver_run.main([model, effort, "--harness", str(harness_dir), "--noise", "clean",
                            "--label", f"rung={rung}", *rest])


if __name__ == "__main__":
    sys.exit(main())
