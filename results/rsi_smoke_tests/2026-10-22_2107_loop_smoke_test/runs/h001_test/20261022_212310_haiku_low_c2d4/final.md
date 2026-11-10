I'm submitting this candidate. It runs and starts at rest, but its Q fit is weak on the voltage-reference validation recording, so treat the Q side as uncertain.

**Model (two-lag Q, angle-derivative P droop):**

- **Frequency estimate:** a washout on the bus angle gives ω = (θ − xw)/(Tw·2π·60), with xw′ = (θ − xw)/Tw.
- **P:** xp′ = (P0 + Kpv·(V − V0) − Kp·ω − xp)/Tp, and P = xp. Kp is the active-power droop gain on frequency.
- **Q:** two parallel first-order lags on the voltage error e = Vset − V:
  - x1′ = (K1·e − x1)/T1
  - x2′ = (K2·e − x2)/T2
  - Q = Q0 + x1 + x2

All states start at rest (xp = P0, xw = θ0, x1 = x2 = 0), so the model starts at equilibrium at any operating point.

**Fitted values (train/ only, decimated to 10 ms):**

- Kp ≈ 17.0 pu P per pu ω, Tp ≈ 0.11 s.
- Kpv ≈ −0.08, which is weakly identified.
- K1 ≈ −16.7, T1 ≈ 5.2 s; K2 ≈ 38.7, T2 ≈ 11.5 s. These two Q paths trade off strongly; only their sum matters for the steady-state gain, and the individual values are poorly identified.
- Tw sits at its 0.02 s lower bound, so the angle washout is effectively a pure derivative. This is poorly identified and may not be physical.

**Validation (check_submission.py, open-loop replay):**

- val/A_val_vref_op2: P RMSE 9.5e-4 (flat baseline 5.9e-3); Q RMSE 0.024 (flat 0.030). Q is barely better than flat.
- val/A_val_load_op1: P RMSE 4.2e-4 (flat 2.4e-2); Q RMSE 5.0e-3 (flat 2.8e-2). This one is good.

**Known weaknesses:**

- The Q residual after each setpoint step is systematic, around −0.045 during the first step, so the true Q dynamics are not captured well by two linear lags.
- The steady-state dQ/dV droop is set by the cancellation between K1 and K2, so it is unreliable.
- Tw at its bound and the large, opposing K1 and K2 may cause trouble in closed loop. I did not run a closed-loop grid simulation, so the stability of this model is unchecked.

```json
{
  "params": {
    "Kp": 16.9944,
    "Kpv": -0.0790,
    "Tp": 0.1103,
    "K1": -16.6961,
    "T1": 5.228,
    "K2": 38.7069,
    "T2": 11.545,
    "Tw": 0.02
  },
  "defs": {
    "om": "(theta-xw)/(Tw*2*pi*60)"
  },
  "states": {
    "xp": {"rhs": "(P0+Kpv*(V-V0)-Kp*om-xp)/Tp", "init": "P0"},
    "x1": {"rhs": "(K1*(Vset-V)-x1)/T1", "init": "0.0"},
    "x2": {"rhs": "(K2*(Vset-V)-x2)/T2", "init": "0.0"},
    "xw": {"rhs": "(theta-xw)/Tw", "init": "theta0"}
  },
  "outputs": {
    "P": "xp",
    "Q": "Q0+x1+x2"
  }
}
```