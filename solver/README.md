# Solver

One solver run gives an agent grid A's recordings, lets it work in a Docker sandbox with `run_python`, takes the terminal model it submits ($V, \theta, V_{set} \to P, Q$, as JSON) and scores it closed loop with the scorer. The harness it is given (system.md, method.md, tools/) is a folder of its own; `../harness_v0/` has the starting one.

| file | what it is |
|---|---|
| `solver_run.py` | one run, from the first request to the scores; `--resume` carries on a run that crashed or was stopped |
| `run_solver_batch.sh` | the same harness N times, P at a time, then `summarize_batch.py` |
| `summarize_batch.py` | one row per run (status, cost, score components) and the spread; writes `summary.md` into the batch folder |
| `python_sandbox.py` | the sandbox: a fresh Docker container for every call (and a local stand-in for tests) |
| `task_prompt.md` | the locked task prompt; its `{{NOISE}}` line is filled from `--noise` |
| `Dockerfile` | the sandbox image: Python 3.12 with numpy, pandas, scipy, sympy |
| `tests/test_solver_run.py` | 28 checks with a fake API client, sandbox and scorer: a normal run, retries, crashes and resumes, stops, the budget, scorer failures, the context window, Docker failing |

## Setup (once)

```bash
cd "Fall DRA/Harness_testing"
docker build -t harness-v0-py solver
export ANTHROPIC_API_KEY=...
```

The runner uses the shared `Fall DRA/.venv`, which has `anthropic` and ANDES. To rebuild it: `python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt` in `Fall DRA`.

## Running

```bash
PY=../.venv/bin/python
$PY solver/solver_run.py haiku low                   # one run (1 1 works too), scored on grid B
$PY solver/solver_run.py haiku low --noise clean     # noise-free data (--noise noisy is the default)
bash solver/run_solver_batch.sh haiku low 10 2       # 10 runs, 2 at a time, then summarize_batch.py
bash solver/run_solver_batch.sh haiku low 10 2 clean
CONFIG=scorer/config_rsi.json bash solver/run_solver_batch.sh haiku low 40 4 clean      # also scored on grid M
HARNESS=rsi/experiments/long1/candidates/h003/harness CONFIG=scorer/config_rsi.json bash solver/run_solver_batch.sh haiku low 20 4 clean
$PY solver/solver_run.py --resume runs/<batch>/<run>  # carry on a run that crashed or was stopped
```

A single run goes to `runs/<tag>/` unless `--out` says otherwise; a batch goes to `runs/batch_<time>_<model>_<effort>_<noise>[_<harness>]/`. `run_solver_batch.sh` takes two optional environment variables, as paths relative to where you run the command. `HARNESS` picks the harness folder (default `harness_v0/harness`) and adds that folder's name to the batch folder's name. `CONFIG` picks the scorer config (default `scorer/config_min.json`). `config_rsi.json` also scores every run on grid M, the hidden monitor, privately like grid A's held-out runs; use it for every batch the RSI loop will be compared against. Each batch folder also gets `batch.json` with the settings, the harness and config paths, and the git commit (ending in `-dirty` if anything was uncommitted).

`--noise` picks both the data and one line of the prompt: "The measured channels carry PMU-grade noise." (noisy, the wording every earlier run got) or "The measured channels are noise-free." (clean, data from `test_cases/grid_A/sandbox_data_clean`). The runner stops if the folder's `dataset.json` noise levels don't match the choice.

## What a run writes

| file | what it is |
|---|---|
| `meta.json` | written when the run starts and after every step: status, cost so far, steps, tool calls, how many calls hit the 120 s limit, whether the budget stopped it, the harness fingerprint, the scorer config, labels (the RSI loop's block, pair, arm and harness), the git commit, the Docker image id, and at the end the score components for every grid |
| `checkpoint.json` | the conversation so far, rewritten after every message; removed when the run finishes |
| `sandbox/` | the agent's working folder; removed when the run finishes, kept for `--resume` otherwise |
| `transcript.json`, `final.md` | every message (the diagram replaced by its file name), and the last one |
| `submission.json` | the last json block of the final message, or the sandbox's `submission.json`; an empty object if neither parses, which scores 2 |
| `score/`, `score.log` | `public.json` (grid B only) and `private.json` (every grid, grid M included), and the scorer's output |

The RSI updater gets only the composite, the TD per held-out run and channel, and failures from `public.json` (decided Oct 17). FR and PAR feed the accept rule but are never shown.

## Crashes, stops and resuming

`meta.json`'s `status` says where a run stands: `running`, `scoring`, `finished`, `crashed` (an error it could not ride out; `error` says which), `stopped` (a signal: Ctrl-C, or the RSI loop stopping its runs) or `scoring_failed` (the scorer itself failed, not because of the submission). `--resume` carries on a crashed or stopped run from its last checkpoint, re-running an interrupted tool call, and a `scoring_failed` run by running the scorer again. `failures` counts the sessions that ended crashed or scoring_failed. A run that died without warning (power cut, kill -9) still says `running`; resume it the same way.

API problems that usually pass (a lost connection, an overloaded or failing server, a rate limit) are retried in place for about 35 minutes before the run counts as crashed. A conversation that has outgrown the model's context window ends the agent's work like a final message without a json block: the sandbox's `submission.json` is scored, or the run scores 2. That is the run's own outcome, not a crash. When Docker itself fails (the daemon is not running, the image is missing), the run crashes instead of handing Docker's error to the agent as if its code had printed it. The scorer runs in its own process group with a three-hour backstop around it; a scorer that hits it is stopped with its ANDES workers and the run scores 2 with the failure named `scoring_timeout`. Every budget counts the spend in `meta.json`, so a run that dies still counts.

## Cost and time

Haiku 5.5 at low effort cost about $0.017 a run in the Oct 13 batch (10 runs, $0.007 to $0.038), with the agent working 1 to 11 minutes. The agent is stopped once its next steps could pass $20. Scoring adds about 2.5 minutes per run on 2 cores (five ANDES runs), about 60% more with `config_rsi.json` (eight). Keep the parallel setting the same for batches you compare: machine load moves the share of tool calls cut off at 120 s (about 4% on the Mac at 2 in parallel), and timeouts change what the agent can do. `summary.md` reports that share.
