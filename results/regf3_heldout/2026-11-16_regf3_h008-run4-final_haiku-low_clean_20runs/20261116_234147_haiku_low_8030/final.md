The fA model passes the at-rest check and is stable against 0.3 and 0.6 pu grid reactances. I'm submitting it, though its parameters are not physically plausible, as explained below.

Saved to `submission.json`. This is a weak result on Q, and the Q part is not a credible model of the device.

**What the data showed**
- **Active power:** P follows bus-angle drift at about −15 pu per pu frequency, which is a P–f droop with mp ≈ 0.053–0.059. The P error on validation recordings is about 0.05–0.13 of the measured deviation. This is the part I'd trust.
- **Reactive power:** Q is almost constant. It hardly responds to voltage, even through the 7% dip in the generator-trip recording, or to the ±2% setpoint steps. Its variation is small and mostly tracks frequency and P. A constant-Q output would score 1.0 by the scorer's scale.

**What I submitted**
- Internal voltage E = xv + kpv·(Vcmd − Vm) + kff·(Vset − V0), with Vcmd = Vset + mq·(Q0 − Qm).
- The angle state δ follows dδ/dt = w0·mp·(P0 − Pm). Filters on P, Q and V.
- Fitted values: mp = 0.0535, XL = 130, mq = 25748, kpv = 29.4, kiv = 36.3, kff = −28.7, TPf = 0.001 (at the floor), TQf = 276.7, TVf = 0.001 (at the floor).
- Mean validation error is 0.349. Q errors are 0.49 and 0.78 on the two validation recordings.

**Caveats**
- The XL = 130 and mq ≈ 25,000 values are degenerate. They make Q nearly insensitive to V and turn the internal source into a ~23 pu quantity. Those numbers are not physical, so the Q dynamics and the dQ/dV droop reported by the scorer may be wrong.
- Parameter identification: mp is well identified from the frequency-driven P. TPf and TVf sit at their floor, so they are not identified. XL, mq and kpv/kiv are poorly identified, because Q barely moved in the data.
- Pinning XL at 0.2 pu and refitting gave Q errors around 1.2, so I did not use that version.
- I did not fit the large-disturbance recording (the fault), so the model's behaviour in severe faults is unvalidated.

```json
{
  "params": {
    "XL": 130.03758946937558,
    "Re": 0.0,
    "mp": 0.05349005614208635,
    "mq": 25748.09798155861,
    "kpv": 29.43505235856261,
    "kiv": 36.31245340605851,
    "kff": -28.67616684991572,
    "TPf": 0.0009999999999994458,
    "TQf": 276.68920128119663,
    "TVf": 0.001000000000932353,
    "w0": 376.99111843077515
  },
  "defs": {
    "Vcmd": "Vset + mq*(Q0 - Qm)",
    "Ei": "xv + kpv*(Vcmd - Vm) + kff*(Vset - V0)",
    "dl": "delta - theta",
    "Pe": "V*(Re*(Ei*cos(dl) - V) + XL*Ei*sin(dl))/(Re**2 + XL**2)",
    "Qe": "V*(XL*(Ei*cos(dl) - V) - Re*Ei*sin(dl))/(Re**2 + XL**2)"
  },
  "states": {
    "delta": {
      "rhs": "w0*mp*(P0 - Pm)",
      "init": "theta0 + atan2((XL*P0 - Re*Q0)/V0, V0 + (Re*P0 + XL*Q0)/V0)"
    },
    "xv": {
      "rhs": "kiv*(Vcmd - Vm)",
      "init": "sqrt((V0 + (Re*P0 + XL*Q0)/V0)**2 + ((XL*P0 - Re*Q0)/V0)**2)"
    },
    "Pm": {
      "rhs": "(Pe - Pm)/TPf",
      "init": "P0"
    },
    "Qm": {
      "rhs": "(Qe - Qm)/TQf",
      "init": "Q0"
    },
    "Vm": {
      "rhs": "(V - Vm)/TVf",
      "init": "V0"
    }
  },
  "outputs": {
    "P": "Pe",
    "Q": "Qe"
  }
}
```