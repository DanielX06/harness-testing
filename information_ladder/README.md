# Information ladder

Chen's Oct 28 suggestions 1 and 3 as one experiment: give the Haiku-low solver more information than harness_v0 does, one rung at a time, and see at which rung its grid B score approaches 0. The rung where it does says what the solver was missing: a way to check its model, data, or structure. Nothing in this folder changes the solver, scorer, test cases or RSI loop. A rung is just a harness folder plus, for two rungs, a copy of grid A's data with extra columns.

## The rungs

| rung | what it adds over harness_v0 | realistic? |
|---|---|---|
| `r0_v0` | nothing (harness_v0 itself, fingerprint 9a035ad12d528ea0) | control |
| `r1_grid_equivalent` | the network's short-circuit reactance at bus 3 in system.md, and `tools/grid_equivalent_replay.py`, which method.md now uses to check candidates | yes, an operator has the network model |
| `r2_device_log` | r1, plus two columns in every CSV: the device's internal angle and internal frequency command | borderline, many units log these |
| `r3_internal_signals` | r1, plus nine columns: internal angle and frequency, filtered P and Q, both power-loop outputs, inner voltage reference, frame currents d and q | oracle |
| `r4_menu_with_true` | r1, plus `tools/structure_menu.py` (27 structures built from blocks, the true one among them) and `tools/fit_structure.py` | partly, a manufacturer's block library |
| `r5_menu_without_true` | r4 with the true blocks taken out (12 structures, none of them the device's) | as r4 |
| `r6_structure_given` | r1, plus the true structure with unknown parameters (the menu reduced to it) and the fitter | oracle |

r1 is the base of every later rung because of what building it turned up. **The open-loop replay in `check_submission.py` diverges on the true model**: Newton fails about 2.1 s into A_val_vref_op2, because REGF1's current loop is only damped through the network (the scorer README already notes this). So under harness_v0, the solver's only checking tool rejects the right answer. The grid-equivalent replay runs the model against a source E(t) behind reactance X, with E(t) backed out of the recording. The true model then reproduces the validation recordings to under 3% of the flat-prediction error, and the three deliberately wrong versions in the test come out 26 to 66 times worse. r0 against r1 measures how much that tool alone was costing.

r4 against r5 is the "menu with and without the true form" ablation. r4 against r6 shows what choosing among 27 structures costs when the true one is available.

## Running it

```bash
PY=../.venv/bin/python
$PY information_ladder/build_ladder.py               # harness folders (committed) and data/ (rebuilt, gitignored), about 15 s
$PY information_ladder/tests/test_ladder.py          # 33 checks, about a minute; no API, Docker or ANDES
bash information_ladder/run_ladder.sh haiku low 10 2                         # every rung, 10 runs each
bash information_ladder/run_ladder.sh sonnet low 10 2 r0_v0 r1_grid_equivalent   # the Sonnet-low baseline
$PY information_ladder/summarize_ladder.py runs/ladder_<haiku> runs/ladder_<sonnet>   # both in one table
$PY information_ladder/run_rung.py r4_menu_with_true haiku low --config scorer/config_rsi.json   # one run
```

Results go to `runs/ladder_<time>_<model>_<effort>/<rung>/`, one batch folder per rung (summary.md as usual), with `ladder_summary.md` on top. Scoring uses `scorer/config_rsi.json` by default, so grid M is scored too, as for the RSI baselines. Every rung uses the noise-free data, since r2 and r3 only exist noise-free. Runs carry the label `rung=<name>` in meta.json, and `solver/solver_run.py --resume` works on them as on any run.

Cost, roughly: Haiku-low runs have cost $0.02 to $0.04, so 70 runs should be a few dollars. The menu rungs will likely take more steps, since each fit call is a step. I don't know Sonnet-low's cost per run on this task. Scoring is about 4 minutes per run with config_rsi.json, so the Haiku ladder at parallel 2 is roughly 2 to 3 hours.

## What to know before trusting the numbers

**The 0.5 pu reactance is my estimate, not a network calculation.** It comes from the staged voltage-reference steps in grid A (ΔV/ΔQ over the first 10 to 300 ms is 0.43 to 0.48 pu; the size of the source jump points nearer 0.6). The true model replays correctly at any X, so the value only changes how hard a wrong model gets pushed back. A short-circuit calculation in ANDES at bus 3 would be the proper number for system.md.

**The internal signals are reconstructed, not simulated.** REGF1's controls are a feed-forward chain from the measured P and Q (filters, power loops, frequency command, internal angle). So `internal_signals.py` computes every column exactly from the recorded columns plus the true parameters, with the trapezoid rule on the 1 ms grid. They agree with the true model's own states to an RMS of about 1e-5. Being functions of the recording, they also stay consistent with it through the fault, where re-simulating wouldn't. If you'd rather have ANDES's own variables, that's a change to `build_test_grids.simulate_run`.

**The menu is device-generic but was written knowing REGF1.** `droop_with_power_loop` and `droop_with_reactive_loop` are REGF1's PI power-limit loops. The test checks that the true combination, with the parameters moved to the device base (×9 or ÷9), equals the truth spec to 1e-9 pu. The defaults are generic values (5% droops and the like), not the truth. `inertia` is a VSM-style block, so the same menu should cover REGF2 when that case exists.

**The fitter is slow and the parameters trade off.** Each call fits for about 100 s (under the 120 s tool limit) and is resumed with `--start`. In a test from defaults, three calls on two short windows gave droops within 0.2% (P-f) and 4.5% (Q-V) of the truth, with validation replay errors of 1 to 2% of flat. The individual P-path parameters didn't match the truth, though (m against Kpp, for example). Choosing informative windows is left to the solver.

**What isn't here.** P setpoint steps in the training data need new ANDES simulations, so that rung is missing. The worked-example idea (2) needs a REGF2 case and truth spec first. The answer-aware updater (4) belongs in the RSI loop, not here. `run_all_checks.py` doesn't run `tests/test_ladder.py`; adding it is one line in FAST_CHECKS if you want it.

## Files

| file | what it is |
|---|---|
| `build_ladder.py` | the rung definitions (text added to system.md and method.md, tools, data), and the builder |
| `harness_tools/` | the new tools' sources; the builder copies them into each rung's `tools/` |
| `harness_tools/grid_equivalent_replay.py` | replay against E(t) behind jX, Newton on states, V and theta together |
| `harness_tools/structure_menu.py` | the block menu; `list`, and `build` to a submission; reads `tools/menu_options.json` for the rung's allowed blocks |
| `harness_tools/fit_structure.py` | least-squares fit of a menu structure by grid-equivalent replay on short windows, resumable |
| `internal_signals.py` | trusted side: the internal signals from a recording and the true parameters |
| `rungs/<rung>/harness/` | the built harnesses (generated; edit `build_ladder.py` and rebuild instead) |
| `data/` | grid A noise-free with the extra columns (generated, gitignored) |
| `run_rung.py` | one solver run on a rung (solver_run.py with the rung's harness and data) |
| `run_ladder.sh`, `summarize_ladder.py` | batches over rungs, and the table |
| `tests/test_ladder.py` | the checks |
