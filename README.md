# Harness testing

An agent identifies an inverter-based device's terminal model from grid recordings, the scorer checks that model closed loop on grids the agent never sees, and the RSI loop lets an updater model improve the agent's harness (its instructions and helper code) one change at a time, keeping a change only when fresh runs show it helps.

## Commands

Everything runs from this folder with the shared venv. Set it up once per machine:

```bash
cd ~/Documents/"Fall DRA"/Harness_testing
PY=../.venv/bin/python                    # the shared venv on the Mac
docker build -t harness-v0-py solver      # the solver's sandbox image
export ANTHROPIC_API_KEY=...              # every solver or updater call needs it; the checks don't
```

Checks, before trusting a change to the code:

```bash
$PY run_all_checks.py                             # every check that needs no API key, Docker or ANDES
$PY run_all_checks.py --andes --rebuild-grid B    # plus the closed-loop scorer tests, a re-score of saved runs
                                                  #   and grid B simulated again and compared with the committed one
```

Solver runs and batches (`solver/README.md` has the rest). A batch takes the model, the effort, the number of runs, how many run at once and the noise, in that order:

```bash
$PY solver/solver_run.py haiku low --noise clean                                     # one run, scored on grid B
bash solver/run_solver_batch.sh haiku low 10 2 clean                                 # 10 runs, 2 at a time, then summary.md
CONFIG=scorer/config_rsi.json bash solver/run_solver_batch.sh opus high 10 2 clean   # a baseline the RSI loop can be compared with (also scores grid M)
HARNESS=rsi_loops/<loop>/candidates/hNNN/harness CONFIG=scorer/config_rsi.json bash solver/run_solver_batch.sh haiku low 20 2 clean   # a candidate harness
$PY solver/solver_run.py --resume results/<study>/<batch>/<run>                      # carry on a run that crashed or was stopped
$PY scorer/rescore_runs.py results/<study>/<batch>/2*/ --reason "why" && $PY solver/summarize_batch.py results/<study>/<batch>   # score finished runs again after a scorer fix
```

Keep the number running at once the same across batches you compare, since machine load changes how often tool calls hit the 120 s limit. Cost scales with the model: Haiku at low effort averaged about $0.017 a run in the Oct 13 batch, and the one Opus run at high effort (Oct 20) cost $4.37.

The RSI loop (`rsi/README.md` has the rest, including running it unattended):

```bash
$PY rsi/rsi_experiment.py --iters 2 --baseline-runs 4 --pairs 4 --early-stop-pairs 2 --confirm-pairs 4   # smoke test
$PY rsi/rsi_experiment.py --iters 40 --parallel 4 --out rsi_loops/<date>_<name>                           # a real experiment
$PY rsi/rsi_experiment.py --resume rsi_loops/<loop>                                                       # carry on where it stopped
$PY rsi/experiment_archive.py rsi_loops/<loop>                                                            # pack an experiment that was stopped by hand
```

## Folders

Code, data you build, and what runs produce are kept apart. Every folder below has a README.

| folder | what is in it |
|---|---|
| `harnesses/` | every harness a person made: `v0/` (the starting harness) and `information_ladder/` (rungs r1 to r6); `harnesses/README.md` lists them |
| `results/` | everything a solver batch produced, one folder per study (`v0_baselines/`, `information_ladder/`, `rsi_smoke_tests/`, `scorer_reference/`); new batches land in `results/unfiled/`; `results/README.md` is the index |
| `rsi_loops/` | the RSI loop experiments, one folder per loop with a README; its own git repository (`harness-experiments`), ignored by this one |
| `analyses/` | one-off studies on saved runs (the Q-V gain test, scoring old runs on grid M) |
| `solver/` | one agent run, batches of runs, the sandbox and the locked task prompt |
| `scorer/` | the closed-loop scorer and the submission parser |
| `test_cases/` | grid A (training), grid B (selection) and grid M (hidden monitor): their specs, recordings and builders |
| `rsi/` | the RSI loop's code: the updater's context, its sandbox, one proposal, and the experiment that runs and judges them |
| `information_ladder/` | the ladder's code: the rung builder, its tools' sources and its run scripts (the rungs themselves are in `harnesses/information_ladder/`) |
| `common/` | small modules the others share: project paths, API prices, the harness fingerprint, the names the solver must never see, and run provenance |

Folders under `results/` and `rsi_loops/` are named `<date>_<model>-<effort>_<noise>` or `<date>_<run name>_<updater>_from-<start>`. They were renamed on Nov 9 (the project doc "Folder map after the Nov 9 reorganization" maps old paths to new); paths written inside older run files (`meta.json`, `batch.json`, `config.json`) still show where they were made. On a machine that still has the old layout, `git pull` and then `bash move_after_reorg.sh` (a dry run; add `--go` to move) puts aside the ignored files git leaves in the old folders and moves the loop repository to `rsi_loops/`.

## Paths and provenance

Scripts take paths relative to this folder and find the rest through `common/project_paths.py`, so moving a folder means editing one line there. Every solver run records the git commit (`-dirty` if anything was uncommitted), the Docker image id and the harness fingerprint in its `meta.json`, so a score can be traced back to the exact code, sandbox and harness that made it.

## The names the solver must never see

The solver is told it faces "an inverter-based unit". The simulator, the case and the device model (`common/hidden_names.py`: ANDES, REGF, Kundur, grid-forming and the like) never appear in anything it gets: the sandbox builders and the RSI candidate checks refuse them, and the updater's context replaces them in solver text. The hidden grids' names (grid M, grid A's held-out runs) and the FR and PAR components never reach the updater either; `rsi/README.md` has the details.
