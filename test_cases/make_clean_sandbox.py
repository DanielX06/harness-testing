"""
Noise-free copy of a grid's sandbox data, for a baseline without measurement noise.

    python make_clean_sandbox.py              # grid A: writes grid_A/sandbox_data_clean/

No simulation is repeated. build_cases.py writes every run's pre-noise recording to
holdout/<run>_clean.csv before it adds noise, so this copies those under the sandbox's file names,
keeps runs.json and the diagram, and sets the noise levels in dataset.json to zero. Each pair is
checked first: same rows, same time and setpoint columns, and a noisy-minus-clean residual whose
spread matches the stated noise level. Re-run it after build_cases.py so the two folders stay in step.

Use it with:  python run_harness.py 1 1 --noise clean    or    bash run_batch.sh 1 1 10 2 clean
"""
import argparse
import csv
import json
import math
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
# same list as build_cases.py: nothing in the sandbox may name the simulator, case or device
FORBIDDEN = re.compile(r"andes|regf|kundur|epri|grid.?forming|gfm|genrou|vsm|tgov|exdc", re.I)
NOISY_NOTE, CLEAN_NOTE = "PMU-grade measurements.", "Measurements are noise-free."


def read(path):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def check_pair(noisy_path, clean_path, sigmas):
    hn, n = read(noisy_path)
    hc, c = read(clean_path)
    assert hn == hc, f"{clean_path.name}: header differs from {noisy_path.name}"
    assert len(n) == len(c), f"{clean_path.name}: {len(c)} rows, sandbox file has {len(n)}"
    for col in ("time_s", "voltage_setpoint_pu"):          # neither carries noise, so must match exactly
        j = hn.index(col)
        assert all(a[j] == b[j] for a, b in zip(n, c)), f"{clean_path.name}: {col} differs"
    for col, s in sigmas.items():
        j = hn.index(col)
        d = [float(a[j]) - float(b[j]) for a, b in zip(n, c)]
        mu = sum(d) / len(d)
        sd = math.sqrt(sum((x - mu) ** 2 for x in d) / len(d))
        assert 0.9 < sd / s < 1.1, f"{clean_path.name}: {col} residual std {sd:.3g}, expected {s:.3g}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="A")
    grid = HERE / f"grid_{ap.parse_args().grid}"
    src, dst, hold = grid / "sandbox_data", grid / "sandbox_data_clean", grid / "holdout"

    dataset = json.loads((src / "dataset.json").read_text())
    runs = json.loads((src / "runs.json").read_text())
    sigmas = dataset["measurement_noise_std"]
    for run, m in runs.items():
        check_pair(src / m["file"], hold / f"{run}_clean.csv", sigmas)

    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir()
    for run, m in runs.items():
        (dst / m["file"]).parent.mkdir(exist_ok=True)
        shutil.copyfile(hold / f"{run}_clean.csv", dst / m["file"])
    for f in src.iterdir():                                 # runs.json, system_diagram.png, anything else
        if f.is_file() and f.name not in ("dataset.json", ".DS_Store"):
            shutil.copyfile(f, dst / f.name)

    dataset["measurement_noise_std"] = {k: 0.0 for k in sigmas}
    assert NOISY_NOTE in dataset["notes"], "dataset.json notes changed; update make_clean_sandbox.py"
    dataset["notes"] = dataset["notes"].replace(NOISY_NOTE, CLEAN_NOTE)
    (dst / "dataset.json").write_text(json.dumps(dataset, indent=2))

    for f in dst.rglob("*"):
        assert not FORBIDDEN.search(f.name), f"forbidden word in {f.name}"
        if f.suffix == ".json":
            assert not FORBIDDEN.search(f.read_text()), f"forbidden word in {f}"
    print(f"{dst}: {len(runs)} noise-free runs, checked against {src.name}")


if __name__ == "__main__":
    main()
