The submitted model runs and starts at rest, but it is a compromise. Its reactive-power fit is the weakest part, and the choice between candidates was made on the grid replay, not on the training fit.

**Model (negative reactive droop, lagged frequency-droop P)**

- Reactive power: `Q = Q0 + Kp·(Vset − V0) + xi − 1.0·(V − V0)`, with `xi' = Ki·(Vset − V)`. This is a proportional-integral voltage regulator with a unit droop on terminal voltage.
- Active power: `P` is a first-order lag (`Tp`) toward `P0 − Dp·ω + Kpv·(V − V0)`, where `ω = (θ − xw)/Tf` and `xw` is a lagged copy of θ acting as a high-pass frequency estimate.
- Unused lag `vm` (time constant `Tv`) is carried in the file but has zero weight, so it has no effect.

**Parameters**

- `Kp = 1.0` and `Ka = −1.0` are fixed by hand rather than fitted, so they are not identified from data.
- `Ki ≈ 0.21`: moderately identified from the voltage-step tests.
- `Dp ≈ 0.045`: P response to angle drift; weakly identified, since the angle drift is small and noisy in effect.
- `Kpv ≈ −0.012`, `Tp ≈ 0.026 s`, `Tf ≈ 0.005 s`: the fast P dynamics are well determined from the steps but the frequency filter constant trades off against `Dp`.
- `Tv` and `Kb` are not identified in this submission, since their weight is zero.

**What the data showed**

- Q responds to voltage-setpoint steps with a fast jump followed by a slower settle, and the best-fitting static relation between Q and V was positive (about +2). A positive gain of that size is marginally unstable against the 0.5 pu source equivalent, and the grid replay diverged with it. I rejected that fit on stability grounds.
- The constrained fits (negative or zero direct V gain) fit reactive power noticeably worse on the training data (about 0.024–0.03 pu RMS on the step tests, against about 0.005 for the unconstrained fit).
- A two-path variant with zero direct gain and a slow positive lagged term was stable on the reference-test validation file but distorted voltage on the load-change file (V error 0.0116 against 0.0050 for the negative-droop model). I rejected it on that basis.

**Validation numbers (grid-equivalent replay, validation files)**

- `A_val_load_op1`: P RMSE 7.4e-4, Q 9.2e-3, V 5.0e-3 (flat baselines: P 2.4e-2, Q 2.8e-2, V 4.8e-3).
- `A_val_vref_op2`: P 5.4e-4, Q 1.44e-2, V 6.7e-3 (flat: P 5.9e-3, Q 2.95e-2, V 9.5e-3).
- The open-loop check on `A_val_load_op1` gives Q RMSE 2.1e-2 against a flat 2.8e-2, so reactive response to the load event is only partly captured.

**Main risks**

- The sign of the steady reactive-voltage gain is the key uncertainty. The data favours a positive gain, the stability check and the documented droop favour negative. I chose negative. If the scorer's droop check compares against a positive real gain, this model will be penalised there.
- Dynamics of reactive power beyond the single lag and integrator are not captured.

```json
{
  "params": {
    "Kp": 1.0,
    "Ki": 0.21456410595128592,
    "Tv": 0.04711031782173438,
    "Ka": -1.0,
    "Kb": 0.0,
    "Dp": 0.045196579211498104,
    "Kpv": -0.01200837257261949,
    "Tf": 0.00515742115222678,
    "Tp": 0.026186366150144677
  },
  "defs": {
    "om": "(theta-xw)/Tf",
    "Pt": "P0-Dp*om+Kpv*(V-V0)"
  },
  "states": {
    "vm": {"rhs": "(V-vm)/Tv", "init": "V0"},
    "xi": {"rhs": "Ki*(Vset-V)", "init": "0.0"},
    "ps": {"rhs": "(Pt-ps)/Tp", "init": "P0"},
    "xw": {"rhs": "(theta-xw)/Tf", "init": "theta0"}
  },
  "outputs": {
    "P": "ps",
    "Q": "Q0+Kp*(Vset-V0)+xi+Ka*(V-V0)+Kb*(vm-V0)"
  }
}
```