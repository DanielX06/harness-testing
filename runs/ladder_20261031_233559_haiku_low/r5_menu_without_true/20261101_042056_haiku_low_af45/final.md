I fitted a voltage-controlled model with a PI voltage loop, an active-power droop and a small reactive droop. It runs, starts at rest, and matches the held-out validation files well on P, V and θ. Q is the weakest channel but still well ahead of a flat prediction.

**Structure**

- Internal voltage-control states `xvd` and `xvq` form a PI loop. Their references are `Idref = Kpv*(vr − vd) + xvd` and `Iqref = Kpv*(0 − vq) + xvq`, and the loop is treated as ideal (currents follow references at once).
- The reactive reference is `vr = Vset + n*(Q0 − Qf)`, which is the reactive droop.
- P and Q are the instantaneous dq-frame products of the terminal voltage and the current references, `Pe = vd·Id + vq·Iq` and `Qe = −vd·Iq + vq·Id`.
- Measured P and Q are smoothed through first-order filters `Pf` and `Qf`.
- The internal angle `delta` integrates `w0·m·(P0 − Pf)`, which is the frequency droop. It starts at `theta0`.

**Fitted parameters**

- `m ≈ 0.059`, the frequency droop. This is reasonably identified because the angle drift after events depends on it.
- `n ≈ 0.029`, the reactive droop. It is fairly well identified, though it trades off with `Kpv`.
- `Kpv ≈ 0.68` and `Kiv ≈ 1.18`, the voltage-loop gains. These are moderately identified from the setpoint steps.
- `Tf` went to essentially zero in the fit, so its value is poorly identified. I set it to 1 ms for numerical stability. The validation replay was unchanged at that value.

**Comparison**

- The simpler voltage-behind-reactance structure reached only about 0.36 of the flat error on the fit windows, against 0.05 for the PI loop, so I did not use it.
- Validation grid-equivalent replay RMSE for the chosen model, on `A_val_load_op1`: P 3.2e-4 (flat 2.4e-2), Q 1.3e-3 (flat 2.8e-2), V 7e-4, θ 3.6e-4.
- The open-loop Q error is about 0.015 against a flat 0.028. Q is the least well captured channel, so expect the largest scoring error there.
- I did not run the frequency-response and droop linearization checks myself.

```json
{
  "params": {
    "Tf": 0.001,
    "m": 0.05915286970374186,
    "n": 0.028549194197301102,
    "Kpv": 0.6822623436746248,
    "Kiv": 1.1825923858735894,
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
    "Pf": {"rhs": "(Pe - Pf)/Tf", "init": "P0"},
    "Qf": {"rhs": "(Qe - Qf)/Tf", "init": "Q0"},
    "delta": {"rhs": "w0*m*(P0 - Pf)", "init": "theta0"},
    "xvd": {"rhs": "Kiv*(vr - vd)", "init": "P0/V0"},
    "xvq": {"rhs": "Kiv*(0 - vq)", "init": "-Q0/V0"}
  },
  "outputs": {"P": "Pe", "Q": "Qe"}
}
```