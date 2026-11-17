The submission is saved as `submission.json` and passes the scorer's checker on both validation recordings (starts at rest, output matches at t=0). The model is a reasonable P model but a weak Q model, so treat it as a first pass.

**Model**

- **Active power (P):** a voltage source E at angle δ behind a coupling impedance (Re ≈ 0, XL ≈ 2.63 pu), giving P = V·E·sin(δ−θ)/XL. The angle follows a droop: dδ/dt = ω0·mp·(P0 − Pm), where Pm is P through a 1.5 µs filter. So P rises when frequency falls, and the frequency is the rate of change of δ.
- **Voltage path:** E = xv + kpv·(Vset − Vm), with an integrator dxv/dt = kiv·(Vset − Vm). Vm is V through a 43 ms lag.
- **Reactive power (Q):** Q = Q0 + kqa·(V − V0) + kqb·(Vm − V0), with kqa ≈ 0.65 and kqb ≈ −0.65. Because kqa + kqb ≈ 0, Q has essentially no steady-state dependence on V, and it responds only to fast changes in V. This matches the recordings, where Q stays flat while V moves by 1–2%.

**Fit results (mean validation error 0.47; train 0.53)**

- **P** is captured well: normalized errors 0.04–0.09 on the ambient and load/line/gen-trip recordings, and 0.15–0.16 on the voltage-reference tests and the fault recording (0.50).
- **Q** is poorly captured: 0.76–0.90 on most recordings (1.1 on the fault). The high-pass structure is a fit to a small signal, and I did not find the true Q mechanism.
- **Well identified:** mp ≈ 0.058 (the frequency droop) and the flat steady-state Q behaviour.
- **Poorly identified:** XL (2.6 pu is far from the ~0.5 pu short-circuit equivalent, so it is an effective value that absorbs the other dynamics); kpv and kiv, because the voltage-setpoint steps barely move V, so the Vset path is weakly excited; Re, which is fitted to ~0; and the Q filter constant and gains, which trade off with each other.
- **Stability:** the linearization has its slowest eigenvalue at 0, which is the integrator of the droop angle. It was not flagged unstable, but it is marginal.
- **Not tried:** the generic WECC droop and VSM structures with their limits, and a Q path that includes a voltage loop with a proper reactive-power droop. These are the obvious next steps if Q matters for scoring.

```json
{
  "params": {
    "XL": 2.629294293447625,
    "Re": -1.442357840425967e-05,
    "mp": 0.0577855870323436,
    "kpv": 0.31651929941153945,
    "kiv": 0.014723619336714875,
    "TPf": 1.4522239163617307e-06,
    "TVf": 0.04346987565619874,
    "kqa": 0.649895572863298,
    "kqb": -0.6540243007301085,
    "w0": 376.99111843077515
  },
  "defs": {
    "Ei": "xv + kpv*(Vset - Vm)",
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
      "rhs": "kiv*(Vset - Vm)",
      "init": "sqrt((V0 + (Re*P0 + XL*Q0)/V0)**2 + ((XL*P0 - Re*Q0)/V0)**2) - 0*kpv"
    },
    "Pm": {
      "rhs": "(Pe - Pm)/TPf",
      "init": "P0"
    },
    "Vm": {
      "rhs": "(V - Vm)/TVf",
      "init": "V0"
    }
  },
  "outputs": {
    "P": "Pe",
    "Q": "Q0 + kqa*(V-V0) + kqb*(Vm-V0)"
  }
}
```