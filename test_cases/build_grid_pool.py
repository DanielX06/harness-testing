"""Build the RSI loop's pool of random grids: for each device, N draws of (training grid X, scoring grid Y).

    python test_cases/build_grid_pool.py --devices REGF1,REGF2 --pairs 100 --workers 10
    python test_cases/build_grid_pool.py --devices REGF1 --pairs 3 --workers 4      # a small pool, to time it
    python test_cases/build_grid_pool.py --check                                     # list what the pool holds

Draws come from test_cases/sample_random_grids.py, seed 0, 1, 2, ... per device. Each draw's X and Y runs are
simulated in ANDES (build_test_grids.simulate_run, the same simulation as the fixed grids). A draw is thrown out if
the power flow or any simulation fails or a limiter binds; the next seed is tried, until --pairs draws are kept.
Building is resumable: seeds already kept or thrown out (manifest.json, rejected.jsonl) are skipped.

What a kept draw holds (grid_pool/<device>/<device>_<seed>/):
  X/sandbox_data_clean/   the noise-free recordings the solver gets (runs.json, dataset.json, system_diagram.png,
                          train/, val/); the noisy copy is not kept (the loop runs on clean data)
  X/holdout/              case.json, answer_key.json and X's two held-out runs (scored as the same-grid diagnostic)
  Y/holdout/              case.json, answer_key.json and Y's three held-out runs (the selection score)
  config_rsi.json         the scorer config of a run on this draw: Y selects, the device's fixed hidden monitor grid
                          (M or M2) monitors, X's held-out runs are the same-grid diagnostic
  specs.json              the two grid specs the draw was built from

The pool is not in git (grid_pool/ is ignored): about 35 MB a draw. It is rebuilt exactly from the seeds with the
same sampler version and repository commit (manifest.json records both).
"""
import argparse
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

TEST_CASES_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = TEST_CASES_DIR.parent
sys.path.insert(0, str(TEST_CASES_DIR))
sys.path.insert(0, str(REPOSITORY_ROOT))
import build_test_grids  # noqa: E402
import sample_random_grids  # noqa: E402
from common.hidden_names import SIMULATOR_AND_DEVICE_NAMES  # noqa: E402
from common.project_paths import DEVICE_SCORER_CONFIGS, GRID_POOL_DIR  # noqa: E402

NOISY_NOTE, NOISE_FREE_NOTE = "PMU-grade measurements.", "Measurements are noise-free."


