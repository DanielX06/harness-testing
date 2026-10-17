# Minimum test cases: grid A (training) and grid B (selection)

Grid A is what the agent learns from: Kundur's two-area system with the device in generator 3's slot, recorded the way an operator would have it. Grid B is the selection grid. It's the same machines re-arranged, the agent never sees it, and its score is the one that goes to `public.json` for the updater. The same device (REGF1 with the parameters from the medium Kundur case) sits in both. Test grids C, D and E and the hidden REGF1 monitor grid come later. The builder already takes any Kundur-family layout, and a different base network needs one more builder file.

```bash
cd "Fall DRA/Harness_testing/test_cases"
PY=../../.venv/bin/python
$PY build_cases.py --workers 6      # both grids, deterministic; --grids A or --grids B for one
$PY draw_grids.py                   # the two one-line diagrams
$PY make_clean_sandbox.py           # noise-free copy of grid A's sandbox_data, for a baseline
```

Every run is described in `grid_*/holdout/case.json` (operating point plus every event, including the ambient load sequence's seed). The scorer rebuilds runs from that file with `scorer/grids/kundur_family.py`, so a held-out run is replayed with exactly the events that produced its recording.

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

`sandbox_data_clean/` is the same folder without measurement noise, for a noise-free baseline. `make_clean_sandbox.py` builds it from the `holdout/*_clean.csv` recordings without re-simulating, checks each one against its noisy twin (same time and setpoint columns, residual spread equal to the stated σ), and sets the noise levels in `dataset.json` to zero. Re-run it after `build_cases.py`. The harness picks it up with `--noise clean` (or `clean` as `run_batch.sh`'s fifth argument). Scoring doesn't change, because the held-out runs are clean either way.

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
