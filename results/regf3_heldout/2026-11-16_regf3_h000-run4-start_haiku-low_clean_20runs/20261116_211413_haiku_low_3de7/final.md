The submission is saved and passes the checker, but the Q channel is not good enough to call done. I'm stopping here on budget.

**Submission (`submission.json`)**: a WECC-droop-style structure, fitted open-loop on `train/`.

- Internal voltage `E` behind a reactance `XL` (Re = 0), with the terminal P and Q given by the standard expressions in `delta − theta`.
- Angle state `delta` with `d(delta)/dt = w0·mp·(P0 − Pm)`, where `Pm` is the filtered P. This is the active-power droop.
- Filtered `Pm`, `Qm`, `Vm` with time constants `TPf`, `TQf`, `TVf`.
- Voltage loop: `Vcmd = Vset + mq·(Q0 − Qm)`, `xv' = kiv·(Vcmd − Vm)`, `E = clip(kpv·(Vcmd − Vm) + xv, 0, 1.15)`.
- Initial states come from the operating point: `E0` and `delta0` from the power-flow relations, so the model starts at rest.

**Fitted values**: XL = 0.25, mq = 6.26, kiv = 3.0, kpv = 0.00055, mp = 0.05, TPf = TQf = TVf = 0.01 s.

**Identification**
- The fit is poorly identified and pushed against bounds. XL sits at its upper bound, mp at its upper bound, kiv at its lower bound, and the three filter constants at their lower bounds.
- mq is large (about 6), which matches the data: a 2% setpoint step barely moves Q, so the device's steady Q-V slope is small. That gives dQ/dV ≈ −1/mq, which is weak but not well pinned down.
- kpv is essentially zero and is poorly determined.
- The fault and gen-trip transients (large, fast P and Q swings) set XL and the filter constants. These are not well separated from the mp and kiv effects.

**Validation (open loop, measured V, θ, Vset)**

| File | P RMSE | P naive | Q RMSE | Q naive |
|---|---|---|---|---|
| A3_val_load_op1 | 0.0019 | 0.0192 | 0.0035 | 0.0014 |
| A3_val_vref_op2 | 0.0001 | 0.0008 | 0.0017 | 0.0001 |

"Naive" means holding the initial P or Q constant.

- P is clearly better than a constant on both files.
- Q is worse than a constant on both files. The voltage-loop Q dynamics I fitted add error that the data does not support. The Q model is the weak point, and I did not get to a better structure.
- The fit was run only on a 10 s window of the training recordings, with a coarse optimizer and about 250 function evaluations in total.
- Closed-loop behaviour in the grid was not tested. Because mp, XL and kiv sit at bounds, the device may react differently in closed loop than in open-loop replay.
- The scorer's droop checks (dP/dω and dQ/dV) are unverified.

The checker reports the model as valid and at rest at t = 0 on both validation files.

```json
{
  "params": {"XL": 0.25, "mq": 6.256, "kiv": 3.0, "kpv": 0.00055, "mp": 0.05, "TPf": 0.01, "TQf": 0.01, "TVf": 0.01, "w0": 376.99111843077515, "Emax": 1.15},
  "defs": {
    "Vc": "Vset + mq*(Q0 - Qm)",
    "Eint": "Min(Max(kpv*(Vc - Vm) + xv, 0), Emax)",
    "a": "delta - theta",
    "Pe": "V*Eint*sin(a)/XL",
    "Qe": "(Eint*V*cos(a) - V**2)/XL"
  },
  "states": {
    "delta": {"rhs": "w0*mp*(P0 - Pm)", "init": "theta0+atan2(XL*P0/V0, V0+XL*Q0/V0)"},
    "Pm": {"rhs": "(Pe - Pm)/TPf", "init": "P0"},
    "Qm": {"rhs": "(Qe - Qm)/TQf", "init": "Q0"},
    "Vm": {"rhs": "(V - Vm)/TVf", "init": "V0"},
    "xv": {"rhs": "kiv*(Vc - Vm)", "init": "sqrt((V0+XL*Q0/V0)**2+(XL*P0/V0)**2)"}
  },
  "outputs": {"P": "Pe", "Q": "Qe"}
}
```