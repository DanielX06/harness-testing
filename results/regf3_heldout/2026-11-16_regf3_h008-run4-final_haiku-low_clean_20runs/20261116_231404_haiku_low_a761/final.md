I saved a submission, but it is a weak model. Its validation error is 0.364 on the scorer's scale (0 = perfect, 1 = constant output), and its parameters are not physically meaningful. I would not trust it to score well on the held-out grid.

**What the data show**
- Q is almost flat in every recording (standard deviation about 0.0005 pu in ambient runs). It barely responds to V, to the voltage setpoint, or to the angle. The ±2% setpoint steps move Q by less than 0.0001 pu and V by about 0.0003 pu.
- P varies with the ambient load changes and with the line and generator events. Those changes are not explained by a simple droop.
- The only large Q movement is in the fault recording, which the tool leaves out of the fit.

**Model (submitted, `submission.json`)**
The structure is the generic droop template with five states: the internal angle `delta`, the voltage-loop integrator `xv`, and filtered P, Q and V (`Pm`, `Qm`, `Vm`). The internal source is `E = xv + kpv*(Vcmd - Vm) + kff*(Vset - V0)`, with `Vcmd = Vset + mq*(Q0 - Qm)`. P and Q come from the coupling equations with `Re = -89.7` and `XL = 0.115`. `delta` integrates `w0*mp*(P0 - Pm)`.

**Parameter identification**
- `Re` (-89.7), `mq` (2.7e5), `TVf` (set to 1000 s, originally infinite) and `kpv` (3e-5) are not physically meaningful. With `TVf` at 1000 s, `Vm` is effectively frozen, so the voltage loop is really a feed-forward on `Vset`. The Q-V droop is effectively switched off. The fit is not identifying a real voltage-regulation mechanism.
- `mp` (0.053) and the filter constants `TPf` and `TQf` (about 0.001 s, at the floor) are the most plausible values. The frequency droop gives the right order of magnitude, but the time constants are not well identified.
- `kiv`, `kff` and `XL` are only weakly identified.
- The linearization is stable (largest eigenvalue -0.001 1/s), but it is very weakly damped and the fitted coupling is not physical, so the scorer's closed-loop behaviour and droop checks may be poor.

**Problems and next steps**
- The fitter did not converge: each run hit the 120 s limit, and the optimizer wandered into unphysical parameter values. A reliable result needs more evaluations, run in chunks and continued from the saved fit.
- Q is the main weakness: its normalized error is 0.53 to 0.79 on the validation recordings. The constant-Q structure is likely wrong. A proper fit probably needs the setpoint to act through a slow path, or a Q limiter or reference state, which I did not test.
- A physically constrained restart with `Re = 0` fit Q much worse (validation error 1.14), so I did not submit it.

```json
{
  "params": {
    "XL": 0.11514177976182362,
    "Re": -89.74168940002505,
    "mp": 0.0530684450121604,
    "mq": 268406.5070013067,
    "kpv": 3.0048225333008686e-05,
    "kiv": 0.009176439223430817,
    "kff": 0.2636825296400571,
    "TPf": 0.0010499999999994182,
    "TQf": 0.0010499999999994182,
    "TVf": 1000.0,
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