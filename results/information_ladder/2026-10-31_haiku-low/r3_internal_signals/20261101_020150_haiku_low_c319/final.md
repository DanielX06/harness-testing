The submission now runs stably on both validation files and beats the flat baseline on every channel. I'm stopping here; it is an empirical linear model, not a physical control model.

**Structure (all states start at rest, P and Q equal P0 and Q0 at t=0):**

1. **Angle washout** (state z, time constant Tw = 0.02 s): z' = (θ−θ0−z)/Tw, and w = (θ−θ0−z)/Tw. This gives the frequency-like signal w, which equals the bus-angle rate in steady state.

2. **Active power** (states x1, x2, a 2-state linear system driven by w, V−V0 and Vset−V0):
   - x' = A_P·x + B_P·[w, V−V0, Vset−V0]
   - P = P0 + C_P·x + D_P·[V−V0, Vset−V0]
   - Steady frequency droop dP/dw ≈ −0.035 pu per rad/s, from the state path only.

3. **Reactive power** (states q1, q2, a 2-state linear system driven by V−V0 and Vset−V0):
   - q' = A_Q·q + B_Q·[V−V0, Vset−V0]
   - Q = Q0 + C_Q·q + D_Q·[V−V0, Vset−V0]

**Fit quality and identifiability:**
- P fits the training recordings to about 5e-4 pu RMS (gentrip, ambient, load, vref). Its frequency response is the least certain part: the washout gain and the split between the state path and the direct path are only loosely identified. A direct derivative feedthrough was unidentifiable and gave a wrong steady droop, so I removed it.
- Q fits ambient and setpoint tests to about 2–5e-3 pu, but only about 1.5e-2 pu on the generator-trip, line and fault recordings. Its dynamics and voltage gains are poorly identified. A lower-order or physically structured voltage loop would likely do better.
- The Q model's sign and gain (dQ/dV) are data-driven, not derived from the documented reactive-droop structure, so the dQ/dV droop check is a risk.
- On the validation files the grid-equivalent replay gives P RMSE about 1.2e-3 and 5e-3, Q about 3.6e-3 and 7.7e-3, against flat baselines of 6e-3 to 3e-2. Fault recordings were not checked.
- The setpoint offset is taken as Vset−V0. This is exact only when the schedule equals the starting voltage, which holds in the recordings I looked at but is an assumption.

**Not done:** an explicit inverter model (PLL, power and voltage loops), a fault check, and any validation of the frequency response or droop checks against the real device.

```json
{
  "params": {
    "Tw": 0.02,
    "pa11": -5.260211, "pa12": -1.162330, "pa21": -1.401350, "pa22": -0.439310,
    "pb11": -0.244810, "pb12": -1.209200, "pb13": 0.545210,
    "pb21": 0.402990, "pb22": -1.326800, "pb23": 0.449770,
    "pc1": 1.280710, "pc2": 0.289760, "pd1": -0.009640, "pd2": 0.183240,
    "qa11": 0.676910, "qa12": -0.450850, "qa21": 1.374330, "qa22": -0.900270,
    "qb11": -0.290120, "qb12": 1.101580, "qb21": 1.102880, "qb22": 0.639230,
    "qc1": 0.512260, "qc2": -0.106810, "qd1": 0.705290, "qd2": 1.119150
  },
  "defs": {
    "u": "theta-theta0-z",
    "w": "u/Tw",
    "dV": "V-V0",
    "dS": "Vset-V0"
  },
  "states": {
    "z":  {"rhs": "(theta-theta0-z)/Tw", "init": "0.0"},
    "x1": {"rhs": "pa11*x1+pa12*x2+pb11*w+pb12*dV+pb13*dS", "init": "0.0"},
    "x2": {"rhs": "pa21*x1+pa22*x2+pb21*w+pb22*dV+pb23*dS", "init": "0.0"},
    "q1": {"rhs": "qa11*q1+qa12*q2+qb11*dV+qb12*dS", "init": "0.0"},
    "q2": {"rhs": "qa21*q1+qa22*q2+qb21*dV+qb22*dS", "init": "0.0"}
  },
  "outputs": {
    "P": "P0+pc1*x1+pc2*x2+pd1*dV+pd2*dS",
    "Q": "Q0+qc1*q1+qc2*q2+qd1*dV+qd2*dS"
  }
}
```