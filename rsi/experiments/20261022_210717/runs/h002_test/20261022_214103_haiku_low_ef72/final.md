The constrained fit is worse on validation (Q RMS 0.0068 and 0.0124, against 0.0058 and 0.0054 for the unconstrained model), so I'm keeping the unconstrained model. It passes the checker on both validation files.

## Model

The device is modelled as two parts.

**Active power: droop with lag.** Frequency deviation is estimated from a washout of the bus angle. Let `w = (θ − θ0 − zθ)/Tw`, where `zθ` lags θ − θ0 with time constant Tw. Then `P = P0 + xp`, with `xp' = (−xp − Kp·w)/Tp`. Fitted values are Kp ≈ 0.0451 pu·s/rad (about 17 pu P per pu ω), Tp ≈ 0.012 s and Tw ≈ 0.003 s. The P residuals on validation are about 0.0006–0.0009 pu, so P is well captured. Tw and Tp are fast and only partly identified.

**Reactive power: a second-order filter on voltage and setpoint.** Q = Q0 + Σ over inputs {Vset−V0, V−V0, P−P0} of second-order filtered terms with shared denominator s² + a1·s + a2. Each input has its own numerator. Fitted a1 ≈ 1.78, a2 ≈ 1.18, and the DC gains are about +10 for the setpoint and −9 for voltage. The Q residuals on validation are about 0.0054–0.0058 pu, against 0.03 for a flat model. This is a black-box fit with no physical interpretation.

## Identifiability and risks

- **Q numerators** are poorly identified individually. Ambient V and Q move together through the grid, so only the staged setpoint steps and the disturbances separate the device's own response from the grid's. The setpoint steps give the cleanest signal.
- **The V feedthrough** has a positive high-frequency term (n2 ≈ 1.38). This is the biggest concern for the closed-loop check. It may make the grid less stable or distort the frequency response, and I did not verify closed-loop behaviour. Constraining it to zero made validation worse, so I kept it.
- **The droops** (dP/dω ≈ Kp, dQ/dV from the DC gain) are only roughly fixed. The integral-type Q behaviour I first tried did not fit as well as the filter form.
- The setpoint is used as Vset − V0 and V − V0, so every state is at rest at t = 0 for any operating point.

```json
{
  "params": {
    "a1": 1.7779,
    "a2": 1.1811,
    "Kp": 0.0451460131,
    "Tp": 0.0122588703,
    "Tw": 0.00319,
    "n2S": 1.7649,
    "n1S": 10.6224,
    "n0S": 12.3243,
    "n2V": 1.381,
    "n1V": -1.4696,
    "n0V": -10.881,
    "n2P": -2.4402,
    "n1P": -10.5447,
    "n0P": 1.0602
  },
  "defs": {
    "Qdev": "n2S*(Vset-V0)+(n1S-n2S*a1)*q2S+(n0S-n2S*a2)*q1S + n2V*(V-V0)+(n1V-n2V*a1)*q2V+(n0V-n2V*a2)*q1V + n2P*xp+(n1P-n2P*a1)*q2P+(n0P-n2P*a2)*q1P"
  },
  "states": {
    "zth": {"rhs": "(theta-theta0-zth)/Tw", "init": "0.0"},
    "xp": {"rhs": "(-xp-Kp*(theta-theta0-zth)/Tw)/Tp", "init": "0.0"},
    "q1S": {"rhs": "q2S", "init": "0.0"},
    "q2S": {"rhs": "-a1*q2S-a2*q1S+(Vset-V0)", "init": "0.0"},
    "q1V": {"rhs": "q2V", "init": "0.0"},
    "q2V": {"rhs": "-a1*q2V-a2*q1V+(V-V0)", "init": "0.0"},
    "q1P": {"rhs": "q2P", "init": "0.0"},
    "q2P": {"rhs": "-a1*q2P-a2*q1P+xp", "init": "0.0"}
  },
  "outputs": {
    "P": "P0+xp",
    "Q": "Q0+Qdev"
  }
}
```