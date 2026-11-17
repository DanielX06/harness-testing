I saved a submission, but it is a weak model. Its mean validation error is 0.51 on the scorer's scale, and the reactive-power channel is barely better than a constant output. The submission passes the scorer's checks: it starts at rest and is stable.

**Submitted model (droop-type, `submission.json`)**

- Internal voltage behind a reactance: P = V·E·sin(δ−θ)/XL and Q = (E·V·cos(δ−θ) − V²)/XL, with Re = 0.
- Angle state δ: dδ/dt = w0·mp·(P0 − Pm), so P droops against frequency through a filtered power Pm (time constant TPf).
- Voltage: an integrator xv with dxv/dt = kiv·(Vcmd − Vm), Vcmd = Vset + mq·(Q0 − Qm), and E = xv + kpv·(Vcmd − Vm) + kff·(Vset − V0). Vm and Qm are filtered measurements.
- Fitted values: XL = 4.27, mq = 679, kpv = 0, kiv = 0.57, kff = 0.060, mp = 0.052, TPf = 0.097 s, with TQf and TVf at their 1 ms floor.

**Identification status**

- **Active power (P):** the droop gain mp and filter TPf are the best-determined parameters. P errors are 0.12–0.30 on validation.
- **Reactive power (Q):** poorly identified. The fit drove mq to about 680, which removes the Q-V path. Q responds only weakly to V and to setpoint steps, so the data barely constrain this channel. Q errors are about 0.9 on every recording.
- **XL:** the fitted 4.27 pu is not physical. It effectively makes the Q and voltage path negligible, so I would not trust XL as a reactance estimate.
- **Voltage loop (kpv, kiv, kff):** not separately identified. kff and kiv are small and their meaning is uncertain.

**What I tried and rejected**

- A fit from a physical XL = 0.5 pu went degenerate (Q error above 2, mean val 1.20), so I discarded it.
- A third start (XL = 0.5, mq = 0.05, kpv = 0.3) produced no result before the background process exited, so it is untested.
- The VSM template is not in this tool version, so I did not fit a VSM structure.

The main gap is Q, and a better Q model would need a physically sensible XL and voltage-loop structure, which this session did not reach.

```json
{
  "params": {
    "XL": 4.269063417260875,
    "Re": 0.0,
    "mp": 0.051766729559749605,
    "mq": 679.0376540757234,
    "kpv": 0.0,
    "kiv": 0.5680667325877105,
    "kff": 0.06027167610869206,
    "TPf": 0.09657855450774372,
    "TQf": 0.0009999999999994462,
    "TVf": 0.0009999999999994458,
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