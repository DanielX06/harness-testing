I saved a submission that passes the checker on both validation files. The active-power part fits reasonably well, but the reactive-power part does not: Q is no better than a constant on every recording.

**Model (in `submission.json`)**
- **Active power:** P = K·V·sin(δ − θ), with K ≈ 1.70 pu. This is a source behind a reactance with K = E/X lumped together.
- **Frequency droop:** dδ/dt = ω0·mp·(P0 − Pm), with mp ≈ 0.057 pu. Pm is the measured P, filtered with TPf ≈ 0.011 s.
- **Reactive power:** Q = Q0 + kq·(Vm − V0) + kqP·(Pm − P0), with kq ≈ 0.0047 and kqP ≈ 0.0044. Vm is V filtered with TVf at its 1 ms floor.
- The model starts at rest at any operating point (checker: zero residual and zero output mismatch at t = 0).

**Results**
- Mean val error is 0.531. P errors are 0.04–0.08 on the ambient, load, line and vref validation/train recordings, and Q errors are about 1.0 (no better than a constant).
- Stability check: the model is stable on its own and when tied to a 0.3 or 0.6 pu reactance source.

**Identification**
- **Well identified:** P-f droop gain (mp ≈ 0.057) and the P-angle relation, which fits the load and gen-trip recordings well.
- **Poorly identified:** K and the filter constants are poorly determined, since only the ratio E/X entered the fit, and TVf sits at its floor, so it is not identified.
- **Not identified:** the Q behaviour. The device's Q barely moves (about 1e-3 pu) and I found no linear dependence on V, θ, setpoint or P that explains it. The setpoint steps move V by only about 0.001 pu and leave Q essentially unchanged, so the voltage-reference loop is weak or very slow in these data. The fitted Q terms are therefore small and not reliable.
- **Dropped:** the Q-V droop and the voltage-reference path (the earlier fits gave erratic gains, e.g. mq ≈ 98, and were no better). The Q model is effectively a near-constant output with small corrections.

Expect the Q score to be poor on held-out recordings. The next step would be to find what drives the small Q variation (possibly the voltage-loop dynamics that the setpoint steps did not excite).

```json
{
  "params": {
    "K": 1.7002468436289884,
    "mp": 0.056682310085619365,
    "kq": 0.004726687144866717,
    "kqP": 0.004428808791387263,
    "TPf": 0.01120562578906481,
    "TVf": 0.0009999999999994458,
    "w0": 376.99111843077515
  },
  "defs": {
    "dl": "delta - theta",
    "Pe": "K*V*sin(dl)"
  },
  "states": {
    "delta": {
      "rhs": "w0*mp*(P0 - Pm)",
      "init": "theta0 + atan(P0/(K*V0)/sqrt(1-(P0/(K*V0))**2))"
    },
    "Pm": {
      "rhs": "(Pe - Pm)/TPf",
      "init": "P0"
    },
    "Vm": {
      "rhs": "(V - Vm)/TVf",
      "init": "V0"
    }
  },
  "outputs": {
    "P": "Pe",
    "Q": "Q0 + kq*(Vm - V0) + kqP*(Pm - P0)"
  }
}
```