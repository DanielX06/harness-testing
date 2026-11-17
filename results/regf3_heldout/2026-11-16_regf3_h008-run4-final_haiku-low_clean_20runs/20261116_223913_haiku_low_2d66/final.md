I saved the submission to `submission.json`. It passes the scorer's checker on both validation recordings: at rest at t = 0 and with no output mismatch. Its validation error is 0.54 on the mean of P and Q (P about 0.07–0.11, Q about 1.0), so the P channel is good and the Q channel is no better than a constant.

**Model**

Three states, with the source voltage behind a reactance XL = 0.3 pu (fixed, not fitted):

- **Source voltage:** `Ei = Ei0 + kpv*(Vset − V)`, where `Ei0 = sqrt((V0 + XL·Q0/V0)² + (XL·P0/V0)²)` is set from the operating point.
- **Angle (frequency droop):** `d(delta)/dt = w0·mp·(P0 − Pm)`, with `delta` starting at `theta0 + atan2(XL·P0/V0, V0 + XL·Q0/V0)`.
- **Active power:** `Pe = V·Ei·sin(delta − theta)/XL`, passed through a first-order filter `Pm` with time constant TPf. P output is `Pm`.
- **Reactive power:** `Qe = V·(Ei·cos(delta − theta) − V)/XL` is computed but not used. Q output is a first-order state `Qo` with target `Q0 + kqv·(V − V0) + kqs·(Vset − V0)` and time constant TQo.

**Parameters**

- **mp = 0.057 (well identified):** the P-f droop, which fits consistently across recordings.
- **TPf = 0.011 s (reasonably identified):** the P filter, which is only just above the 1 ms sample period.
- **kpv = 0.0005 (poorly identified):** the effect of Vset on P through the source voltage is negligible.
- **kqv = −0.0041 and kqs = −0.0003 (poorly identified):** the Q response to V and Vset is tiny, so these are close to zero. The Q channel is essentially a constant with a weak sensitivity.
- **TQo = 0.071 s (poorly identified):** it only sets how fast Q relaxes.
- **XL = 0.3 pu (not identified):** it was fixed, not fitted. Free fits pushed it to degenerate values.

**What the data showed**

- Q barely moves in any recording, including the ±2% Vset steps. In the gentrip recording, V fell about 4% and Q stayed at 0.1706 pu. None of my fitted Q structures beat a constant on the training or validation data.
- P follows the bus angle and the frequency drift. The fitted droop explains the post-event P well.
- Fits with a voltage PI loop and Q-V droop were degenerate: parameters ran to 10¹⁸ or infinity, or XL to 498 pu. I dropped those structures.

**Caveats**

- The Q output will likely score near 1.0 on the scorer's voltage-reference and Q-droop checks, because the data do not show a Q-V response I could identify. The dQ/dV droop is near zero, so it probably does not match the real device's steady-state droop.
- The fault recording was excluded from the fit, so the model has no tested large-disturbance behaviour and no current limit.
- The angle state has no restoring term, so under a sustained disturbance it can drift (the same behaviour the grid itself shows).

```json
{
  "params": {
    "XL": 0.3,
    "mp": 0.0572066047147766,
    "kpv": 0.00047532615499662196,
    "TPf": 0.010807349923662357,
    "kqv": -0.004091747291236711,
    "kqs": -0.0002881313865865846,
    "TQo": 0.07092440180594127,
    "w0": 376.99111843077515
  },
  "defs": {
    "Ei0": "sqrt((V0 + XL*Q0/V0)**2 + (XL*P0/V0)**2)",
    "Ei": "Ei0 + kpv*(Vset - V)",
    "dl": "delta - theta",
    "Pe": "V*Ei*sin(dl)/XL",
    "Qe": "V*(Ei*cos(dl) - V)/XL"
  },
  "states": {
    "delta": {
      "rhs": "w0*mp*(P0 - Pm)",
      "init": "theta0 + atan2(XL*P0/V0, V0 + XL*Q0/V0)"
    },
    "Pm": {
      "rhs": "(Pe - Pm)/TPf",
      "init": "P0"
    },
    "Qo": {
      "rhs": "(Q0 + kqv*(V-V0) + kqs*(Vset-V0) - Qo)/TQo",
      "init": "Q0"
    }
  },
  "outputs": {
    "P": "Pm",
    "Q": "Qo"
  }
}
```