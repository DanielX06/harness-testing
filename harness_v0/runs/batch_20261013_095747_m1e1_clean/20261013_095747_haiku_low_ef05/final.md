The submitted model is a three-state terminal model. It runs at rest, and open-loop replay on both validation recordings beats a flat baseline, but it does not capture the device fully.

**Equations** (V, θ, Vset are live; w is the angle rate, a washout of θ with Tw = 0.01 s):

- **Frequency state:** `xw' = (θ − xw)/Tw`, `w = (θ − xw)/Tw` (≈ dθ/dt, rad/s).
- **Active power:** `xp' = (P0 − Kp·w + Kv·(V − V0) − xp)/Tp`, output `P = xp`.
  - Kp ≈ 0.050 pu P per rad/s, which is the droop (about 17 pu per pu frequency).
  - Kv ≈ −0.021 pu per pu V.
  - Tp ≈ 0.020 s.
- **Reactive power:** `xq' = (Q0 + a·(Vset − V0) + b·(V − V0) + c·(xp − P0) + e·w − xq)/Tq`, output `Q = xq`.
  - a ≈ 1.09 (setpoint gain), b ≈ 0.97 (dQ/dV, the voltage droop), c ≈ 1.43 (coupling to P), e ≈ 0.022 (frequency term).
  - Tq = 0.01 s.

**Identification quality**
- **P droop (Kp), Kv, Tp:** well identified. P residuals are about 0.0006–0.0008 RMS on train and validation, across Tw choices. Tw itself is not identifiable; it only sets how well w is estimated.
- **Q setpoint gain (a) and voltage gain (b):** reasonably determined from the staged tests, but the staged-test fits disagree on b (about 0.97 here versus about 1.75 when the frequency term is dropped). Treat dQ/dV as uncertain, roughly 1–2.
- **Q coupling to P (c) and frequency term (e):** poorly identified and they trade off. The fit with e ≈ 0 gives c ≈ 0.4; with e included, c ≈ 1.4 and e ≈ 0.02. The validation load-change event favours the latter, but the frequency-term sign is not consistent across recordings.
- **Fault response:** not modelled. The fault recording shows large nonlinear Q excursions (current-limit-like behaviour) that this linear model cannot follow. The scorer's disturbances may exercise this.
- **Dynamics:** the Q time constant (≈0.01 s) and the Q overshoot after setpoint steps are only partly captured. The residual Q error after a setpoint step is about 0.007 RMS.

**Checks run:** `check_submission.py` passes on both validation files. Open-loop replay RMSE is P 8e-4 and 2.7e-3, Q 6.6e-3 and 9.8e-3, against flat baselines of 6e-3 to 2.8e-2. I did not run a closed-loop grid simulation, so stability in the scorer's network is unverified.

```json
{
  "params": {"Kp": 0.0501, "Kv": -0.0211, "Tp": 0.0197, "Tw": 0.01, "a": 1.0908, "b": 0.9651, "c": 1.4251, "e": 0.022, "Tq": 0.01},
  "defs": {
    "w": "(theta - xw)/Tw",
    "u": "P0 - Kp*w + Kv*(V - V0)",
    "tq": "Q0 + a*(Vset - V0) + b*(V - V0) + c*(xp - P0) + e*w"
  },
  "states": {
    "xw": {"rhs": "(theta - xw)/Tw", "init": "theta0"},
    "xp": {"rhs": "(u - xp)/Tp", "init": "P0"},
    "xq": {"rhs": "(tq - xq)/Tq", "init": "Q0"}
  },
  "outputs": {"P": "xp", "Q": "xq"}
}
```