# Harness v0

The baseline harness the RSI loop starts from. One run gives an agent grid A's recordings, lets it work in the Docker sandbox with `run_python`, takes its terminal model ($V, \theta, V_{set} \to P, Q$, as JSON) and scores it closed loop on grid B with `scorer/config_min.json`.

## What the agent gets, and who may change it

| piece | file | RSI edit scope |
|---|---|---|
| task, data description, how it's scored, submission format (including `Vset`), budget | `prompt.md` | locked |
| facts about the device and grid: an inverter-based unit, 900 MVA, droop support claimed, structure undocumented; the rest of the network | `harness/system.md` | edit-anything scope only |
| how to work | `harness/method.md` | both scopes |
| helper code copied into the sandbox: the submission checker (`check_submission.py` and `replay.py`) | `harness/tools/` | both scopes |
| the submission parser `symbolic.py`, copied into the sandbox's `tools/` so the checker applies the scorer's own rules | `../scorer/symbolic.py` | locked |
| grid A's `train/`, `val/`, `runs.json`, `dataset.json`, `system_diagram.png` | `../test_cases/grid_A/sandbox_data` (`sandbox_data_clean` with `--noise clean`) | locked |
| scorer, $20 cap, sandbox, Docker image | `run_harness.py`, `../scorer/` | locked |

The diagram and `system.md` are always included, following the Oct 8 context-arm result. An evolved harness is just another folder laid out like `harness/`, run with `--harness`. Every run records a hash of that folder, so each score traces back to the exact harness.

v0 ships the submission checker in `tools/`. Without it, a weak agent would probably lose many runs to malformed JSON or a model that doesn't start at rest, and those score 2, so the baseline would mostly measure format errors. If you want a barer baseline, delete the two files from `harness/tools/`, and check that the prompt line pointing to the checker still makes sense.

## Setup (once)

```bash
cd "Fall DRA/Harness_testing/harness_v0"
docker build -t harness-v0-py .        # python 3.12 with numpy, pandas, scipy, sympy
export ANTHROPIC_API_KEY=...
```

The runner uses the shared `Fall DRA/.venv`, which has `anthropic` and ANDES. To rebuild it: `python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt` in `Fall DRA`.

## Running

```bash
PY=../../.venv/bin/python
$PY run_harness.py 1 1                 # one run: Haiku 5.5 at low effort, scored on grid B
bash run_batch.sh 1 1 10 2             # calibration: 10 runs, 2 at a time, then summarize.py
$PY run_harness.py 1 1 --noise clean   # noise-free baseline (--noise noisy is the default)
bash run_batch.sh 1 1 10 2 clean       # same, as a batch; the fifth argument is noisy or clean
```

`--noise` picks both the data and one line of the prompt. `prompt.md` has a `{{NOISE}}` placeholder that the runner fills with "The measured channels carry PMU-grade noise." (noisy, the wording every earlier run got) or "The measured channels are noise-free." (clean, data from `../test_cases/grid_A/sandbox_data_clean`). The runner stops if the folder's `dataset.json` noise levels don't match the choice. `meta.json` records `noise` and the data folder, and batch folders end in `_noisy` or `_clean`.

Each run writes `runs/<tag>/` containing:
- `transcript.json`: every tool call and result
- `final.md`: the agent's last message
- `submission.json`: the last json block of the final message, or the sandbox's `submission.json`; an empty object if neither parses, which scores 2
- `meta.json`: cost, steps, tool calls, whether the budget stopped it, harness hash and score components
- `score/`: `public.json` (grid B only, what the updater may see) and `private.json`

A batch also writes `summary.md` with the mean, spread and cost per run. That spread is the number that decides how many reps the keep/revert rule needs.

Scoring adds about 2.5 minutes per run on 2 cores (five ANDES runs), and less on your Mac with more workers.

## What changed from Harness1.0

The Harness1.0 agent submitted a δ law as Python and was scored by driving it open loop with the true inputs. v0 asks for a terminal model as JSON (the scorer's format), with no δ in the data, and scores it closed loop on a grid the agent never sees. The data now has three operating points, staged voltage-reference tests, ambient recordings and an operator log. The skeleton is device-generic and calls the device an inverter-based unit. The old skeleton's structural hints (droop on P after millisecond filters, extra PI action) are gone, as agreed on Oct 9.

## What has and hasn't been checked

I ran the runner end to end in the cloud with a stand-in for the API that submits the true model with an ideal current loop. The prompt, `system.md`, `method.md` and the diagram arrive as four blocks, the json block is extracted, and the scorer gives 0.0106 on grid B, as it should. I also ran the checker on a validation file: the ideal-loop model replays to near the noise, flat replays as flat, and the full 13-state truth diverges open loop, which is the known behaviour that `method.md` warns about.

Not checked: the Docker sandbox (no Docker daemon in the cloud) and real API calls. The first real run is yours. Start with one Haiku-low run and read its transcript before launching a batch.
