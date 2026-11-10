I have a model that passes the format check and starts at rest on both validation files. The active-power part fits the data well; the reactive-power part only fits partly. When replayed open loop on the two validation files, the error compared with a model whose P and Q never move is:

| Validation file | P error (model / flat) | Q error (model / flat) |
|---|---|---|
| val vref op2 | 4.1e-4 / 5.9e-3 | 1.35e-2 / 2.95e-2 |
| val load op1 | 1.1e-3 / 2.35e-2 | 3.9e-3 / 2.76e-2 |

**Equations**

The model is an internal voltage Ei at angle δ behind a reactance X = 20 pu. Because X is so large, the unit behaves almost like a controlled current source rather than a voltage source.

- P = Ei·V·sin(δ−θ)/X
- Q = (Ei·V·cos(δ−θ) − V²)/X
- Active-power droop:
  - dδ/dt = −377·mp·(Pf − P0)
  - dPf/dt = (P − Pf)/Tf
  - In steady state, ΔP ≈ −Δω/mp, about 17 pu P per pu frequency (a droop of about 5.8%).
- Voltage control is proportional-integral with a small reactive droop:
  - Ei = x + kpv·(Vset − Vf)
  - dx/dt = Ki·(Vset − Vf − mq·(Qf − Q0))
  - dVf/dt = (V − Vf)/Tv
  - dQf/dt = (Q − Qf)/Tq
- Initial values: δ, Ei and x come from P0, Q0 and V0; Pf = P0, Qf = Q0, Vf = V0.

**How well each parameter is identified**

- **Well identified:**
  - mp ≈ 0.058 is consistent across the frequency events; this is the strongest result.
  - Tf is very fast and sits on its lower bound. It is not resolvable from the data, but it doesn't matter.
- **Poorly identified:**
  - X sits at its upper bound (20). It trades off directly with kpv and Ki: what matters is roughly kpv/X ≈ 0.7 as the proportional gain and Ki/X ≈ 1.2/s as the integral gain.
  - Tq is also on its bound (2 s).
  - mq (0.039) is loosely set. The data show the terminal voltage returning close to Vset after events, which is more consistent with near-integral control than with a large droop.

**Limitations**

- **The Q model is not settled.** After natural events (generator trip, line trip, fault), Q moves in ways that local voltage error does not explain. In the generator trip, for example, Q kept rising while the voltage was above Vset.
- **Rejected candidates:** a pure Q–V droop; plain proportional-integral control with and without a lag; adding a frequency or P term to Q; and a stiff grid-forming source with small X, because Q did not jump when V dropped at the trip. None reproduced those Q events.
- **Open-loop replay is unreliable for Q.** Because the voltage control integrates, small voltage errors accumulate in replay, so Q fits on the training files varied widely between fits.
- **Not checked closed loop.** I could not test the model inside the grid, so I can't confirm it stays stable there. Its gains are moderate, which is the main reason to expect it does.

```json
{"params": {"mp": 0.05808298663326633, "Tf": 0.006000000000000001, "X": 19.999999999999996, "Ki": 24.135234460349267, "mq": 0.038538672092611005, "Tq": 1.9999999999999998, "kpv": 14.36790098761371, "Tv": 0.15337987024166944}, "defs": {"Ei": "x + kpv*(Vset - Vf)", "a": "dl - theta", "Pe": "Ei*V*sin(a)/X", "Qe": "(Ei*V*cos(a) - V**2)/X"}, "states": {"dl": {"rhs": "-376.99111843077515*mp*(Pf - P0)", "init": "theta0 + atan2(P0*X/V0, V0 + Q0*X/V0)"}, "Pf": {"rhs": "(Pe - Pf)/Tf", "init": "P0"}, "Qf": {"rhs": "(Qe - Qf)/Tq", "init": "Q0"}, "x": {"rhs": "Ki*(Vset - Vf - mq*(Qf - Q0))", "init": "sqrt((V0 + Q0*X/V0)**2 + (P0*X/V0)**2)"}, "Vf": {"rhs": "(V - Vf)/Tv", "init": "V0"}}, "outputs": {"P": "Pe", "Q": "Qe"}}
```