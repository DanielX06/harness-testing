I've written a terminal model to `submission.json` and checked it with `tools/check_submission.py` on both validation files: it parses, starts at rest, and replays. Active power P matches well. Reactive power Q matches only partly: the Q equations are a fitted equivalent, not the device's identified control structure.

**Open-loop replay on validation (driven by measured V, θ, Vset)**

| File | P error (RMSE) | P if held flat | Q error (RMSE) | Q if held flat |
|---|---|---|---|---|
| `val_load_op1` | 3.3e-4 | 2.35e-2 | 4.4e-3 | 2.76e-2 |
| `val_vref_op2` | 3.0e-4 | 5.9e-3 | 1.6e-3 | 2.95e-2 |

All of this is open-loop replay. I haven't tested the model inside the grid, which is how it will be scored.

**Model: an internal voltage E∠δ behind a fitted impedance Z = R + jX**
- φ = δ − θ, a = E·cos φ − V, b = −E·sin φ
- P = V·(a·R − b·X)/(R² + X²)
- Q = V·(a·X + b·R)/(R² + X²)
- Frequency droop: dδ/dt = ω_b·mp·(P0 − P), with ω_b = 2π·60
- Voltage loop: err = Vset − Vf − mq·(Qf − Q0)
- E = xi + Kpv·err + Kpe·(Pf − P0), with d(xi)/dt = Kiv·err
- Filters: dVf/dt = (V − Vf)/Tv; dQf/dt = (Q − Qf)/Tq; dPf/dt = (P − Pf)/Tpe
- At t = 0 the states start from the operating point (δ0, E0 from V0, P0, Q0 and Z; Qf = Q0, Vf = V0, Pf = P0), so the model starts at rest at any operating point.
- Steady-state droops: dP/dω = −1/mp ≈ −16.9 pu per pu frequency, and dQ/dV = −1/mq ≈ −25.

**How I got there (rejected candidates)**
- **Plain voltage source behind a reactance:** the fit sent X to an unrealistic 487 pu, and Q was poor.
- **Grid-following unit with a PLL** (with P and Q outer loops and current lags): clearly worse on P and Q, including validation.
- **Black-box controller with three internal states:** better on training but no better on validation.
- **What was kept:**
  - A mainly resistive Z made the internal angle continuous across events and fixed P.
  - The only extra term that improved validation was feeding filtered P back into E (`Kpe`). It brought Q error on the voltage-setpoint test from 5.4e-3 down to 1.4e-3.

**How well each parameter is identified**
- **Well identified:**
  - mp ≈ 0.059: the measured ΔP/Δω is −17.1 in every event.
  - mq ≈ 0.040: settled ΔQ/(Vset − V) is about 24 across events.
- **Poorly identified, and they trade off against each other:** R, X, Kpv, Kiv and Kpe. R ranged from 1.1 to 3.5 between fits of similar quality. Treat R ≈ 2.0, X ≈ 0.63 as an equivalent, not physical, impedance; it implies an internal voltage of about 2.7 pu.
- **Moderately identified:** Tq ≈ 2.7 s, Tv ≈ 0.63 s, Tpe ≈ 0.31 s.

**Known weaknesses**
- **Q errors remain** on large, fast voltage moves: the bus-8 load drop, the generator trip and the line opening. Errors there are 0.004–0.006 pu and last several seconds.
- **Q gains seem to depend on the operating point**, which this structure doesn't fully capture.
- **Slow internal mode:** with V, θ and Vset held, the model has a lightly damped oscillation of about 0.05 Hz that decays over about 5 s. Replays were stable, but this is the main closed-loop risk.

```json
{
 "params": {
  "R": 2.031236748594067,
  "X": 0.627859413706732,
  "mp": 0.05899834472659033,
  "Tq": 2.743105842279172,
  "mq": 0.039762272032817625,
  "Kpv": 1.898635672770578,
  "Kiv": 4.24792546013495,
  "Tv": 0.6349139097322442,
  "Kpe": -1.7052298778068586,
  "Tpe": 0.3080783517971074,
  "wb": 376.99111843077515
 },
 "defs": {
  "Z2": "R**2+X**2",
  "err": "Vset-Vf-mq*(Qf-Q0)",
  "Emag": "xi+Kpv*err+Kpe*(Pf-P0)",
  "phi": "delta-theta",
  "ea": "Emag*cos(phi)-V",
  "eb": "-Emag*sin(phi)",
  "Pout": "V*(ea*R-eb*X)/Z2",
  "Qout": "V*(ea*X+eb*R)/Z2"
 },
 "states": {
  "delta": {"rhs": "wb*mp*(P0-Pout)", "init": "theta0+atan2((X*P0-R*Q0)/V0, V0+(R*P0+X*Q0)/V0)"},
  "Qf": {"rhs": "(Qout-Qf)/Tq", "init": "Q0"},
  "xi": {"rhs": "Kiv*err", "init": "sqrt((V0+(R*P0+X*Q0)/V0)**2+((X*P0-R*Q0)/V0)**2)"},
  "Vf": {"rhs": "(V-Vf)/Tv", "init": "V0"},
  "Pf": {"rhs": "(Pout-Pf)/Tpe", "init": "P0"}
 },
 "outputs": {"P": "Pout", "Q": "Qout"}
}
```