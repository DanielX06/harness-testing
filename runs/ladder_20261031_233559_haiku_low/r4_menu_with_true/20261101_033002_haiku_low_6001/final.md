The submitted model is a frequency-droop, reactive-droop and PI voltage-loop structure. It starts at rest and matches the recorded P and Q with errors well below the flat-prediction baseline on both validation files. Its outputs are the active and reactive power in pu on the 900 MVA rating.

**Equations** (with `vd = V cos(δ−θ)`, `vq = −V sin(δ−θ)`):
- Reactive droop: `vr = Vset + n·(Q0 − Qf)`
- Voltage PI loop (ideal inner current loop): `Id = Kpv·(vr − vd) + xvd`, `Iq = Kpv·(0 − vq) + xvq`, with `d(xvd)/dt = Kiv·(vr − vd)` and `d(xvq)/dt = Kiv·(0 − vq)`
- Output: `P = vd·Id + vq·Iq`, `Q = −vd·Iq + vq·Id`
- Power filter: `Pf` and `Qf` are first-order lags of P and Q with time constant `Tf`
- Frequency droop: `d(δ)/dt = w0·m·(P0 − Pf)`, with δ starting at θ0

The states start at the operating point (`xvd = P0/V0`, `xvq = −Q0/V0`, `δ = θ0`), so the model is at rest at t = 0.

**Identification:**
- `Kpv`, `Kiv`, `n` and `Tf` were fitted together. `Kpv` and `Kiv` are moderately identified, and `Kpv` trades off with `n`.
- `m` (frequency droop, about 0.059) is the best identified and is consistent across fits.
- `n` (about 0.054) and `Tf` (about 0.013 s) are plausible but less certain, since they were fitted on a short window.
- The simpler candidate (direct reactive droop with a voltage source behind reactance) drove `n` to zero and `Tf` to a near-singular value, and fitted worse. I dropped it.
- I did not fit the PI current-loop or inertia structures, so the device's true internal structure may differ in detail.

```json
{
  "params": {
    "Tf": 0.013237394033149457,
    "m": 0.05877627715592543,
    "n": 0.053931333251984896,
    "Kpv": 0.6890106164075404,
    "Kiv": 1.1298138920575562,
    "w0": 376.99111843077515
  },
  "defs": {
    "vd": "V*cos(delta - theta)",
    "vq": "-V*sin(delta - theta)",
    "vr": "Vset + n*(Q0 - Qf)",
    "Idref": "Kpv*(vr - vd) + xvd",
    "Iqref": "Kpv*(0 - vq) + xvq",
    "Id": "Idref",
    "Iq": "Iqref",
    "Pe": "vd*Id + vq*Iq",
    "Qe": "-vd*Iq + vq*Id"
  },
  "states": {
    "Pf": {
      "rhs": "(Pe - Pf)/Tf",
      "init": "P0"
    },
    "Qf": {
      "rhs": "(Qe - Qf)/Tf",
      "init": "Q0"
    },
    "delta": {
      "rhs": "w0*m*(P0 - Pf)",
      "init": "theta0"
    },
    "xvd": {
      "rhs": "Kiv*(vr - vd)",
      "init": "P0/V0"
    },
    "xvq": {
      "rhs": "Kiv*(0 - vq)",
      "init": "-Q0/V0"
    }
  },
  "outputs": {
    "P": "Pe",
    "Q": "Qe"
  }
}
```