I'm stopping here with the current candidate. Its P side is validated; its Q side is good on staged tests but not on the network-event recordings.

**Model (on the 900 MVA rating, bus 3 terminal)**

- **Active power:** a frequency droop. A washout of the bus angle (time constant Tw ≈ 0.11 s) gives a frequency estimate `w = (θ − x_f)/(Tw·2π·60)`, and `P = P0 − Kp·w + Kv·(V − V0)`, with Kp ≈ 16.8 pu/pu (about 6 % droop) and Kv ≈ −0.04.
- **Reactive power:** a direct voltage term plus one lagged state driven by the setpoint and voltage deviations. `Q = Q0 + K·(Vset − V0) + a·(V − V0) + x_q`, with `dx_q/dt = (c·(Vset − V0) + dd·(V − V0) − x_q)/Tq`. Fitted values are K ≈ −0.054, a ≈ 1.78, c ≈ 1.30, dd ≈ −0.20, Tq ≈ 1.58 s.

**Validation (open-loop replay on the provided tool)**

- `val/A_val_vref_op2`: P RMSE 2.2e-3 (flat 6.8e-3), Q RMSE 2.8e-3 (flat 2.8e-2). Good.
- `val/A_val_load_op1`: P RMSE 1.7e-3 (flat 2.4e-2), but Q RMSE 3.1e-2, slightly worse than flat (2.8e-2).

**Identification confidence**

- Kp and Tw are well identified. P residuals are near the 0.001 noise on ambient and most events; the fault recording is about 0.002.
- The Q lag (Tq, c, dd) is moderately identified from the staged steps.
- The steady dQ/dV sign is not trustworthy. The model gives a positive value (about +1.6). The staged tests and ambient data point that way, but the fault and gentrip records show Q rising as V dips, which implies a negative droop. I could not reconcile these. This is the largest risk for the dQ/dV check and for closed-loop stability.
- Attempts to add a frequency term to Q, or a fully general two-state linear model, did not improve fit on held-out data, so I did not keep them.

```json
{
  "params": {"Kp": 16.7811, "Tw": 0.112, "Kv": -0.0396, "K": -0.0542, "a": 1.7822, "c": 1.2973, "dd": -0.1968, "Tq": 1.5787},
  "defs": {"dV": "V-V0", "dS": "Vset-V0", "w": "(theta-xf)/Tw/(2*pi*60)"},
  "states": {
    "xf": {"rhs": "(theta-xf)/Tw", "init": "theta0"},
    "xq": {"rhs": "(c*dS+dd*dV-xq)/Tq", "init": "0.0"}
  },
  "outputs": {"P": "P0-Kp*w+Kv*dV", "Q": "Q0+K*dS+a*dV+xq"}
}
```