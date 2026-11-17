I saved a submission, but it is a partial model. The active-power path is reasonable. The reactive-power path is essentially a constant, which scores about 1.0 (no better than a constant output), so the Q half of the score will be poor.

**Model (in `submission.json`)**

- **Active power.** A grid-forming power-angle relation with a fixed internal voltage V0 and coupling reactance XL = 1.0 pu. The internal angle delta follows a P-f droop, d(delta)/dt = w0·mp·(P0 − Pm), with mp = 0.06. Pm is a 10 ms filtered copy of the output P, which is what the droop sees.
  - Output: P = V·V0·sin(delta − theta)/XL.
  - Initial angle: theta0 + asin(XL·P0/V0²), written with `atan2` and `sqrt` because `asin` is not allowed.
- **Reactive power.** Qm is a first-order lag (0.5 s) toward Q0 + kqv·(V − V0), with kqv = 0. It is at rest at t = 0 and holds Q0 throughout, so the output is a constant.

**Evidence**

- The ambient recordings show P tracking frequency at roughly −0.05 pu per rad/s of angle drift. That corresponds to mp ≈ 0.05; the grid search settled on 0.06.
- Q barely changes in any recording. In the generator-trip case V falls about 4% while Q stays at 0.1706. Staged Vset steps of ±2% also leave Q unchanged. Linear regressions of Q on V, Vset, P, and a washed-out angle explain under 4% of its variance.
- The full-order droop template I started from (with the generic Q-V and voltage loops) gave Q errors above 1 on every recording, so I dropped it.

**Validation**

- Using `--eval` on the val files, P errors are about 0.10 for the load test and 0.13 for the vref test. The fault recording is the outlier at about 0.6.
- Q errors are about 1.0, so the mean validation error is about 0.59.
- The model is stable (slowest eigenvalue about −2 1/s, also when tied to a 0.3 or 0.6 pu source), and `check_submission.py` reports it at rest at t = 0.
- I did not finish the full tool fit. It exceeded the time limit, and I did not get a complete fit of the template.

**Parameter identification**

- mp is reasonably identified. It is set by the frequency-drift response in the ambient data.
- XL is poorly identified: the grid search preferred the largest value tried, so the P response is weakly sensitive to the coupling reactance and XL=1.0 is an empirical choice rather than a measured one.
- TPf and TQ are not identified. They were fixed at 0.01 s and 0.5 s.
- The Q-V relationship and the role of Vset are not identified. The data show no measurable Q response to either, and the setpoint feed-forward I tried made Q errors much worse.

**Next steps**

- Model Q with a different structure, or identify whether the device controls voltage at all; the current data do not support any Q-V droop.
- Refit XL and mp with the full tool once the optimiser can run within the time limit.

```json
{
  "params": {
    "XL": 1.0,
    "mp": 0.06,
    "TPf": 0.01,
    "TQ": 0.5,
    "kqv": 0.0,
    "w0": 376.99111843077515
  },
  "defs": {
    "dl": "delta - theta",
    "Pe": "V*V0*sin(dl)/XL"
  },
  "states": {
    "delta": {
      "rhs": "w0*mp*(P0-Pm)",
      "init": "theta0 + atan2((P0*XL/V0**2), sqrt(1-(P0*XL/V0**2)**2))"
    },
    "Pm": {
      "rhs": "(Pe-Pm)/TPf",
      "init": "P0"
    },
    "Qm": {
      "rhs": "(Q0 + kqv*(V-V0) - Qm)/TQ",
      "init": "Q0"
    }
  },
  "outputs": {
    "P": "Pe",
    "Q": "Qm"
  }
}
```