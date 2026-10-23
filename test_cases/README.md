# Test cases: grid A (training), grid B (selection) and grid M (hidden monitor)

Grid A is what the agent learns from: Kundur's two-area system with the device in generator 3's slot, recorded the way an operator would have it. Grid B is the selection grid. It's the same machines re-arranged, the agent never sees it, and its score is the one that goes to `public.json` for the updater. Grid M is the hidden monitor for RSI runs: re-arranged another way, scored privately on every run, and never used to select anything, so it can show whether gains on B carry over to a grid nobody tuned on. The same device (REGF1 with the parameters from the medium Kundur case) sits in all three. Test grids C, D and E come later. The builder already takes any Kundur-family layout, and a different base network needs one more builder file.

```bash
cd "Fall DRA/Harness_testing"
PY=../.venv/bin/python
$PY test_cases/build_test_grids.py --workers 6         # all three grids, deterministic; --grids M (or A, B, or B,M) for some
$PY test_cases/draw_grid_diagrams.py                   # the one-line diagrams; add M to draw only grid M's
$PY test_cases/make_noise_free_sandbox.py              # noise-free copy of grid A's sandbox_data, for a baseline
$PY test_cases/score_wrong_models_on_grid.py M         # truth and deliberately wrong models scored on M -> monitor_check.json
```

