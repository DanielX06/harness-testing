The submission is in place and starts at rest, but one check is weak. I'm reporting that rather than hiding it.

**Model (submission.json)**

The device is modelled as a PI voltage-regulated source with an ideal inner current loop and frequency droop on P.

- Filtered power: `Pf` and `Qf` follow the electrical P and Q, with a time constant `Tf` (fitted to about zero).
- Active power: the internal angle `delta` integrates `w0*m*(P0 - Pf)`, so P rises when the bus angle drifts negative (frequency falls).
- Reactive reference: `vr = Vset + n*(Q0 - Qf)`.
- Voltage loop: `Id = Kpv*(vr - vd) + xvd` and `Iq = Kpv*(0 - vq) + xvq`, with `xvd' = Kiv*(vr - vd)` and `xvq' = Kiv*(0 - vq)`. Here `vd` and `vq` are the terminal voltage in the frame of `delta`.
- Outputs: `P = vd*Id + vq*Iq` and `Q = -vd*Iq + vq*Id`.
- Initial states are set from the operating point, so the model starts at rest.

**Fitted parameters**

| Parameter | Value | Identification |
|---|---|---|
| m (P droop) | 0.0596 | Well identified. It sets the P response to angle drift. |
| Kpv | 0.686 | Reasonably identified. |
| Kiv | 1.17 | Reasonably identified, but it trades off against Kpv. |
| n (Q droop) | 0.0213 | Moderately identified. It was small and its effect is weak. |
| Tf | ~0 | Poorly identified. The fit drove it to the lower limit, so the filter is effectively off. |

**Validation**

- Grid-equivalent replay, validation files: P error is about 4 to 40 times below the flat baseline, and V and theta errors are also small.
- Open-loop replay on `A_val_vref_op2`: P error is about 30 times below flat, but Q error (3.2e-2) is no better than flat (2.95e-2). The Q response to the voltage-setpoint steps is not captured well in that replay.
- Open-loop replay on `A_val_load_op1`: P is about 50 times below flat, and Q is about 0.97 of flat.

The Q path is the weak point. The grid-equivalent replay looked good on Q, but the open-loop Q check does not. Q droop `n` and the voltage-loop gains are the parameters to revisit if you have more time. I did not test the other menu structures, such as the reactive PI loop or the inertia option.

```json
{
  "params": {
    "Tf": 1.7409924720773153e-09,
    "m": 0.059638105702808135,
    "n": 0.021304466032597214,
    "Kpv": 0.6858114604381215,
    "Kiv": 1.1716861691251867,
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