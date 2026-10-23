# Harness v0

The harness the RSI loop starts from: what an agent is told about the device and how to work, plus the helper code it gets in its sandbox. The code that runs an agent with a harness is in `../solver/` (see its README). The runs made before the Oct 22 restructuring stay in `runs/` here, untouched; new runs go to `../runs/`.

## What the agent gets, and who may change it

| piece | file | RSI edit scope |
|---|---|---|
| task, data description, how it's scored, submission format (including `Vset`), budget | `../solver/task_prompt.md` | locked |
| facts about the device and grid: an inverter-based unit, 900 MVA, droop support claimed, structure undocumented; the rest of the network | `harness/system.md` | edit-anything scope only |
| how to work | `harness/method.md` | both scopes |
| helper code copied into the sandbox: the submission checker (`check_submission.py`, with its open-loop replay in `open_loop_replay.py`) | `harness/tools/` | both scopes |
| the submission parser, copied into the sandbox as `tools/submission_parser.py` so the checker applies the scorer's own rules | `../scorer/submission_parser.py` | locked |
| grid A's `train/`, `val/`, `runs.json`, `dataset.json`, `system_diagram.png` | `../test_cases/grid_A/sandbox_data` (`sandbox_data_clean` with `--noise clean`) | locked |
| scorer, $20 cap, sandbox, Docker image | `../solver/`, `../scorer/` | locked |

The diagram and `system.md` are always included, following the Oct 8 context-arm result. An evolved harness is just another folder laid out like `harness/`, run with `--harness`. Every run records the harness's fingerprint (`common/harness_files.py`), so each score traces back to the exact harness. The fingerprint skips `__pycache__` and dotfiles such as Finder's `.DS_Store`, and the copy of `tools/` in the sandbox leaves out the same files, so opening a harness folder in Finder doesn't change it.

On Oct 22 two files were renamed for readability: `tools/replay.py` is now `tools/open_loop_replay.py`, and the parser the sandbox gets is now `tools/submission_parser.py` (it was `symbolic.py`). The checker prints exactly what it printed before on every saved submission, but the fingerprint changed from f141be203a8a40f4 to 9a035ad12d528ea0, so the runs in `runs/` here belong to a harness that no longer exists on disk. `../rsi/tests/fixtures/harness_v0_oct13/` keeps a copy of it for the tests.

v0 ships the submission checker in `tools/`. Without it, a weak agent would probably lose many runs to malformed JSON or a model that doesn't start at rest, and those score 2, so the baseline would mostly measure format errors. If you want a barer baseline, delete the two files from `harness/tools/`, and check that the task prompt's line pointing to the checker still makes sense.

## What changed from Harness1.0

The Harness1.0 agent submitted a δ law as Python and was scored by driving it open loop with the true inputs. v0 asks for a terminal model as JSON (the scorer's format), with no δ in the data, and scores it closed loop on a grid the agent never sees. The data now has three operating points, staged voltage-reference tests, ambient recordings and an operator log. The skeleton is device-generic and calls the device an inverter-based unit. The old skeleton's structural hints (droop on P after millisecond filters, extra PI action) are gone.