def git_commit():
    try:
        return subprocess.run(["git", "describe", "--always", "--dirty"], cwd=REPOSITORY_ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def simulate(job):
    """(key, run name, simulation or None, error or None) for one run of one grid of one draw."""
    key, grid_spec, run_name = job
    try:
        return key, run_name, build_test_grids.simulate_run((grid_spec, run_name)), None
    except Exception as error:
        return key, run_name, None, f"{type(error).__name__}: {error}"[-300:]


def read_json(path, default):
    try:
        with open(path) as file:
            return json.load(file)
    except FileNotFoundError:
        return default


def make_noise_free_sandbox(grid_dir):
    """X/sandbox_data_clean from X/holdout's clean recordings, as make_noise_free_sandbox.py does for grid A; then
    the noisy sandbox_data/ and the train and validation copies in holdout/ are removed (the scorer reads only the
    held-out runs)."""
    noisy_dir, clean_dir, holdout_dir = grid_dir / "sandbox_data", grid_dir / "sandbox_data_clean", grid_dir / "holdout"
    runs = json.loads((noisy_dir / "runs.json").read_text())
    dataset = json.loads((noisy_dir / "dataset.json").read_text())
    clean_dir.mkdir()
    for run_name, run in runs.items():
        (clean_dir / run["file"]).parent.mkdir(exist_ok=True)
        shutil.copyfile(holdout_dir / f"{run_name}_clean.csv", clean_dir / run["file"])
    for path in noisy_dir.iterdir():
        if path.is_file() and path.name != "dataset.json":
            shutil.copyfile(path, clean_dir / path.name)
    dataset["measurement_noise_std"] = {column: 0.0 for column in dataset["measurement_noise_std"]}
    dataset["notes"] = dataset["notes"].replace(NOISY_NOTE, NOISE_FREE_NOTE)
    (clean_dir / "dataset.json").write_text(json.dumps(dataset, indent=2))
    for path in clean_dir.rglob("*"):
        assert not SIMULATOR_AND_DEVICE_NAMES.search(path.name), f"forbidden word in {path.name}"
        if path.suffix == ".json":
            assert not SIMULATOR_AND_DEVICE_NAMES.search(path.read_text()), f"forbidden word in {path}"
    shutil.rmtree(noisy_dir)
    for run_name in runs:
        (holdout_dir / f"{run_name}_clean.csv").unlink()


def scorer_config(device, pair_dir):
    """The device's config_rsi with the grids swapped: Y selects, the fixed monitor stays, X's held-out runs."""
    base_path = Path(DEVICE_SCORER_CONFIGS[device]["rsi"])
    base = json.loads(base_path.read_text())
    monitor = next(grid for grid in base["grids"] if grid["role"] == "monitor")
    monitor_path = (base_path.parent / monitor["path"]).resolve()
    config = {"_note": f"Random grid pool draw {pair_dir.name}: grid_Y is the selection grid, {monitor['name']} the "
                       "fixed hidden monitor, grid_X's own held-out runs the same-grid diagnostic. Written by "
                       "test_cases/build_grid_pool.py; paths are relative to this file.",
              "grids": [{"name": "grid_Y", "role": "selection", "format": "kundur_family_v1", "path": "Y"},
                        {"name": monitor["name"], "role": "monitor", "format": monitor["format"],
                         "path": os.path.relpath(monitor_path, pair_dir)},
                        {"name": "grid_X", "role": "train_holdout", "format": "kundur_family_v1", "path": "X"}]}
    config.update({key: value for key, value in base.items() if key not in ("_note", "grids")})
    return config


def write_draw(device, seed, specs, simulations, pool_dir):
    """Every file of one kept draw; returns its folder."""
    from draw_grid_diagrams import draw_grid
    pair_dir = pool_dir / device / f"{device.lower()}_{seed:04d}"
    staging = pair_dir.with_name(pair_dir.name + ".tmp")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    regenerate = f"python test_cases/build_grid_pool.py --devices {device} (seed {seed})"
    for which in ("X", "Y"):
        build_test_grids.write_grid_files(regenerate, specs[which], simulations[which], staging / which, plots=False)
    draw_grid(dict(sample_random_grids.diagram_labels(specs["X"]), out=staging / "X" / "sandbox_data" / "system_diagram.png"))
    make_noise_free_sandbox(staging / "X")
    (staging / "specs.json").write_text(json.dumps(specs, indent=1))
    (staging / "config_rsi.json").write_text(json.dumps(scorer_config(device, pair_dir), indent=1))
    if pair_dir.exists():
        shutil.rmtree(pair_dir)
    staging.rename(pair_dir)
    return pair_dir


def build(devices, pairs, workers, pool_dir, batch_size):
    import matplotlib
    matplotlib.use("Agg")
    pool_dir.mkdir(parents=True, exist_ok=True)
    manifest_path, rejected_path = pool_dir / "manifest.json", pool_dir / "rejected.jsonl"
    manifest = read_json(manifest_path, {"draws": {}})
    rejected = {}
    if rejected_path.exists():
        for line in rejected_path.read_text().splitlines():
            record = json.loads(line)
            rejected[(record["device"], record["seed"])] = record
    with multiprocessing.get_context("spawn").Pool(workers) as process_pool:
        for device in devices:
            kept = [draw for draw in manifest["draws"].values() if draw["device"] == device]
            seed = 0
            while len(kept) < pairs:
                batch = []
                while len(batch) < batch_size:
                    key = f"{device.lower()}_{seed:04d}"
                    if key not in manifest["draws"] and (device, seed) not in rejected:
                        batch.append(seed)
                    seed += 1
                started = time.monotonic()
                specs = {s: dict(zip(("X", "Y", "summary"), sample_random_grids.sample_pair(device, s))) for s in batch}
                jobs = [((s, which), specs[s][which], run_name) for s in batch for which in ("X", "Y")
                        for run_name in specs[s][which]["case"]["runs"]]
                jobs.sort(key=lambda job: -job[1]["case"]["runs"][job[2]]["tf"])
                results, errors = {s: {"X": {}, "Y": {}} for s in batch}, {s: [] for s in batch}
                for (s, which), run_name, simulation, error in process_pool.imap_unordered(simulate, jobs):
                    if error:
                        errors[s].append(f"{which} {run_name}: {error}")
                    else:
                        results[s][which][run_name] = simulation
                for s in batch:
                    key = f"{device.lower()}_{s:04d}"
                    if errors[s]:
                        record = {"device": device, "seed": s, "reasons": errors[s][:4], "summary": specs[s]["summary"]}
                        rejected[(device, s)] = record
                        with open(rejected_path, "a") as file:
                            file.write(json.dumps(record) + "\n")
                        continue
                    if len(kept) >= pairs:
                        break
                    pair_dir = write_draw(device, s, {"X": specs[s]["X"], "Y": specs[s]["Y"]}, results[s], pool_dir)
                    entry = {"device": device, "seed": s, "folder": str(pair_dir.relative_to(pool_dir)),
                             "sampler_version": sample_random_grids.SAMPLER_VERSION, "commit": git_commit(),
                             "summary": specs[s]["summary"]}
                    manifest["draws"][key] = entry
                    kept.append(entry)
                    manifest_path.write_text(json.dumps(manifest, indent=1))
                thrown = sum(1 for s in batch if errors[s])
                print(f"{device}: seeds {batch[0]}-{batch[-1]}: kept {len(batch) - thrown}, thrown out {thrown} "
                      f"({time.monotonic() - started:.0f} s); {len(kept)} of {pairs} kept", flush=True)
    check(pool_dir)


def check(pool_dir):
    manifest = read_json(pool_dir / "manifest.json", {"draws": {}})
    rejected_path = pool_dir / "rejected.jsonl"
    rejected = rejected_path.read_text().splitlines() if rejected_path.exists() else []
    for device in sorted({draw["device"] for draw in manifest["draws"].values()}):
        draws = [draw for draw in manifest["draws"].values() if draw["device"] == device]
        missing = [draw["folder"] for draw in draws if not (pool_dir / draw["folder"] / "config_rsi.json").exists()]
        slots = {slot: sum(draw["summary"]["X"]["slot"] == slot for draw in draws) for slot in (2, 3, 4)}
        thrown = sum(json.loads(line)["device"] == device for line in rejected)
        print(f"{device}: {len(draws)} draws kept, {thrown} thrown out; training-grid slots {slots}"
              + (f"; MISSING FOLDERS {missing}" if missing else ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--devices", default="REGF1,REGF2")
    parser.add_argument("--pairs", type=int, default=100, help="draws to keep per device")
    parser.add_argument("--workers", type=int, default=max(1, (multiprocessing.cpu_count() or 2) - 1))
    parser.add_argument("--batch", type=int, default=None, help="draws simulated together (default: workers / 2, at least 2)")
    parser.add_argument("--out", default=str(GRID_POOL_DIR))
    parser.add_argument("--check", action="store_true", help="only list what the pool holds")
    options = parser.parse_args()
    pool_dir = Path(options.out)
    if options.check:
        return check(pool_dir)
    devices = options.devices.split(",")
    unknown = [device for device in devices if device not in sample_random_grids.TRAINING_GRID_OF_DEVICE]
    if unknown:
        sys.exit(f"no random grids for {unknown}: the pool holds the training devices "
                 f"{sorted(sample_random_grids.TRAINING_GRID_OF_DEVICE)} only (REGF3 is held out)")
    build(devices, options.pairs, options.workers, pool_dir, options.batch or max(2, options.workers // 2))


if __name__ == "__main__":
    main()
