I saved a submission, but the Q side of it is weak and its parameters are not physically credible. Treat it as a provisional fit, not a validated model.

**Submitted model** (`submission.json`, a grid-forming droop form, five states):
- Internal source E behind a coupling reactance XL (Re = 0).
- Angle state `delta` with rate `w0*mp*(P0 - Pm)`: P-f droop on the filtered active power `Pm`.
- Voltage integrator `xv` with rate `kiv*(Vcmd - Vm)`, where `Vcmd = Vset + mq*(Q0 - Qm)`: Q-V droop, with the setpoint entering as a feed-forward through `kff*(Vset - V0)`.
- Filters `Pm`, `Qm`, `Vm` with 10 ms time constants (fixed at the sample-period-scale value, not identified).
- Outputs are the standard lossless-plus-Re source equations for P and Q, using E, the terminal voltage V and the angle difference `delta - theta`.

Fitted values: XL = 4.17, mq = 575, mp = 0.057, kiv = 0.16, kff = 0.012, kpv = 0, Re = 0.

**Fit quality (normalized error, 0 = perfect, 1 = constant output):**
- P is good on most recordings: about 0.05–0.12 on the ambient, load, line and vref recordings, and 0.08 on the gen-trip recording. The fault recording is poor at about 1.0; this is expected from the linear replay in a large event.
- Q is poor: about 0.5–1.2 across recordings. Mean validation error is 0.437.

**Identification:**
- P-f droop (mp ≈ 0.057, so about 17 pu power per pu frequency) is reasonably identified from the data.
- XL and mq are poorly identified. Across fits, XL drifted from 0.5 to 4.2 to 362, and mq from 0.05 to 575. The Q-V sensitivity is near zero in the ambient and setpoint-step data, which is why these parameters run away. The 4.2 value here is not a physical estimate.
- The voltage setpoint steps barely move Q or V in the recordings. The fitted feed-forward and integrator therefore carry little information about the true Q-V gain.
- The true device likely has a Q-V response that the template structure does not capture. I did not get to test alternatives (for example, a VSM-form model or a different Q path), and the fitting tool was slow, so I stopped after three chained fits.

**Risks:** the extreme XL and mq make the Q path nearly decoupled from the grid. Stability checks passed (all eigenvalues negative, including when tied to a 0.3 and 0.6 pu source), and the scorer's check passes on two validation files with zero initial residual. The grid feedback under the scorer's disturbances is untested.

```json
{
  "params": {
    "XL": 4.17085309358604,
    "Re": 0.0,
    "mp": 0.057494379727759615,
    "mq": 575.3014487432266,
    "kpv": 0.0,
    "kiv": 0.16155494154099892,
    "kff": 0.012279069326554837,
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