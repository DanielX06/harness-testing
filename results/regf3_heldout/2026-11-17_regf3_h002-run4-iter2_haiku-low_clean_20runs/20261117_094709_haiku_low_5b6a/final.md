I saved a submission that passes the checker on both validation files, but its Q channel is essentially a constant. Its P channel is good, and the Q channel is not identified in any useful sense.

**Model (submission.json):** a grid-forming droop with an internal angle state and a coupling reactance.

- Angle state: `d(delta)/dt = w0·mp·(P0 − Pm)`, with `Pm` a 10 ms filtered P.
- Internal voltage: `E = xv + kpv·(Vcmd − Vm)`, with `Vcmd = Vset + mq·(Q0 − Qm)` and `d(xv)/dt = kiv·(Vcmd − Vm)`. `Vm` and `Qm` are 10 ms filtered V and Q.
- Output: `P = V·XL·E·sin(delta − theta)/XL²` and `Q = V·(XL·E·cos(delta − theta) − V)/XL²`, with Re = 0.

**Fitted values:**
- `mp` ≈ 0.059. This is the P-f droop, and it is well identified. A direct regression on the recordings gives dP ≈ −0.048·dθ/dt, which corresponds to mp ≈ 0.055.
- `XL` ≈ 3.8 and `mq` ≈ 3300, `kpv` ≈ 0.11, `kiv` ≈ 1×10⁵. These are poorly identified and not physical: they are chosen to make the Q channel nearly flat, not because they describe the device. The device's voltage loop has almost no visible effect on Q.

**What the data show:**
- P responds to the frequency (the rate of change of the terminal angle), and the droop model reproduces it. Per-recording P errors are about 0.03 to 0.12, except the fault recording (about 1.2), where the linear replay is least accurate.
- Q is nearly constant. Its variation in the ambient and vref recordings is mostly driven by network load changes. A 2 % setpoint step moves V by only about 0.0002 pu and Q by about 0.0002 pu. Q errors sit at about 1.0 (no better than a constant), and the gentrip and load recordings are slightly worse at about 1.2 to 1.3.
- Parameters for the voltage path are not trustworthy. The scorer's dQ/dV droop check will probably not match the real device.

**Other notes:**
- The model is stable at all three coupling strengths the tool checks (its own eigenvalues are about −50 s⁻¹ or faster).
- I dropped a fitted voltage feed-forward and a fixed-E variant because they gave large Q errors.
- Mean validation error is about 0.56, dominated by the Q channel. Improving Q would need a better explanation of the device's voltage control, which I did not find.

```json
{
  "params": {
    "XL": 3.8132973721254055,
    "Re": 0.0,
    "mp": 0.058575649805053545,
    "mq": 3266.5785909211104,
    "kpv": 0.11368386276638788,
    "kiv": 104164.35739105131,
    "kff": 0.0,
    "TPf": 0.01,
    "TQf": 0.01,
    "TVf": 0.01,
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