I saved a submission, but it is a partial model. P comes from a droop-type model that fits well. Q is held at its operating value because I could not find a Q model that beat that on validation.

**What the model does** (`submission.json`, saved in the working directory)

- **Internal voltage source.** The device is a voltage source E behind a reactance XL = 0.6 pu, with the internal angle δ and the EMF E taken from the operating point (P0, Q0, V0). The init formulas reproduce P0 and Q0 exactly, so the model starts at rest.
- **P–f droop.** dδ/dt = ω0·mp·(P0 − Pm), where Pm is P passed through a first-order filter with TPf = 0.041 s. The output is P = V·E·sin(δ − θ)/XL.
- **Voltage loop.** E is held constant (kiv = 0), so the setpoint has no effect.
- **Q.** Output Q = Q0 (constant).

**Evidence**

- **Setpoint.** The staged voltage-reference steps (±1 to 2%) move Q by under 1e-4 pu and P by under 1e-3. Either the voltage loop is effectively absent or it is far slower than the recordings. I therefore left the setpoint out.
- **P.** The droop fit gives mp ≈ 0.058. That is consistent with the ambient regression of P on dθ/dt (about −0.04 per rad/s), which is an independent check. On the validation files the open-loop P error is 8e-5 and 1.3e-3 pu RMS, against P standard deviations of 8e-4 and 9.7e-3.
- **Q.** The droop-E model's Q error was worse than holding Q constant on both validation files (7.4e-3 versus 1.35e-3 pu RMS on the load recording). Linear regressions of Q on V, P and the setpoint gave inconsistent coefficients across recordings. So I chose the constant.

**Parameter identification**

- **mp and TPf:** reasonably identified from the P response to frequency during the trip, load and line events.
- **XL:** poorly identified. The fit pushed it to its upper bound of 0.6, and it mainly trades off against the Q sensitivity, which the data does not support.
- **kiv:** the fit drove it to zero. The data show no voltage-loop action, so the voltage-droop check (dQ/dV) will likely differ from the real device.
- **mq:** not identifiable, because it multiplies a term that is switched off.

**Known weaknesses**

- Q does not respond to V, so the model has no reactive support in the grid. The fault recording shows a real Q swing of about 0.37 pu, which this model misses entirely.
- The model has not been run closed-loop in the grid, so its stability there is untested.
- The P droop is fitted only to small-signal and moderate events. The fault's current-limiting behaviour is not modelled.

```json
{
 "params": {
  "XL": 0.6,
  "mp": 0.0576581162,
  "TPf": 0.0413565651,
  "kiv": 0.0,
  "w0": 376.99111843
 },
 "defs": {
  "P_e": "V*xv*sin(dl-theta)/XL"
 },
 "states": {
  "Pm": {
   "rhs": "(P_e-Pm)/TPf",
   "init": "P0"
  },
  "dl": {
   "rhs": "w0*mp*(P0-Pm)",
   "init": "theta0+atan2(P0*XL,Q0*XL+V0**2)"
  },
  "xv": {
   "rhs": "kiv*(Vset-V)",
   "init": "sqrt((P0*XL)**2+(Q0*XL+V0**2)**2)/V0"
  }
 },
 "outputs": {
  "P": "P_e",
  "Q": "Q0"
 }
}
```