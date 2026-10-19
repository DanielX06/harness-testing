# Closed-loop scorer for terminal-model submissions

The agent submits its device model as equations in a JSON file. For every held-out run, the scorer drops that model into the grid in ANDES in place of the real device, re-runs the same disturbance, and compares the device's terminal P and Q with the clean recording. It also linearizes the submitted model to compare its frequency response and droops with the truth. Everything in this folder is trusted kernel code. The agent and the updater never see it, except `symbolic.py`, which `harness_v0/run_harness.py` copies into the agent's `tools/` (locked) so the agent-side checker parses with exactly these rules.

## Why closed loop, and how it works

Open-loop replay (driving the model with the recorded V and theta) failed on the true model: REGF1's inner current loop is unstable once V and theta are held fixed, because ANDES only damps it through the network impedance. Closed loop has no such problem. `truth/regf1_spec.py` writes REGF1 as a submission, and run closed loop it reproduces the case CSVs to 6e-6 pu at worst, so the truth now scores exactly 0.

ANDES only runs models written in its own format and registered in its model list. `closedloop.py` fills a fixed ANDES model template with the submission's equations, which have been parsed and re-printed by sympy. It then registers the class at runtime and generates its numerical code into a per-score copy of the pycode folder, so `~/.andes/pycode` is never touched. Each run is a separate process (spawn) with a timeout, and runs go in parallel.

A submission is pure data. Expressions are converted from the Python AST to sympy node by node against a whitelist, and nothing is ever `eval`'d, so no Docker sandbox is needed for scoring. Code injection and attribute access are rejected; the tests check both.


## Submission format (agent-facing contract)

```json
{
  "params":  {"Kp": 5.0, "T": 0.05, "Kq": 25.0},
  "defs":    {"Pc": "P0 + Kp*sin(theta - delta)"},
  "states":  {"delta": {"rhs": "-(Pc - P0)/T", "init": "theta0"}},
  "outputs": {"P": "Pc", "Q": "Q0 - Kq*(V - V0)"}
}
```

(Illustrative only: it parses and starts at rest, but it is not a good model.)

* **Symbols.** `V` and `theta` are the terminal voltage magnitude (pu) and bus angle (rad), both live. `Vset` is the device's voltage setpoint (pu), also live: it equals `V0` until an operator steps it (the staged voltage-reference tests), and the data log it in the `voltage_setpoint_pu` column. `V0`, `theta0`, `P0` and `Q0` are the operating point at t = 0, with P and Q in pu on the device rating. `pi` is also available, along with the params, the states, and any defs already defined.
* **defs** are named intermediate expressions. They are evaluated in order and must not refer to themselves in a cycle. They are substituted inline, so there are no algebraic loops.
* **init** expressions may use `V0`, `theta0`, `P0`, `Q0`, `pi`, params and other states' inits (not `Vset`, which equals `V0` at t = 0). They should put the model at rest at the operating point. Setpoints should come from the operating point rather than being hardcoded, because held-out grids run at different dispatch.
* **Functions:** sin, cos, tan, exp, log, sqrt, tanh, atan, atan2, Abs, Min, Max. Operators: `+ - * / **`.
* **Limits:** 60 states, 200 defs, 200 params, 4000 characters per expression. Time `t` is not available.
* `baselines/flat.json` is the smallest valid submission.

`python tools/check_submission.py submission.json val/A_val_vref_op2.csv` (the agent-side checker in `harness_v0/harness/tools/`) parses the file with the scorer's rules, checks that the first sample is a steady state, and replays the run open loop (measured V and theta, logged Vset) as a sanity check.

**How a setpoint step reaches a submission.** The submission's `Vset` becomes a constant `c_Vset` in the generated ANDES class. A held-out voltage-reference step is an ANDES `Alter` on that constant, at the same time and size as the `Alter` on REGF1's `vref` that produced the recording. The truth spec uses `Vset` in its voltage reference, and it reproduces the grid B step run to 1e-8 pu.

## How a submission is scored

All components are normalized so that the flat prediction scores exactly 1.0 and the true model 0. Each component is capped at 2, and a failure scores 2.

