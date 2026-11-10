The model passes the scorer's checks on both validation recordings and runs at rest from t = 0. I'm submitting this linear candidate; I didn't have budget to test a nonlinear Q alternative.

**Model:** The device is a linear, two-part model around the operating point, with P and Q as deviations from P0 and Q0.

- **Q (voltage control):** A second-order lag (ωq, ζq) driven by `Kv·ΔVset − Kq·ΔV`, plus direct feedthrough `−Kd·ΔV + Kvd·ΔVset`.
- **P (frequency support):** A second-order lag (ωp, ζp) driven by `−Kw·ω − Kpv·ΔV`, plus direct feedthrough `−Kpd·ΔV`. Here ω is the bus-angle rate divided by 2π·60, estimated with a fast washout state (τ = 10 ms).
- **Rest at t = 0:** All states start at zero, so P = P0 and Q = Q0 at the first sample.

**Fit quality:**
- Staged voltage-reference tests fit well (Q RMSE about 0.004–0.008 pu on train).
- Ambient and load-change recordings fit P and Q to within about 0.003 pu.
- Fault and generator-trip recordings still leave Q residuals of about 0.023–0.028 pu. Q is not hard-clipped in the data, so the miss is likely nonlinearity in V at large deviations, which this linear model does not capture.
- Validation (open-loop replay): P RMSE 3.8e-4 and 9.0e-4, against 2.4e-2 and 5.9e-3 for a flat model. Q RMSE 8.7e-3 and 4.7e-3, against 2.8e-2 and 3.0e-2 for a flat model.

**Parameter identification:**
- Well identified: the P-side parameters (ωp ≈ 45 rad/s, Kw, Kpv), and the direct feedthrough terms that carry the fast Q jump at a setpoint step.
- Poorly identified: Kv and Kq both hit their bounds (20), and ωq sits at its lower bound (0.2 rad/s). These trade off against each other, so the Q lag and the steady-state voltage droop (about −20 pu/pu in the fit) are not well separated. Treat the Q low-frequency behaviour, and the dQ/dV droop it implies, with caution.
- Kpd is small and has the opposite sign to Kpv, which may also be a fitting artefact.

```json
{
  "params": {
    "Kv": 18.608,
    "Kq": 20.0,
    "Kd": -0.6057,
    "Kvd": 1.9834,
    "wq": 0.2,
    "zq": 1.6936,
    "Kw": 16.9903,
    "Kpv": 0.2532,
    "Kpd": -0.1742,
    "wp": 45.1081,
    "zp": 3.0,
    "Om": 376.99111843077515,
    "taud": 0.01
  },
  "defs": {
    "dV": "V-V0",
    "dVs": "Vset-V0",
    "uq": "Kv*dVs-Kq*dV",
    "omega": "(theta-theta0-xth)/(taud*Om)",
    "up": "-Kw*omega-Kpv*dV",
    "Qd": "q1-Kd*dV+Kvd*dVs",
    "Pd": "p1-Kpd*dV"
  },
  "states": {
    "xth": {"rhs": "(theta-theta0-xth)/taud", "init": "0"},
    "q1": {"rhs": "q2", "init": "0"},
    "q2": {"rhs": "wq**2*(uq-q1)-2*zq*wq*q2", "init": "0"},
    "p1": {"rhs": "p2", "init": "0"},
    "p2": {"rhs": "wp**2*(up-p1)-2*zp*wp*p2", "init": "0"}
  },
  "outputs": {"P": "P0+Pd", "Q": "Q0+Qd"}
}
```