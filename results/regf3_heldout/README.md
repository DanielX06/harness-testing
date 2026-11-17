# REGF3 held-out test

REGF3 (dVOC) is the device no harness was tuned on: grids A3 (training recordings), B3 (selection), M3 (monitor), built from `../../test_cases/grid_specs/grid_A3.json`, `grid_B3.json`, `grid_M3.json`. It is in `HELD_OUT_DEVICES` (`../../common/project_paths.py`), so no RSI loop may run on it; it is tested once, with frozen harnesses from run4 (`../../rsi_loops/2026-11-12_run4_opus-high-updater_from-wecc-docs/candidates/`). Haiku 5.5 low, clean data, `scorer/config_rsi_regf3.json`, parallel 4 on the desktop.

On these grids the flat model scores about 0.79, not 1: it matches the vref run exactly, because REGF3 ignores its voltage setpoint (see `../../scorer/truth/regf3_as_submission.py`). The Q-V droop is left out of PAR for REGF3 (`DROOPS_ABSENT` in `../../scorer/truth/__init__.py`).

| folder | harness | runs | selection (B3) mean | old name |
|---|---|---|---|---|
| `2026-11-16_regf3_h000-run4-start_haiku-low_clean_20runs` | h000, run4's starting harness (WECC docs, no fitting tool) | 20 | 0.620 | `2026-11-16_210530_haiku-low_clean_regf3_h000` |
| `2026-11-16_regf3_h008-run4-final_haiku-low_clean_20runs` | h008, run4's final harness (fit_model.py) | 20 | 0.424 | `2026-11-16_223913_haiku-low_clean_regf3_h008` |
| `2026-11-17_regf3_h002-run4-iter2_haiku-low_clean_20runs` | h002, the harness iteration 2 accepted (fit_model.py first added) | 20 | 0.571 | `2026-11-17_*_haiku-low_clean_regf3_h002` |

The no-solver fit of h008's template (no LLM) is in `../../analyses/no_solver_h008/REGF3/` on the Mac: 1.302, every simulation failed. The gate (truth 0, flat 0.79) is `../../test_cases/grid_B3_check.json` and `grid_M3_check.json`. The analysis is in the project doc "REGF3 held-out test" (Nov 17).
