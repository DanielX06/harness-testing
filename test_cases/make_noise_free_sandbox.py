"""Noise-free copy of a grid's sandbox data, for a baseline without measurement noise.

    python test_cases/make_noise_free_sandbox.py              # grid A: writes grid_A/sandbox_data_clean/
    python test_cases/make_noise_free_sandbox.py --grid A

No simulation is repeated. build_test_grids.py writes every run's recording to holdout/<run>_clean.csv before it adds
noise, so this copies those under the sandbox's file names, keeps runs.json and the diagram, and sets the noise
levels in dataset.json to zero. Each pair is checked first: the same rows, the same time and setpoint columns, and a
noisy-minus-clean residual whose spread matches the stated noise level. Run it again after build_test_grids.py so
the two folders stay in step.

The solver gets it with  python solver/solver_run.py haiku low --noise clean  (or clean as the fifth argument of
solver/run_solver_batch.sh).
"""
import argparse
import csv
import json
import math
import shutil
import sys
from pathlib import Path

TEST_CASES_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_CASES_DIR.parent))          # the repository root
from common.hidden_names import SIMULATOR_AND_DEVICE_NAMES  # noqa: E402

NOISY_NOTE, NOISE_FREE_NOTE = "PMU-grade measurements.", "Measurements are noise-free."


def read_csv(path):
    with open(path, newline="") as file:
        rows = list(csv.reader(file))
    return rows[0], rows[1:]


def check_noisy_against_clean(noisy_path, clean_path, noise_sigmas):
    """The clean recording must be the noisy one's twin: same rows, same time and setpoint, residual spread = sigma."""
    noisy_header, noisy_rows = read_csv(noisy_path)
    clean_header, clean_rows = read_csv(clean_path)
    assert noisy_header == clean_header, f"{clean_path.name}: header differs from {noisy_path.name}"
    assert len(noisy_rows) == len(clean_rows), f"{clean_path.name}: {len(clean_rows)} rows, sandbox file has {len(noisy_rows)}"
    for column in ("time_s", "voltage_setpoint_pu"):          # neither carries noise, so they must match exactly
        index = noisy_header.index(column)
        assert all(noisy[index] == clean[index] for noisy, clean in zip(noisy_rows, clean_rows)), \
            f"{clean_path.name}: {column} differs"
    for column, sigma in noise_sigmas.items():
        index = noisy_header.index(column)
        residuals = [float(noisy[index]) - float(clean[index]) for noisy, clean in zip(noisy_rows, clean_rows)]
        mean = sum(residuals) / len(residuals)
        spread = math.sqrt(sum((value - mean) ** 2 for value in residuals) / len(residuals))
        assert 0.9 < spread / sigma < 1.1, f"{clean_path.name}: {column} residual std {spread:.3g}, expected {sigma:.3g}"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--grid", default="A")
    grid_dir = TEST_CASES_DIR / f"grid_{parser.parse_args().grid}"
    noisy_dir, noise_free_dir, holdout_dir = grid_dir / "sandbox_data", grid_dir / "sandbox_data_clean", grid_dir / "holdout"

    dataset = json.loads((noisy_dir / "dataset.json").read_text())
    runs = json.loads((noisy_dir / "runs.json").read_text())
    noise_sigmas = dataset["measurement_noise_std"]
    for run_name, run in runs.items():
        check_noisy_against_clean(noisy_dir / run["file"], holdout_dir / f"{run_name}_clean.csv", noise_sigmas)

    if noise_free_dir.exists():
        shutil.rmtree(noise_free_dir)
    noise_free_dir.mkdir()
    for run_name, run in runs.items():
        (noise_free_dir / run["file"]).parent.mkdir(exist_ok=True)
        shutil.copyfile(holdout_dir / f"{run_name}_clean.csv", noise_free_dir / run["file"])
    for path in noisy_dir.iterdir():                         # runs.json, system_diagram.png, anything else
        if path.is_file() and path.name not in ("dataset.json", ".DS_Store"):
            shutil.copyfile(path, noise_free_dir / path.name)

    dataset["measurement_noise_std"] = {column: 0.0 for column in noise_sigmas}
    assert NOISY_NOTE in dataset["notes"], "dataset.json notes changed; update make_noise_free_sandbox.py"
    dataset["notes"] = dataset["notes"].replace(NOISY_NOTE, NOISE_FREE_NOTE)
    (noise_free_dir / "dataset.json").write_text(json.dumps(dataset, indent=2))

    for path in noise_free_dir.rglob("*"):
        assert not SIMULATOR_AND_DEVICE_NAMES.search(path.name), f"forbidden word in {path.name}"
        if path.suffix == ".json":
            assert not SIMULATOR_AND_DEVICE_NAMES.search(path.read_text()), f"forbidden word in {path}"
    print(f"{noise_free_dir}: {len(runs)} noise-free runs, checked against {noisy_dir.name}")


if __name__ == "__main__":
    main()
