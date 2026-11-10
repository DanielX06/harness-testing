I fitted a five-state linear model. It replays both validation recordings well open loop, but I did not test it closed loop in a grid. Open-loop replay RMSE is below.

| Validation recording | P RMSE (pu) | Q RMSE (pu) | Flat-model P (pu) | Flat-model Q (pu) |
|---|---|---|---|---|
| `A_val_vref_op2` | 8.8e-4 | 4.1e-3 | 5.9e-3 | 3.0e-2 |
| `A_val_load_op1` | 4.3e-4 | 7.6e-3 | 2.4e-2 | 2.8e-2 |

The "flat" columns are the error of a model whose P and Q never move. The model starts at rest in both recordings.

**Equations** (ω is the angle rate, estimated as the difference between θ and a lagged copy of θ):
- **P branch:**
  - ω_p = (θ − tf)/Twp, with d(tf)/dt = ω_p.
  - Tp·d(xp)/dt = −kp·ω_p + kpv·(V − V0) − xp.
  - P = P0 + xp.
- **Q branch:**
  - ω_q = (θ − tg)/Twq, with d(tg)/dt = ω_q.
  - T1·d(x1)/dt = a·(V − V0) − x1.
  - T2·d(x2)/dt = b·(Vset − V0) − x2.
  - Q = Q0 + x1 + x2 + c·(V − V0) + kd·ω_q.

**Parameter identification**
- **P:** the frequency droop kp ≈ 0.045 and the lag Tp ≈ 0.1 s are well identified. The P fit is good on every training recording (RMS ≤ 2.4e-3 pu).
- **Voltage term in P:** kpv is small and poorly identified.
- **Twp:** this is pinned at its lower bound (0.02 s), so it is effectively a numerical derivative filter.
- **Q:** the Q fit is only moderate. The Q residual was 0.0004–0.035 pu RMS across the training recordings in the earlier fit, and the final Q fit has the same shape.
- **Q parameters that trade off:** a, c, T1 and b, T2 trade off against each other. Together they give a net steady-state dQ/dV of about +0.07 and a Vset gain of about 2.
- **Twq and kd:** Twq sits at its upper bound (2 s), and kd is small.
- **Instant V-to-Q term:** c ≈ 1 is a positive instantaneous feedback from V to Q. It is the term most likely to matter for grid stability, which I did not test.

```json
{"params": {"kp": 0.04508, "Tp": 0.09547, "Twp": 0.02, "kpv": -0.07, "a": -0.932, "T1": 0.47, "b": 2.025, "T2": 0.984, "c": 1.001, "Twq": 2.0, "kd": -0.045}, "defs": {"omp": "(theta-tf)/Twp", "omq": "(theta-tg)/Twq"}, "states": {"tf": {"rhs": "omp", "init": "theta0"}, "tg": {"rhs": "omq", "init": "theta0"}, "xp": {"rhs": "(-kp*omp+kpv*(V-V0)-xp)/Tp", "init": "0"}, "x1": {"rhs": "(a*(V-V0)-x1)/T1", "init": "0"}, "x2": {"rhs": "(b*(Vset-V0)-x2)/T2", "init": "0"}}, "outputs": {"P": "P0+xp", "Q": "Q0+x1+x2+c*(V-V0)+kd*omq"}}
```