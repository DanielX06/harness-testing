The submission is written to `submission.json` and passes the scorer's checks on both validation recordings: it starts at rest, and open-loop replay gives P RMSE about 5e-4 and Q RMSE about 7e-3, against 0.02–0.03 for a flat line. The Q model is the weak point. Its static voltage gain is poorly identified and probably too weak, and it does not capture the fault transient.

**Model**

- **Frequency proxy:** `w = (θ − xw)/Tw`, with `xw` a state initialised at θ0 and Tw = 0.02 s. This approximates dθ/dt in rad/s.
- **Active power:** `P = P0 − Dp·xp + e·(V − V0) + f·(Vset − V0)`, with `xp' = (w − xp)/Tp`.
  - Dp = 0.045 per rad/s (about 15.5 pu P per pu frequency), Tp = 0.084 s. Both are well identified: the droop is consistent across the ambient, load, line and generator-trip recordings.
  - e = −0.081 and f = +0.078 are small direct terms; they are less certain, since V and Vset are correlated in the staged tests.
- **Reactive power:** a target `u = Q0 + A·(Vset − V0) − B·(V − V0) + Kw·w`, passed through two lags, `y1' = (u − y1)/T1` then `y2' = (y1 − y2)/T2`, with `Q = y2`.
  - A = 2.23, Vset gain. Fitted on all training files.
  - B = 0.105, voltage gain. Poorly identified. It trades off against the fault and generator-trip transients, which pull it towards zero.
  - Kw = −0.046 and T1 = 0.018 s, with T2 = 2.57 s, the slow component that carries most of the response.

**Rejected candidates**

- A PI-style voltage loop with an integrator state fitted the events poorly, and its static slope was ill-defined.
- A Q model fitted only to the staged tests (static Q–V gain of about −1.9) generalized badly to validation (Q RMSE 0.038, worse than flat). The staged steps and the fault clearly disagree about the static voltage gain, and the event data is what generalizes.

**Known limitations**

- Q residuals on the fault and generator-trip recordings remain around 0.02 pu. The device appears to change its reactive response strongly during large dips (possibly current limiting or a voltage-support mode), which this linear form does not represent.
- The steady dQ/dV droop of about −0.1 is probably too weak compared with the staged tests. Expect the scorer's droop check to be off on that point.
- I did not run a closed-loop grid simulation or the frequency-response check, so stability in the scorer's grid is untested.

```json
{
  "params": {
    "A": 2.2324,
    "B": 0.1046,
    "Kw": -0.0463,
    "T1": 0.0184,
    "T2": 2.5652,
    "Dp": 0.04499,
    "Tp": 0.08395,
    "Tw": 0.02,
    "e": -0.08122,
    "f": 0.07839
  },
  "defs": {
    "w": "(theta-xw)/Tw",
    "u": "Q0+A*(Vset-V0)-B*(V-V0)+Kw*w"
  },
  "states": {
    "xw": {"rhs": "(theta-xw)/Tw", "init": "theta0"},
    "y1": {"rhs": "(u-y1)/T1", "init": "Q0"},
    "y2": {"rhs": "(y1-y2)/T2", "init": "Q0"},
    "xp": {"rhs": "(w-xp)/Tp", "init": "0.0"}
  },
  "outputs": {
    "P": "P0-Dp*xp+e*(V-V0)+f*(Vset-V0)",
    "Q": "y2"
  }
}
```