I've written a model that passes the submission checker on both validation files. Active power fits well. Reactive power is only partly captured: it misses the fast reactive-power swings that move with the grid's roughly 1 Hz voltage oscillations.

**Open-loop replay on validation** (error in pu; "do-nothing" is the error of a model whose P and Q never move)

| File | P error | P do-nothing | Q error | Q do-nothing |
|---|---|---|---|---|
| val vref_op2 | 0.0004 | 0.0059 | 0.013 | 0.030 |
| val load_op1 | 0.0010 | 0.024 | 0.0033 | 0.028 |

On the training files, the Q error stays around 0.01 for the voltage-reference tests and the line and fault events. That is a large share of how much Q actually moves in those recordings. I haven't run it closed loop in the grid. The small steady-state gain from voltage error to Q and the large reactance suggest it is stable, but that is untested.

**How it behaves.** I first tried treating P as a filtered response to frequency, which fitted P well. It ended up as a voltage-source structure with an internal angle and an internal voltage behind a reactance X. The fitted X went to my search limit of 20 pu, so in practice the device acts like a current source. It does not behave like a stiff voltage source.

**Equations** (ωb = 2π·60; all states start at rest)
- Internal angle: dδ/dt = −ωb·mp·(Pf − P0), with Pf' = (P − Pf)/Tf.
- Voltage loop error: e = Vset − Vm − mq·(Qf − Q0), with Vm' = (V − Vm)/Tv and Qf' = (Q − Qf)/Tq.
- Internal voltage: E = x + Kp·e, with x' = Ki·e.
- Outputs: P = E·V·sin(δ − θ)/X and Q = (E·V·cos(δ − θ) − V²)/X.
- Initial values: δ0 = θ0 + atan2(P0·X/V0, V0 + Q0·X/V0), x0 = |V0 + Q0·X/V0 + j·P0·X/V0|.

**Which parameters are well or poorly identified**
- **Well identified:**
  - mp ≈ 0.058: the frequency droop. dP/dω is about 17 pu, which matches the steady P change after the generator trip.
  - mq ≈ 0.042: the steady voltage droop, dQ/dV ≈ −24 pu.
- **Poorly identified:**
  - X sits on its bound, so it trades off with Kp and Ki. Only the ratios matter: Kp/X ≈ 0.7 is the proportional gain from voltage error to Q, and Ki/X ≈ 1.2 per second is the integral gain.
  - Tf sits on its lower bound of 0.006 s, so it just means "fast".
  - Tq ≈ 4.8 s and Tv ≈ 0.13 s are loosely identified.

**Rejected candidates**
- A first-order lag from voltage error to Q: Q error up to 0.06.
- A voltage-error controller with a measurement filter: the filter time constant ran to its 2 s limit, which isn't physical.
- A stiff voltage source whose internal voltage steps directly with Vset: Q error about 0.047.

```json
{"params": {"X": 19.999999999981522, "mp": 0.05835617531674779, "Tf": 0.006000000000000001, "mq": 0.042423924487683555, "Tq": 4.820202204086395, "Ki": 23.998099170703643, "Kp": 14.006221922838632, "Tv": 0.1315585595186603, "wb": 376.99111843077515}, "defs": {"e": "Vset-vm-mq*(qf-Q0)", "Eint": "x+Kp*e", "g": "dl-theta", "Pe": "Eint*V*sin(g)/X", "Qe": "(Eint*V*cos(g)-V**2)/X"}, "states": {"dl": {"rhs": "-wb*mp*(pf-P0)", "init": "theta0+atan2(P0*X/V0,V0+Q0*X/V0)"}, "pf": {"rhs": "(Pe-pf)/Tf", "init": "P0"}, "qf": {"rhs": "(Qe-qf)/Tq", "init": "Q0"}, "x": {"rhs": "Ki*e", "init": "sqrt((V0+Q0*X/V0)**2+(P0*X/V0)**2)"}, "vm": {"rhs": "(V-vm)/Tv", "init": "V0"}}, "outputs": {"P": "Pe", "Q": "Qe"}}
```