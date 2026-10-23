# Harness testing

An agent identifies an inverter-based device's terminal model from grid recordings, the scorer checks that model closed loop on grids the agent never sees, and the RSI loop lets an updater model improve the agent's harness (its instructions and helper code) one change at a time, keeping a change only when fresh runs show it helps.

| folder | what is in it |
|---|---|
| `solver/` | one agent run, batches of runs, the sandbox and the locked task prompt (`solver/README.md`) |
| `harness_v0/` | the starting harness (`system.md`, `method.md`, `tools/`), and the runs made before Oct 22 (`harness_v0/README.md`) |
| `scorer/` | the closed-loop scorer and the submission parser (`scorer/README.md`) |
| `test_cases/` | grid A (training), grid B (selection) and grid M (hidden monitor): their specs, recordings and builders (`test_cases/README.md`) |
| `rsi/` | the RSI loop: the updater's context, one proposal, and the experiment that runs and judges them (`rsi/README.md`) |
| `common/` | small modules the others share: project paths, API prices, the harness fingerprint, the names the solver must never see, and run provenance |
| `experiments/` | one-off analyses (the Q-V gain test, scoring old runs on grid M) |
| `runs/` | solver runs and batches made from Oct 22 on |

## Getting started

Everything runs from this folder with the shared venv (`PY=../.venv/bin/python` on the Mac).

```bash
docker build -t harness-v0-py solver                   # the solver's sandbox image, once
export ANTHROPIC_API_KEY=...
$PY run_all_checks.py                                   # every check that needs no API key, Docker or ANDES
$PY run_all_checks.py --andes --rebuild-grid B         # plus the closed-loop scorer tests, a re-score of saved runs
                                                        #   and grid B simulated again and compared with the committed one
$PY solver/solver_run.py haiku low --noise clean        # one solver run, scored on grid B
$PY rsi/rsi_experiment.py --iters 2 --baseline-runs 4 --pairs 4 --early-stop-pairs 2 --confirm-pairs 4   # RSI smoke test
```

Scripts take paths relative to this folder and find the rest through `common/project_paths.py`, so moving a folder means editing one line there. Every solver run records the git commit (`-dirty` if anything was uncommitted), the Docker image id and the harness fingerprint in its `meta.json`, so a score can be traced back to the exact code, sandbox and harness that made it.

## The names the solver must never see

The solver is told it faces "an inverter-based unit". The simulator, the case and the device model (`common/hidden_names.py`: ANDES, REGF, Kundur, grid-forming and the like) never appear in anything it gets: the sandbox builders and the RSI candidate checks refuse them, and the updater's context replaces them in solver text. The hidden grids' names (grid M, grid A's held-out runs) and the FR and PAR components never reach the updater either; `rsi/README.md` has the details.