Each grid is defined in `grid_specs/grid_<X>.json`: its purpose, the case (the device's slot, the network changes, the operating points and every run's events, including the ambient load sequence's seed), the device under test (model, rating and ANDES parameters), the operator's description of each operating point for a grid with training runs, and design notes on why the grid is the way it is. `build_test_grids.py` writes the case unchanged to `grid_<X>/holdout/case.json`, and the scorer rebuilds every held-out run from that file with `scorer/grids/kundur_family_builder.py`, the same code that simulated it, so a held-out run is replayed with exactly the events that produced its recording.

The device is a setting of the grid spec, not of the code. Putting REGF2 or REGF3 in a grid takes four things: its recording variables (P, Q and the limiters that must not bind) in `DEVICE_RECORDING_VARIABLES` in `build_test_grids.py`, its voltage-setpoint variable in `VOLTAGE_SETPOINT_VARIABLE` in the grid builder, a truth model in `scorer/truth/` (one module and one line in `TRUTH_SPEC_BUILDERS`), and its wrong versions in `score_wrong_models_on_grid.py`. Then the spec's `device_under_test` names it.

## Grid A: what the agent gets

`grid_A/sandbox_data/` is the only thing that goes into the sandbox.

* `train/*.csv` (8 runs) and `val/*.csv` (2 runs), one file per run. Columns are `time_s, active_power_pu, reactive_power_pu, voltage_pu, bus_angle_rad, voltage_setpoint_pu`. The internal angle δ is gone. P and Q are on the device's 900 MVA rating, the angle is relative to its value at t = 0, and samples are 1 ms apart.
* PMU-grade noise, the same as the medium case: σ = 0.001 on P and Q, 0.0005 on V, 0.001 rad on θ. The setpoint column has no noise because it comes from the control log.
* `runs.json` holds the operator's log for each run: operating conditions plus timestamped events ("t=5.000 s: staged test, device voltage reference stepped +2.0% of nominal (setpoint now +2.0% from schedule)"). `dataset.json` gives the rating, nominal frequency, sample period, column meanings and noise levels.
* `system_diagram.png` is a one-line diagram with the three operating points noted. It labels the device "inverter-based unit" to keep the skeleton device-generic. The old medium-case diagram says "grid-forming converter", so pick one before the harness uses either.

Operating points. **op1** is the medium case's dispatch: the device at 700 MW, voltage schedule 1.00 pu. **op2** moves the device to 450 MW with a 1.01 pu schedule, and G4 picks up the difference. **op3** has one 9-10 circuit out for maintenance and 100 MW more load at bus 8, so the device sees a weaker connection.

| run | split | op | length | what happens |
|---|---|---|---|---|
| A_amb_op1 | train | op1 | 60 s | ambient only (loads vary 1% rms) |
| A_amb_op2 | train | op2 | 60 s | ambient only |
| A_vref_op1 | train | op1 | 60 s | staged test: V_ref +2% at 5 s, back at 20 s, −2% at 35 s, back at 50 s |
| A_vref_op3 | train | op3 | 45 s | staged test: ±1% steps at 5, 15, 25, 35 s |
| A_gentrip_op1 | train | op1 | 40 s | G2 (400 MW) trips at 5 s |
| A_load_op2 | train | op2 | 40 s | bus-7 load +10% at 5 s |
| A_fault_op1 | train | op1 | 30 s | three-phase fault at bus 8, 100 ms |
| A_line_op3 | train | op3 | 30 s | one 7-8 tie circuit opens at 5 s |
| A_val_load_op1 | val | op1 | 30 s | bus-8 load −8% at 5 s |
| A_val_vref_op2 | val | op2 | 30 s | V_ref +1.5% at 5 s, back at 20 s |
| A_test_line_op1 | holdout | op1 | 20 s | one 9-10 circuit opens at 2 s |
| A_test_vref_op1 | holdout | op1 | 20 s | V_ref −1.5% at 2 s, back at 12 s |

Every train and val run that has an event also has light ambient variation (0.3% rms) underneath, as a live grid would. The two holdout runs are clean and never reach the agent. `config_min.json` scores them privately as a same-grid diagnostic (role `train_holdout`), so the gap between them and grid B shows how much the agent fit grid A rather than the device.

`sandbox_data_clean/` is the same folder without measurement noise, for a noise-free baseline. `make_noise_free_sandbox.py` builds it from the `holdout/*_clean.csv` recordings without re-simulating, checks each one against its noisy twin (same time and setpoint columns, residual spread equal to the stated σ), and sets the noise levels in `dataset.json` to zero. Re-run it after `build_test_grids.py`. The solver gets it with `--noise clean` (or `clean` as the fifth argument of `solver/run_solver_batch.sh`). Scoring doesn't change, because the held-out runs are clean either way.

## Grid B: the selection grid

B is Kundur re-arranged rather than weakened. Its connection strength and frequency stiffness stay close to Kundur's, so the score gaps keep their size.

| | grid A (op1) | grid B |
|---|---|---|
| 7-8 tie | 3 circuits | 2 circuits (Line_6 out) |
| load at the device's HV bus 9 | none | 200 MW, 30 Mvar (new) |
| loads at buses 7 / 8 / 10 | 859 / 1425 / 150 MW | 900 / 1200 / 150 MW |
| device dispatch | 700 MW, schedule 1.00 pu | 720 MW, schedule 1.02 pu |

Held-out runs (all at one operating point, because the scorer evaluates FR and PAR at one point per grid). Each is 25 s with the event at 2 s. The disturbances differ in kind, place or size from anything in training:

| run | event |
|---|---|
| B_vref | V_ref +2.5% at 2 s, back at 14 s |
| B_load | the new bus-9 load +50% (100 MW, 15 Mvar) |
| B_line | one 8-9 circuit opens |

Why 720 MW: the device's loading decides whether a voltage-loop error is visible at all. With B first built at 550 MW, a 30% error in the voltage-loop gain KPv cost only 0.02 to 0.06 on a line trip. At 700 MW the same error cost 0.16 to 0.22, and at grid A's op1 it saturates the cap of 2. 720 MW keeps that error visible without saturating, and it sits just above anything in the training data.

Score of deliberately wrong versions of the true device (composite; flat = 1, truth = 0), on grid B, on grid A's two held-out runs, and on the old 10 s Kundur stand-in:

| error | grid B | grid A held-out | old stand-in |
|---|---|---|---|
| ideal current loop | 0.011 | 0.015 | 0.017 |
| wdrp × 0.8 | 0.120 | 0.125 | 0.134 |
| Qdrp × 0.8 | 0.046 | 0.054 | 0.052 |
| Tpm × 2 | 0.162 | 0.172 | not run |
| KPv × 0.7 | 0.53 | 1.13 (TD at the cap) | not run |

Droop and filter errors cost within about 15% of what they cost on Kundur, so B doesn't shrink the gaps the RSI accept rule needs. A voltage-loop gain error is clearly visible on B, though one of its three runs (the line trip) hits the cap. The full per-run numbers are in `selection_check.json`.

## Grid M: the hidden monitor

M is there so an RSI run can tell a real improvement from tuning to grid B. Nothing selects on it, and neither the agent nor the updater ever sees it. `../scorer/config_rsi.json` scores it privately on every run, next to grid A's held-out runs. If the B score keeps improving while M's stalls, the loop is fitting B. M's runs are the same three kinds as B's, in other places, directions and sizes, on a different arrangement at a similar strength, so a real improvement should show on both.

| | grid A (op1) | grid B | grid M |
|---|---|---|---|
| 7-8 tie | 3 circuits | 2 circuits (Line_6 out) | 3 circuits |
| other outage | none | none | one 5-6 circuit (Line_1) |
| loads at buses 7 / 8 / 9 / 10 | 859 / 1425 / 0 / 150 MW | 900 / 1200 / 200 / 150 MW | 1000 / 1150 / 0 / 300 MW |
| G2 / G4 | 400 / 700 MW | 400 / 700 MW | 500 / 650 MW |
| device dispatch | 700 MW, schedule 1.00 pu | 720 MW, schedule 1.02 pu | 650 MW, schedule 1.01 pu |
| least-damped mode with the true device | 0.59 Hz, ζ = 0.058 | 0.53 Hz, ζ = 0.079 | 0.92 Hz, ζ = 0.056 |

Held-out runs, 25 s each, event at 2 s, one operating point:

| run | event |
|---|---|
| M_vref | V_ref −1.5% at 2 s, back at 14 s |
| M_load | the bus-10 load −40% (−120 MW) |
| M_line | one 6-7 circuit opens |

Three drafts failed before this one:

* At 680 MW and a 0.99 pu schedule, the grid with the true device in it had a 0.93 Hz mode at a damping ratio of 0.009, and the voltage-reference run swung V between 0.84 and 1.15 pu. In an ANDES EIG scan, damping rose with the schedule and fell with dispatch, so M runs at 650 MW and 1.01 pu.
* A −2.5% reference step pushed the operating point into a less damped region, and the 0.9 Hz swing barely decayed over 12 s. At −1.5% it rings about as much as B's own step back down at 14 s.
* Opening a 9-10 circuit moved the device's P by an RMSE of only 0.0019 pu, under the scorer's 3σ floor of 0.003, so the flat model scored 0.97 instead of 1. The 6-7 circuit moves P and Q by 0.021 and 0.037 pu (B_line: 0.016 and 0.069). A 7-8 tie trip penalised the wrong models about the same but moved P by only 0.006.

Score of deliberately wrong versions of the true device (composite; flat = 1, truth = 0):

| error | grid B | grid M |
|---|---|---|
| ideal current loop | 0.011 | 0.015 |
| wdrp × 0.8 | 0.120 | 0.142 |
| Qdrp × 0.8 | 0.046 | 0.054 |
| Tpm × 2 | 0.162 | 0.188 |
| KPv × 0.7 | 0.53 (B_line at the cap) | 1.04 (M_vref and M_line at the cap, M_load's Q too) |

On the P side, droop, filter and current-loop errors cost M almost exactly what they cost B, run for run. M's Q channel charges more for the same errors because M's Q swings are smaller (the TD divides by them), which puts the composite 15 to 25% higher. The one real difference is the voltage-loop gain. M's 0.9 Hz mode is less damped than B's (0.056 against B's 0.098 for its 0.89 Hz mode), so a 30% low KPv saturates two of M's runs where it saturates one of B's. Grid A's held-out runs saturate as well (1.13), so it is B that forgives this error, not M that is extreme. For a monitor that is useful: a B-tuned harness that drifts toward a wrong voltage-loop gain would pass B and show up on M. Per-run numbers are in `monitor_check.json` (`score_wrong_models_on_grid.py M` regenerates it). How the 22 calibration runs score on M is in `../experiments/monitor_grid/results.md`.

## Limits worth knowing

1. **Only voltage-reference steps.** REGF1 in ANDES has no active-power setpoint or frequency reference that acts during a run. `Pref` is used only at initialization, and a step on `Paux` feeds an integrator, so P runs away until the frequency limit. The P-setpoint and frequency-reference parts of MOD-026/027 testing can't be reproduced without editing the device model.
2. **Ambient is piecewise constant.** Each load's P and Q follow an Ornstein-Uhlenbeck process (5 s correlation time) held for 0.5 s between updates. Every update is a small step, so the clean P shows small spikes every 0.5 s. A finer update would be smoother but slower to simulate.
3. **No AGC.** After a load change or a voltage step (constant-impedance loads draw more at higher voltage), frequency settles off nominal and the bus angle ramps, by about −4 rad over 15 s in A_vref_op1. That's physical for a grid with governors and no secondary control.
4. **1 kHz sampling.** Real PMUs report at 30 to 60 frames per second, and at that rate the 6 to 18 ms filters would be invisible. These cases keep 1 ms, as before.
5. **The old medium case is untouched,** but the scorer no longer loads it: the stand-in builder and config were removed on Oct 11, so the "old stand-in" column above can't be re-run from here.

## Checks

* The generic builder rebuilds the old medium case's test_2 run to 5e-11 pu, so the new grids come from the same simulator setup.
* No limiter binds in any run (Psig, Qsig and dw ranges are in each `answer_key.json`). Peak-to-peak SNR is at least 17 on every channel of every run (the lowest is P in A_amb_op1). The full table is in each answer key.
* The true device, written as a submission, scores exactly 0 on grid B and on grid A's held-out runs, and flat scores exactly 1. That includes the voltage-reference runs, so the setpoint step reaches the submission the same way it reaches REGF1.
* Grid M (Oct 17) was built in the cloud with ANDES at the same commit as the venv (eda5163). The same setup rebuilt grid B's three recordings byte for byte (identical SHA-256). On M the truth scores exactly 0 and flat exactly 1, no limiter binds (Qsig peaks at 2.61 against a limit of 9 on the system base), and peak-to-peak SNR is at least 22 (P in M_vref).
