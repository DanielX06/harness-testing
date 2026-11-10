I've fitted a working terminal model: a grid-forming droop source behind an impedance, with 3 states. It passes the checker on both validation files and replays them well. Its main weakness is that its reactive-power structure is probably not the device's true one, so it may not carry over cleanly to a new operating point (details below).

**Equations** (pu on 900 MVA; ωb = 2π·60)
- **Initial internal voltage:** E0∠δ0 = V0∠θ0 + (R + jX)·I0, where I0 = conj((P0 + jQ0)/(V0∠θ0)). Define g = R/(R²+X²) and b = X/(R²+X²).
- **Internal angle (active-power droop):** dδ/dt = ωb·mp·(P0 − P), with δ(0) = δ0.
- **Filtered Q:** dQf/dt = (Q − Qf)/Tq, with Qf(0) = Q0.
- **Voltage integrator with Q droop:** dxi/dt = Ki·[(Vset − V) − mq·(Qf − Q0)], with xi(0) = 0.
- **Internal voltage magnitude:** E = E0 + kvs·(Vset − V0) + kv·(V − V0) − md·(Qf − Q0) + xi − kp·(P − P0).
  - Because P depends on E, this is solved in closed form, so there is no algebraic loop.
  - With φ = θ − δ: a = V(g·cos φ − b·sin φ) and P = a·E − g·V², which gives E = (Eo + kp·P0 + kp·g·V²)/(1 + kp·a). Here Eo is E without the kp term.
- **Outputs:**
  - P = V·E·(g·cos φ − b·sin φ) − g·V²
  - Q = V·E·(g·sin φ + b·cos φ) − b·V²

The model starts at rest at any operating point (checker: residual about 1e-14).

**Fit quality** (open-loop replay RMSE, with the "never moves" model in brackets)

| Validation file | P error | Q error |
|---|---|---|
| vref_op2 | 2.7e-4 (flat 5.9e-3) | 2.7e-3 (flat 3.0e-2) |
| load_op1 | 4.6e-4 (flat 2.4e-2) | 3.6e-3 (flat 2.8e-2) |

- On training data P errors are 0.6–5e-4 and Q errors 0.8–6.5e-3.
- The fault recording, which I did not fit on, has a Q error of about 0.010.

**Which parameters are well and poorly identified**
- **Well identified:**
  - mp ≈ 0.058, so dP/dω ≈ −17 pu/pu. I also got 0.0588 independently by integrating measured P, and the gen-trip steady state agrees.
  - mq ≈ 0.042, so steady dQ/dV ≈ −24. Steady states across all recordings agree.
  - The P path as a whole.
- **Moderately identified:** R and X. The effective source looks mostly resistive, about 1.4–1.6 pu on fast time scales. R, X, kp and kv trade off against each other.
- **Poorly identified:** md, Tq, kvs and Ki trade off.
  - md comes out negative, which is a weak, slow positive Q feedback. Its loop gain is small (about 0.02), but treat it as a fitting artefact, not real physics.
  - Dropping md doubled the training error.

**Risks and rejected candidates**
- **Q structure is likely wrong in detail.** In the data, the Q response to a voltage-setpoint step doesn't depend on Q0. In this model the Q-voltage gain grows with Q0, so the structure is only an approximation.
- **Stability depends on the operating point:**
  - Held V/θ (model alone): stable for Q0 > 0, unstable for Q0 ≤ 0.
  - Connected to a simple test grid: stable at Q0 = −0.1 and every positive Q0 I tried, and unstable at Q0 = −0.2.
  - All training points had Q0 between 0.17 and 0.27. If the held-out point has the device absorbing reactive power, closed-loop runs could go unstable.
- **Rejected** (all fitted Q badly, with errors up to or above the flat model):
  - grid-following models with a PLL and current loops, with and without a shunt conductance;
  - linear models of Q from V, Vset and θ, pooled across files;
  - a source behind a reactance with no voltage feedback.

```json
{
 "params": {
  "R": 1.4189640581967753,
  "X": 0.33062397731775417,
  "mp": 0.05797317502175563,
  "md": -0.09574463701450805,
  "Tq": 1.5960903475044,
  "kvs": 1.5744671356677484,
  "kv": 0.13739381852692217,
  "kp": 0.9120324737863913,
  "Ki": 2.603654733415897,
  "mq": 0.04232376972419419,
  "wb": 376.99111843077515
 },
 "defs": {
  "zz": "R**2+X**2",
  "g": "R/zz",
  "bb": "X/zz",
  "Ire0": "(P0*cos(theta0)+Q0*sin(theta0))/V0",
  "Iim0": "(P0*sin(theta0)-Q0*cos(theta0))/V0",
  "E0re": "V0*cos(theta0)+R*Ire0-X*Iim0",
  "E0im": "V0*sin(theta0)+R*Iim0+X*Ire0",
  "E0": "sqrt(E0re**2+E0im**2)",
  "Eo": "E0+kvs*(Vset-V0)+kv*(V-V0)-md*(Qf-Q0)+xi",
  "ang": "theta-dl",
  "ca": "cos(ang)",
  "sa": "sin(ang)",
  "aP": "V*(g*ca-bb*sa)",
  "bP": "-V**2*g",
  "Eint": "(Eo+kp*P0-kp*bP)/(1+kp*aP)",
  "Pe": "aP*Eint+bP",
  "Qe": "V*Eint*(g*sa+bb*ca)-V**2*bb"
 },
 "states": {
  "dl": {
   "rhs": "wb*mp*(P0-Pe)",
   "init": "atan2(V0*sin(theta0)+R*(P0*sin(theta0)-Q0*cos(theta0))/V0+X*(P0*cos(theta0)+Q0*sin(theta0))/V0, V0*cos(theta0)+R*(P0*cos(theta0)+Q0*sin(theta0))/V0-X*(P0*sin(theta0)-Q0*cos(theta0))/V0)"
  },
  "Qf": {
   "rhs": "(Qe-Qf)/Tq",
   "init": "Q0"
  },
  "xi": {
   "rhs": "Ki*((Vset-V)-mq*(Qf-Q0))",
   "init": "0"
  }
 },
 "outputs": {
  "P": "Pe",
  "Q": "Qe"
 }
}
```