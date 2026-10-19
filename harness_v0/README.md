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

The diagram and `system.md` are always included, following the Oct 8 context-arm result. An evolved harness is just another folder laid out like `harness/`, run with `--harness`. Every run records a hash of that folder, so each score traces back to the exact harness. The hash skips `__pycache__` and dotfiles such as Finder's `.DS_Store`, and the copy of `tools/` in the sandbox leaves out the same files, so opening a harness folder in Finder doesn't change its hash.

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
CONFIG=../scorer/config_rsi.json bash run_batch.sh 1 1 40 4 clean                       # RSI calibration pool, also scored on grid M
HARNESS=path/to/h003 CONFIG=../scorer/config_rsi.json bash run_batch.sh 1 1 20 4 clean  # an archived harness
```

`run_batch.sh` takes two optional environment variables, as paths relative to where you run the command. `HARNESS` picks the harness folder (default `harness/`) and adds that folder's name to the batch folder's name. `CONFIG` picks the scorer config (default `config_min.json`). `config_rsi.json` also scores every run on grid M, the hidden monitor, privately like grid A's held-out runs. Use it for every batch the RSI loop will be compared against, including the v0 calibration pool, so the monitor has a v0 baseline. Each batch folder also gets `batch.json` with the settings, the harness and config paths, and the git commit (ending in `-dirty` if anything was uncommitted).

`--noise` picks both the data and one line of the prompt. `prompt.md` has a `{{NOISE}}` placeholder that the runner fills with "The measured channels carry PMU-grade noise." (noisy, the wording every earlier run got) or "The measured channels are noise-free." (clean, data from `../test_cases/grid_A/sandbox_data_clean`). The runner stops if the folder's `dataset.json` noise levels don't match the choice. `meta.json` records `noise` and the data folder, and batch folders end in `_noisy` or `_clean`.

Each run writes `runs/<tag>/` containing:
- `transcript.json`: every tool call and result
- `final.md`: the agent's last message
- `submission.json`: the last json block of the final message, or the sandbox's `submission.json`; an empty object if neither parses, which scores 2
- `meta.json`: cost, steps, tool calls, how many tool calls were cut off at 120 s (`tool_timeouts`), whether the budget stopped it, harness hash, scorer config and score components for every grid
- `score/`: `public.json` (grid B only) and `private.json` (every grid, grid M included). The RSI updater will get only the composite, the TD per held-out run and channel, and failures from `public.json` (decided Oct 17). FR and PAR feed the accept rule but are never shown.

A batch also writes `summary.md` with the mean, spread and cost per run, the grid M score when the batch used `config_rsi.json`, and the share of tool calls cut off at 120 s. That spread is the number that decides how many reps the keep/revert rule needs. Keep the parallel setting the same for batches you compare: machine load moves the timeout share (about 4% of calls on the Mac at 2 in parallel), and timeouts change what the agent can do.

Scoring adds about 2.5 minutes per run on 2 cores (five ANDES runs), about 60% more with `config_rsi.json` (eight).

## What changed from Harness1.0

The Harness1.0 agent submitted a δ law as Python and was scored by driving it open loop with the true inputs. v0 asks for a terminal model as JSON (the scorer's format), with no δ in the data, and scores it closed loop on a grid the agent never sees. The data now has three operating points, staged voltage-reference tests, ambient recordings and an operator log. The skeleton is device-generic and calls the device an inverter-based unit. The old skeleton's structural hints (droop on P after millisecond filters, extra PI action) are gone.

