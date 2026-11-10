The submission is written to `submission.json` and passes the checker on both validation recordings. It is a reasonable first model, not a fully resolved one.

**Model**

- **Reactive power:** Q is a first-order lag (time constant Tq ≈ 0.010 s) driven by a voltage-reference term and a terminal-voltage term: `dx/dt = (Kqs·(Vset−V0) + Kqv·(V−V0) − x)/Tq`, with `Q = Q0 + x + Kqf·ω`.
- **Active power:** `P = P0 + Kpv·(V−V0) + Kf·ω`, with a small voltage sensitivity Kpv.
- **Frequency estimate:** ω is estimated as `(θ − θ_l)/Tf`, where θ_l is a lagged copy of θ with time constant Tf. This gives the exact steady ramp rate, so it can carry the droop term.

**Fitted values (train)**

| Parameter | Value | Note |
|---|---|---|
| Kqs | 1.48 | Q per pu setpoint; well identified from the staged steps |
| Kqv | 0.56 | Q per pu voltage; well identified |
| Tq | 0.010 s | Short; Q is nearly static |
| Kpv | −0.21 | Poorly identified; trades off against Kf |
| Kf | −0.045 | P droop on ω; poorly identified |
| Tf | 1.60 s | Poorly identified; this is the least trustworthy value |
| Kqf | −0.046 | Q term on ω; poorly identified |

Tf is the weakest part of the model. The fit moved it from about 0.1 s to 1.6 s across attempts, and the frequency estimate is not reliable. The droop and frequency-related terms should be treated as tentative.

**Rejected candidates**

- A washout of θ: it cannot carry steady droop after the gen-trip event, so P was wrong over the long drift.
- The earlier fit without a frequency term: it had a residual of about 0.043 on Q in the gen-trip recording.
- The P-droop-only fit: it fixed P but left the gen-trip Q error at 0.043.

**Validation (open-loop replay, RMSE vs flat baseline)**

- `A_val_load_op1`: P 0.0051 (flat 0.024), Q 0.0088 (flat 0.028)
- `A_val_vref_op2`: P 0.0042 (flat 0.007), Q 0.0044 (flat 0.028)

Both are well above the 0.001 noise on P, so there is still unexplained structure, probably in the frequency response.

```json
{
  "params": {
    "Kqs": 1.482,
    "Kqv": 0.5611,
    "Tq": 0.0103,
    "Kpv": -0.2117,
    "Kf": -0.0454,
    "Tf": 1.5988,
    "Kqf": -0.0463
  },
  "defs": {
    "om": "(theta-th_l)/Tf"
  },
  "states": {
    "x": {"rhs": "(Kqs*(Vset-V0)+Kqv*(V-V0)-x)/Tq", "init": "0.0"},
    "th_l": {"rhs": "(theta-th_l)/Tf", "init": "theta0"}
  },
  "outputs": {
    "P": "P0+Kpv*(V-V0)+Kf*om",
    "Q": "Q0+x+Kqf*om"
  }
}
```