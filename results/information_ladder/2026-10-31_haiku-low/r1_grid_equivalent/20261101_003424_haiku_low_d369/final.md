The submission is at `submission.json`. It passes both checkers on both validation recordings, starts at rest, and stays stable in the grid-equivalent replay.

**Model.** The device is a voltage regulator with integral action plus a frequency droop on the active power. The equations, with V, θ and Vset live:

- Angle filter: `xt' = (θ − xt)/Tw`, `xt(0) = θ0`. The frequency estimate is `ω ≈ (θ − xt)/Tw`.
- Voltage integral: `xi' = Kiq·(Vset − V)`, `xi(0) = 0`.
- Reactive power: `Q = Q0 + Kpq·(Vset − V) + xi + Kqv·(V − V0)`.
- Active power: `P = P0 − Kd·(θ − xt)/Tw + Kpv·(V − V0)`.

Fitted values: Kpq = 1.81, Kiq = 0.626, Kqv = 2.70, Kd = 0.0451 pu per rad/s, Tw = 0.107 s, Kpv = −0.046.

**Fit quality.** Joint RMSE over the eight training recordings is about 0.010 pu. P error is 0.0002–0.002 pu on every training file. On validation, the grid-equivalent replay gives P RMSE about 6–7e-4 (flat baseline 0.006–0.02) and Q RMSE 6–7e-3 (flat baseline 0.03).

**Identifiability.**
- Kd and Tw: the droop gain is reasonably identified as the product Kd·Tw ≈ 0.0048 pu per rad/s. Kd and Tw separately trade off, since the washout is only well-constrained on time scales near Tw.
- Kpq, Kiq and Kqv: poorly identified. Single-file fits gave very different values (Tq ranged from 0.001 to 0.27 s, Kqv from negative to positive). The fitted steady dQ/dV at fixed Vset is Kqv − Kpq ≈ +0.9, which is positive and unusual for a droop. I trust it least; the data (mostly load and voltage-step recordings with weak excitation) do not clearly separate a negative droop from the integral action.
- Kpv: small and weakly identified.
- Model deficiencies: Q residuals remain about 0.025 pu on fault and line-trip recordings, where fast dynamics are not captured by this structure. The model reproduces the voltage-reference steps and frequency drift well.

```json
{
  "params": {
    "Kpq": 1.8117414096919908,
    "Kiq": 0.625721135110405,
    "Kqv": 2.7030415958631058,
    "Kd": 0.045111486533065424,
    "Tw": 0.10722395629935577,
    "Kpv": -0.046257959736457806
  },
  "defs": {
    "dth": "(theta-xt)/Tw",
    "Qerr": "Vset-V"
  },
  "states": {
    "xi": {"rhs": "Kiq*(Vset-V)", "init": "0.0"},
    "xt": {"rhs": "(theta-xt)/Tw", "init": "theta0"}
  },
  "outputs": {
    "P": "P0-Kd*(theta-xt)/Tw+Kpv*(V-V0)",
    "Q": "Q0+Kpq*(Vset-V)+xi+Kqv*(V-V0)"
  }
}
```