* **Time domain (TD, 0.5).** For each held-out run, closed loop:

  $$\frac{1}{2|R|}\sum_r\sum_{y\in\{P,Q\}}\min\left(2,\ \frac{\mathrm{RMSE}(\hat y_r-y_r)}{\max(\mathrm{RMSE}(y_r(0)-y_r),\,3\sigma_y)}\right)$$

  If ANDES fails (the grid loses stability, initialization fails, or there's a timeout, NaN, or |P| or |Q| above 50 pu), that run scores 2 on both channels. Bus V and theta errors are logged in `private.json` but not scored.
* **Frequency response (FR, 0.3).** The submission is linearized exactly with symbolic Jacobians at the grid's operating point, with V and theta held. This gives the 2x2 response $G(j\omega)=C(j\omega I-A)^{-1}B+D$ at 40 log-spaced points from 0.1 to 10 Hz. Each of the four entries (P/V, P/theta, Q/V, Q/theta) gets a pointwise relative error, averaged over frequency and divided by the same average for $G = 0$. The score is the mean over the four entries. Open-loop instability is not penalized here, since the true model has it; closed-loop instability shows up in TD.
* **Droops (PAR, 0.2).** These are taken from the same linearization: dP/dω is the limit of $G_{P\theta}(j\omega)/j\omega$, and dQ/dV is the limit of $G_{QV}(j\omega)$. Both are evaluated at 1e-4 Hz and checked against 1e-5 Hz. If they don't converge (no droop, or a pure integrator), that gain scores 2. The error per gain is $|g - g_{true}|/|g_{true}|$. For the truth this gives 22.1546 rad/s per pu and 0.039838 pu V per pu Q, matching the answer key.
* **Grid score** = 0.5 TD + 0.3 FR + 0.2 PAR. **Role score** = 0.5 × mean + 0.5 × worst over that role's grids.
* **Outputs.** `public.json` covers the selection grids only. `private.json` holds everything: test and monitor grids, V and theta errors, readable droops, init residual, open-loop eigenvalues and structure.

## Running it (Mac, in the shared `Fall DRA/.venv`: ANDES 2.0.0, sympy, pandas)

```bash
cd "Fall DRA/Harness_testing/scorer"
PY=../../.venv/bin/python
$PY score.py baselines/flat.json --config config_min.json --out runs/flat
$PY score.py path/to/submission.json --config config_min.json --out runs/<name> [--workers 4]
$PY score.py path/to/submission.json --config config_rsi.json --out runs/<name>   # adds grid M (monitor)
$PY tests/test_scorer.py            # config_min.json; --quick skips the sensitivity sweep
```

When calling `score_submission()` from the RSI loop script, keep the script's top level under `if __name__ == "__main__":`. On macOS, worker processes are spawned, and spawned processes re-import the main script.

## Test results on the minimum test cases (config_min.json, Oct 10)

Scored in the cloud with ANDES 2.0.0 built from the same commit as your venv (eda5163). The generic builder reproduces the old medium case's test_2 run to 5e-11.

| submission | grid B (selection) | grid A held-out (diagnostic) |
|---|---|---|
| flat baseline | 1.0 / 1.0 / 1.0 | 1.0 / 1.0 / 1.0 |
| true REGF1 (13 states) | 0 / 0 / 0 (Vset step reproduced to 1e-8 pu) | 0 / 0 / 0 |
| ideal current loop | 0.011 | 0.015 |
| wdrp × 0.8 | 0.120 | 0.125 |
| Qdrp × 0.8 | 0.046 | 0.054 |
| Tpm × 2 | 0.162 | 0.172 |
| KPv × 0.7 | 0.533 (TD 0.80; the line trip run hits the cap) | 1.132 (TD at the cap) |

Composite scores unless shown as TD / FR / PAR. Per-run numbers are in `../test_cases/selection_check.json`.

`tests/test_scorer.py --quick` passes on config_min. One check changed: the destabilizing submission used to be expected at TD = 2. On grid B its voltage-reference run is a no-op for a model that ignores `Vset` (nothing else moves), so that run scores exactly like flat. The test now requires a crash on every run that disturbs the network and no run better than flat.

## Test results on the stand-in (run here with ANDES 2.0.0 at the same commit as your venv, Oct 9)

| check | result |
|---|---|
| flat baseline | 1.0 / 1.0 / 1.0, PASS |
| true REGF1 (13 states) as a submission | 0.0 / 0.0 / 0.0; V RMSE 4e-7, theta 2e-6, PASS |
| REGF1 with ideal current loop (9 states) | 0.017 (TD 0.019, FR 0.025, PAR 0), PASS |
| wdrp × 0.8 / 1.0 / 1.25 | 0.134 / 0 / 0.121, PASS |
| Qdrp × 0.8 / 1.0 / 1.25 | 0.052 / 0 / 0.052, PASS |
| invalid JSON / unknown name / code injection / attribute access | 2.0 each, PASS |
| destabilizing model (grid fails in ANDES) | TD 2.0, PASS |
| run timeout | TD 2.0, PASS |

Before scoring I reproduced your `test_1` and `train_3` CSVs with my ANDES install to 5e-11, so the results above are from the same simulator. One score on the stand-in (two 10 s runs in parallel) takes about 50 to 65 s here, and each 10 s ANDES run takes about 30 s.

## Files

| file | what it does |
|---|---|
| `score.py` | CLI and `score_submission()` |
| `symbolic.py` | parses and checks submissions, lambdify for replay, exact linearization |
| `closedloop.py` | ANDES model template, runtime registration, codegen, parallel runs with timeouts |
| `metrics.py` | TD, FR and droop errors |
| `cases.py` | loads grids in the `kundur_family_v1` format (test_cases/grid_*) |
| `grids/kundur_family.py` | rebuilds any Kundur-family grid from its `holdout/case.json` (network, operating point, events) with any device in the slot |
| `config_min.json` | minimum test cases: grid B as the selection grid, grid A's two held-out runs as a private same-grid diagnostic |
| `config_rsi.json` | for RSI runs and anything compared with them: `config_min.json` plus grid M as a hidden monitor (role `monitor`, private, never used to accept). Built and checked in `../test_cases` (grid M section of its README) |
| `truth/regf1_spec.py` | REGF1 as a submission (full and ideal current loop) |
| `baselines/flat.json` | floor baseline |
| `tests/test_scorer.py` | the checks above |

## Open questions

1. **Closed loop compresses the scale.** In open-loop replay, wdrp × 0.8 scored 0.40. Closed loop it scores 0.13, because the grid partly absorbs the device's error. Good and mediocre candidates now differ by smaller numbers, which matters for how many reps the keep/revert rule needs.
2. **The score still leans on the P side, and that is physics.** At 20% off, Qdrp costs about 0.04 to 0.05 and wdrp about 0.12. A Q-V droop of 4% is stiff next to the network reactance the device sees (about 0.3 pu on its rating), so the network largely sets Q and the slope barely moves it: in steady state $\Delta Q = \Delta V_{set}/(R_q + X_{th})$. Voltage-reference steps in the new cases give clean Q-V runs but do not change that ratio. Q-V droop errors register at full size in PAR and in the Q/V frequency-response entry.
3. **The droop errors leak the true droop to the updater** via `public.json` plus the transcripts. Decided Oct 17: the updater gets only the composite, the TD per held-out run and channel, and failure messages, since an operator could compute TD from held-out recordings but FR and PAR need the true model. FR and PAR still feed the accept rule. `public.json` itself still carries them, so the RSI loop's context builder has to strip them. The composite minus half the TD still gives 0.3 FR + 0.2 PAR per run, one mixed number, which is one reason the updater gets no code execution.
4. **Grid format (done for the Kundur family).** `kundur_family_v1` covers any grid derived from kundur_full. A different base network (IEEE 14 or 39 for the test tier) needs its own builder with the same `build(device, params, run, pycode_path, spec)` signature.
5. **Cost.** Each held-out run costs one full ANDES simulation per submission. `config_min.json` has five runs (3 x 25 s on B, 2 x 20 s on A) and takes about 2.5 minutes per score on 2 cores in the cloud, less on your Mac with more workers. Dropping grid A's diagnostic runs from the config cuts that to about 1.7 minutes. `config_rsi.json` adds grid M's three 25 s runs, eight runs in all.
6. **One operating point per grid in the scorer.** `cases.py` still requires every held-out run on a grid to share its t = 0 operating point, because FR and PAR are evaluated at one point. Grid A's training data uses three operating points; grid B's held-out runs share one.
