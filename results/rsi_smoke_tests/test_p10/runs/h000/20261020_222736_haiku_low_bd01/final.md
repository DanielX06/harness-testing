The model is in `submission.json`. It fits P well and Q only partly: it beats the flat baseline on the validation load step and the staged-test replays, but not on the fault recording.

**Structure**

- **Frequency state:** `xth` lags the bus angle with time constant Tf, so `w = (θ − xth)/Tf` estimates the frequency deviation (rad/s).
- **Active power:** `P = P0 − Kp·w + Kvp·(V − V0)`, a frequency droop of about 17 pu per pu frequency (Kp = 0.0451 per rad/s) with a small voltage term.
- **Reactive power:** a first-order state `xq` (time constant Tq) follows `qi = Q0 + Kvs·(Vset − V0) − Kv·(V − V0) + Kw·w`, and Q = xq.
- Both states start at rest and the outputs equal P0 and Q0 at t = 0.

**Fitted values (train only):**

| Parameter | Value | Identification |
|---|---|---|
| Tf | 0.103 s | Well identified; P fit is good |
| Kp | 0.0451 rad/s (≈17 pu) | Well identified; consistent across recordings |
| Kvp | −0.046 | Small; moderately identified |
| Kvs | 2.25 | Identified from the staged voltage-reference steps |
| Kv | 0.12 | Poorly identified; the sign of the static voltage slope flipped between fits |
| Tq | 2.5 s | Poorly identified; the optimiser pushed it toward the upper bound of 5 s in other fits |
| Kw | −0.046 per rad/s | Moderately identified; this term took the validation load-step error from 0.026 to 0.007 |

Kv, Tq and Kw trade off against each other. The static dQ/dV droop (−Kv ≈ −0.12) is weak and uncertain, so the scorer's droop check may score poorly on Q.

**Known weaknesses**

- The fault recording's Q is no better than flat (RMSE 0.026 against 0.026 flat). The line-trip recording also leaves a persistent Q offset of about 0.04 pu that no terminal-voltage term I tried captured.
- The gen-trip Q oscillates in phase with V at grid frequencies, and this model only partly captures it.
- The Q model is the weakest part and is most likely to be wrong in closed loop on large disturbances.

```json
{
  "params": {
    "Tf": 0.10255281823253609,
    "Kp": 0.04511069602179832,
    "Kvp": -0.04571135982831539,
    "Kv": 0.1225834182187718,
    "Kvs": 2.249253828898299,
    "Tq": 2.525395413678713,
    "Kw": -0.04622069938072353
  },
  "defs": {
    "w": "(theta-xth)/Tf",
    "dV": "V-V0",
    "qi": "Q0+Kvs*(Vset-V0)-Kv*dV+Kw*w"
  },
  "states": {
    "xth": {"rhs": "(theta-xth)/Tf", "init": "theta0"},
    "xq": {"rhs": "(qi-xq)/Tq", "init": "Q0"}
  },
  "outputs": {
    "P": "P0-Kp*w+Kvp*dV",
    "Q": "xq"
  }
}
```