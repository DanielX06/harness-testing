The model is written to `submission.json`. It passes the rest-start check, and on both validation recordings it cuts the error to roughly a fifth to a tenth of a flat (do-nothing) model.

**Structure (four states):**
- **Reactive power:** `xq' = (Q0 + Kq·(Vset − vf) − xq)/Tq`, output `Q = xq`. This is a voltage droop with a lag, acting on a filtered voltage.
- **Voltage filter:** `vf' = (V − vf)/Tv`. This lag on the measured voltage was needed. Without it, the Q error on the generator-trip recording was about 0.16 pu; with it, about 0.03.
- **Active power:** `xp' = (P0 − Kp·ω)/Tp`, output `P = xp`, where `ω = (θ − z)/Tw` and `z' = (θ − z)/Tw`. So ω is a fast washout-filtered estimate of dθ/dt, and this is the frequency droop.
- Initial states are P0, Q0, θ0 and V0, so the model starts at rest.

**Fitted values:**
| Parameter | Value | Identification |
|---|---|---|
| Kq | 24.7 pu Q per pu V | Well identified from the ±2% setpoint steps. |
| Tq | 13.8 s | Moderately identified. It was 3.5 s before the voltage filter was added, so it trades off against Tv. |
| Tv | 1.73 s | Moderately identified. It is a lumped lag that may stand in for the real measurement or control dynamics. |
| Kp | 0.0447 pu P per rad/s | Well identified. This is about 17 pu P per pu frequency, roughly a 6% droop. |
| Tp | 0.016 s | Poorly identified. It is short and only mildly constrained by the data. |
| Tw | 0.006 s | Poorly identified. It sets how sharply θ is differentiated, and the fit is insensitive to it. |

**Validation:** The grid-equivalent replay gives P RMSE 5.7e-4 and 7.7e-4, and Q RMSE 5.3e-3 and 6.9e-3, against flat-model errors of 5.9e-3 to 2.4e-2. I did not run the frequency-response or droop checks, and the operating-point dependence was checked only through the per-recording fits, not on the op3 or op2 validation sets.

**Caveats:** The Q dynamics are the least certain part. The fitted Tq and Tv are a lumped approximation, not a verified control structure. Fault recordings were not used for fitting, so the response to a close fault is untested.

```json
{
  "params": {"Kq": 24.7188, "Tq": 13.7958, "Kp": 0.0447, "Tp": 0.016, "Tw": 0.006, "Tv": 1.73203},
  "defs": {"om": "(theta-z)/Tw"},
  "states": {
    "xq": {"rhs": "(Q0+Kq*(Vset-vf)-xq)/Tq", "init": "Q0"},
    "xp": {"rhs": "(P0-Kp*om-xp)/Tp", "init": "P0"},
    "z": {"rhs": "(theta-z)/Tw", "init": "theta0"},
    "vf": {"rhs": "(V-vf)/Tv", "init": "V0"}
  },
  "outputs": {"P": "xp", "Q": "xq"}
}
```