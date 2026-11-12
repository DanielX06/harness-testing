The submission is saved as `submission.json`. It passes the scorer's rest-at-start check on both validation files. The Q channel is only partly explained, and the reactive-power droop check is the most likely weak point.

**Equations**

- **Active power:** `P = P0 + Kpv·(V − V0) − Kw·wf`
  - `wf = (θ − z)/(Tw·2π·60)` is the frequency deviation, obtained from a state `z` that low-passes the angle with time constant `Tw`. This avoids needing a derivative.
- **Reactive power:** `Q = q`, a lagged state with `dq/dt = (Q0 + Kvs·(Vset − V0) + x − q)/Tq`.
  - `x` is an integral of the voltage error: `dx/dt = Ki·(Vset − V)`.
- **Initial state:** `x = 0`, `q = Q0`, `z = θ0`, so the model starts at rest with P = P0 and Q = Q0.

**Parameters**

| Parameter | Value | Identification |
|---|---|---|
| Kw | 19.70 (about 5% droop on 900 MVA) | Well identified from the ambient, load and trip recordings. |
| Tw | 0.079 s | Well identified. |
| Kpv | −0.076 | Weak; near zero, so it may be spurious. |
| Kvs | 2.49 | Trades off against Ki. |
| Ki | 0.468 | Reasonably identified from the staged steps. |
| Tq | 0.178 s | Reasonably identified from the staged steps. |

**Validation**

- **P:** open-loop replay RMSE about 1e-3, against about 6e-3 to 2.6e-2 for a flat-line baseline.
- **Q:** RMSE about 0.011, against about 0.027 for a flat-line baseline.
- **Q residuals:** largest in the fault and generator-trip recordings (about 0.03 RMSE on train), so the model misses some fast post-event behaviour.

**Known weaknesses**

- The Q law has zero steady-state dQ/dV, because the integral action drives V toward Vset. The device documents reactive-power droop, so the dQ/dV check will likely score poorly. I did not test a model with an explicit proportional droop term against the validation data.
- I fitted only this one structure and did not run a closed-loop stability check in the grid.

```json
{
  "params": {
    "Kvs": 2.49262737,
    "Ki": 0.46776647,
    "Tq": 0.17808935,
    "Kpv": -0.07596044,
    "Kw": 19.70145488,
    "Tw": 0.07914869
  },
  "defs": {
    "wf": "(theta-z)/(Tw*2*pi*60)",
    "Qt": "Q0+Kvs*(Vset-V0)+x"
  },
  "states": {
    "x": {
      "rhs": "Ki*(Vset-V)",
      "init": "0.0"
    },
    "q": {
      "rhs": "(Qt-q)/Tq",
      "init": "Q0"
    },
    "z": {
      "rhs": "(theta-z)/Tw",
      "init": "theta0"
    }
  },
  "outputs": {
    "P": "P0+Kpv*(V-V0)-Kw*wf",
    "Q": "q"
  }
}
```