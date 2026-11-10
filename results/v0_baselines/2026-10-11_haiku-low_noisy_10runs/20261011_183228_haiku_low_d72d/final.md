The submission is written to `submission.json` and passes the checker, but the reactive-power model is only partly right. On the load-step validation recording its Q replay error (0.022) is barely better than a flat line (0.028), so I'd expect Q to score poorly on disturbance tests.

**Structure (2 states, 7 parameters)**

- **Q:** a first-order lag `xq` driven by the voltage error, `dxq/dt = (Kv·(Vset − V) − xq)/Tq`, with `Q = Q0 + xq + Kqv·(V − V0) + Kqw·ω`.
- **P:** `P = P0 + Kp·ω + Kpv·(V − V0)`, where `ω = (θ − xf)/Tf` and `xf` is a washout state of the angle (`dxf/dt = (θ − xf)/Tf`), so ω is the angle rate.

**Fitted values (train only):** Kv ≈ 1.79 pu/pu, Tq ≈ 5.0 s (at its upper bound), Kqv ≈ 2.36, Kp ≈ −0.045, Kpv ≈ −0.016, Tf ≈ 0.33 s, Kqw ≈ −0.016.

**Identifiability**

- **Well identified:** the Q response to a setpoint step (gain Kv and lag). The P-to-frequency term Kp is moderately constrained by the drifting angle in the load and ambient recordings.
- **Poorly identified:** Tq sits at its bound, so the true lag is probably slower or has more structure. Kqv and Kv trade off against each other, so the steady-state dQ/dV droop (Kqv − Kv ≈ 0.57, the sign is wrong for a droop) is not reliable. Kpv and Kqw are small and near zero, and their values are not meaningful. Tf depends on the angle-drift regime and is not well pinned down.

**Known weaknesses:** the Q residual on the load-step validation file is about 0.011 against 0.001 noise. Likely causes are a missing slower Q dynamic, or a Q dependence on network state that this structure cannot represent. I did not reach a candidate that fixes this. The model also has no secondary-control or nonlinear behaviour, so it has not been tested on faults or trips.

```json
{
  "params": {
    "Kv": 1.78567567,
    "Tq": 5.0,
    "Kqv": 2.36046588,
    "Kp": -0.04527862,
    "Kpv": -0.01610986,
    "Tf": 0.32685359,
    "Kqw": -0.01597554
  },
  "defs": {
    "omega": "(theta-xf)/Tf"
  },
  "states": {
    "xq": {"rhs": "(Kv*(Vset-V)-xq)/Tq", "init": "0.0"},
    "xf": {"rhs": "(theta-xf)/Tf", "init": "theta0"}
  },
  "outputs": {
    "P": "P0+Kp*omega+Kpv*(V-V0)",
    "Q": "Q0+xq+Kqv*(V-V0)+Kqw*omega"
  }
}
```