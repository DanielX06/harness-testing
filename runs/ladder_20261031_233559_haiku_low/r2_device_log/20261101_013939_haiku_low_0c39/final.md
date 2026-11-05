The model runs, starts at rest, and matches the setpoint-test validation well. It does not capture the Q response to the bus-8 load change on the second validation recording, so I'm reporting that rather than tuning further.

**Model (first-order, 3 states)**

- **Internal angle filter** `a`: da/dt = (θ − a)/Tf, starting at θ0. The frequency estimate is w = (θ − a)/Tf, which approximates dθ/dt.
- **Active power**: xp is a lag with time constant Tp, driven by Pref = P0 − Dp·w − Kpv·(V − V0). P = xp.
- **Reactive power**: xq is a lag with time constant Tq, driven by Qref = Q0 + Kqv·(Vset − V0) − Kqvv·(V − V0). Q = xq.
- At t = 0 every state equals its operating-point value, so the model starts at rest.

**Fitted parameters (train/ only)**

| Param | Value | Notes |
|---|---|---|
| Kqv | 2.586 | Q gain on setpoint error. Well identified from the setpoint steps. |
| Tq | 0.0742 s | Q lag. Well identified. |
| Kqvv | ≈ 0 | Voltage droop term fitted to zero. An unconstrained fit gave a positive value (Q rising with V), which was positive feedback, so I constrained it. |
| Dp | 0.0452 | P droop on the frequency estimate. Moderately identified. |
| Tp | 0.0262 s | P lag. Moderately identified. |
| Kpv | 0.0120 | Weak P term on V. Poorly identified. |
| Tf | 0.0017 s | Hit its lower bound, so it is effectively a pure derivative of θ. Poorly identified, and the derivative estimate could amplify noise in the scorer's grid. |

**Validation**

- `A_val_vref_op2`: open-loop RMSE P 5.9e-4 and Q 5.9e-3 pu. Grid-equivalent RMSE P 4.9e-4, Q 5.9e-3, V 2.8e-3, θ 8.1e-4. Q is about 5× better than a flat model.
- `A_val_load_op1`: open-loop RMSE P 6.8e-4, Q 2.8e-2. Grid-equivalent Q RMSE 2.8e-2, which equals the flat baseline, so the model gives no Q gain on this load-step event.

**Caveats**

- The Q response to voltage changes from load events is not captured. The likely missing term is a negative Q-V droop, but a stable one was not identified, so I did not add it.
- Tf and Kpv are poorly identified. I did not check the frequency-response or droop checks, nor the fault and generator-trip recordings.

```json
{
  "params": {
    "Kqv": 2.58594355,
    "Tq": 0.0741953763,
    "Kqvv": 2.60832176e-16,
    "Dp": 0.0451953413,
    "Tp": 0.0261550335,
    "Kpv": 0.0119737211,
    "Tf": 0.00170656928
  },
  "defs": {
    "w": "(theta-a)/Tf",
    "Pref": "P0-Dp*w-Kpv*(V-V0)",
    "Qref": "Q0+Kqv*(Vset-V0)-Kqvv*(V-V0)"
  },
  "states": {
    "a": {"rhs": "(theta-a)/Tf", "init": "theta0"},
    "xp": {"rhs": "(Pref-xp)/Tp", "init": "P0"},
    "xq": {"rhs": "(Qref-xq)/Tq", "init": "Q0"}
  },
  "outputs": {"P": "xp", "Q": "xq"}
}
```