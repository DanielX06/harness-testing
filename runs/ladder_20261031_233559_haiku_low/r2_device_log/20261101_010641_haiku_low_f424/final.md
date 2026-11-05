I'm submitting the first bounded fit (`submission.json`), since it has the lower closed-loop error on the load test.

## Model

The model is three equations, with P and Q as outputs and V, θ and Vset as inputs.

**Active power and frequency droop.** The device's internal angle δ integrates an internal frequency command ω, which is a droop on its own P:

- ω = −Kp·(P − P0), with Kp ≈ 22.08 rad/s per pu
- dδ/dt = ω
- P = P0 + a·(V − V0) + b·(δ − (θ − θ0)), with a ≈ 0.019 and b ≈ 0.088

**Reactive power and voltage control.** A first-order lag x tracks the setpoint error:

- dx/dt = (kq·(Vset − V0) − x) / Tq, with kq ≈ 2.01 and Tq ≈ 2.07 s
- Q = Q0 + x + kp·(P − P0) − kd·(V − V0), with kp ≈ 1.33 and kd = 0

At t = 0, x = 0, δ = 0 and P = P0, Q = Q0, so the model starts at rest.

## Identification

- **Kp (well identified):** the logged internal frequency tracks −22.1·(P − P0) with a small residual. The P fit to the training recordings is at about 0.001 pu.
- **a and b (moderately identified):** the P fit is good, but a and b trade off against the internal angle offset.
- **kq and Tq (identified from the setpoint steps):** the staged reference tests show a fast Q jump on each setpoint step, followed by a settling tail.
- **kp and kd (poorly identified):** the fit pins the voltage droop kd at its zero bound. Open-loop regressions on the ambient and event data give a positive V coefficient, which is destabilizing in closed loop; that was rejected, so the model has no V-droop. The unexplained Q residual is about 0.003–0.005 in the ambient and load recordings, so the model probably misses some slow Q–V coupling.

## Checks (grid-equivalent replay, X = 0.5 pu)

| Validation file | P RMSE (flat) | Q RMSE (flat) | V RMSE (flat) | θ RMSE (flat) |
|---|---|---|---|---|
| A_val_vref_op2 | 1.1e-3 (5.9e-3) | 5.7e-3 (2.9e-2) | 2.6e-3 (9.5e-3) | 8e-4 (1.7) |
| A_val_load_op1 | 2.1e-3 (2.4e-2) | 1.1e-2 (2.8e-2) | 6.1e-3 (4.8e-3) | 3e-3 (7.4) |

The load test's V error is worse than a flat (constant) prediction, so the closed-loop voltage response to load changes is not right yet. I did not run the frequency-response or droop checks, so I have not confirmed the 0.1–10 Hz response or dQ/dV.

```json
{
  "params": {"Kp": 22.083, "a": 0.0191, "b": 0.0884, "kq": 2.0065, "kd": 0.0, "Tq": 2.0726, "kp": 1.3256},
  "defs": {
    "Pe": "P0 + a*(V-V0) + b*(de - (theta-theta0))",
    "w": "-Kp*(Pe-P0)",
    "Qe": "Q0 + x - kd*(V-V0) + kp*(Pe-P0)"
  },
  "states": {
    "de": {"rhs": "w", "init": "0.0"},
    "x": {"rhs": "(kq*(Vset-V0)-x)/Tq", "init": "0.0"}
  },
  "outputs": {"P": "Pe", "Q": "Qe"}
}
```