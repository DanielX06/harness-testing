The submission is a frequency-droop active-power path with a reactive droop and a PI voltage loop, with ideal current tracking. It is saved as `submission.json` and passes the parse and at-rest check on a validation file.

**Equations** (V, θ are terminal voltage and angle; w0 = 2π·60):
- Internal angle: δ' = w0·m·(P0 − Pf). The bus angle is driven through the droop.
- Filtered outputs: Pf' = (Pe − Pf)/Tf and Qf' = (Qe − Qf)/Tf, with Tf ≈ 0 (fitted to ~1e-10, so the filter is effectively off).
- Terminal dq components use δ: vd = V·cos(δ − θ), vq = −V·sin(δ − θ).
- Reactive droop: vr = Vset + n·(Q0 − Qf).
- PI voltage loop: Id = Kpv·(vr − vd) + xvd, Iq = Kpv·(0 − vq) + xvq, with xvd' = Kiv·(vr − vd) and xvq' = Kiv·(0 − vq). Initial integrator values are P0/V0 and −Q0/V0.
- Outputs: Pe = vd·Id + vq·Iq and Qe = −vd·Iq + vq·Id.

**Parameters:**
- m ≈ 0.0594 (frequency droop). Well identified: it sets the P response to the generator trip and the load events.
- n ≈ 0.0258 (reactive droop). Moderately identified. It trades off against Kpv, so the Q-to-setpoint gain is set jointly by these two.
- Kpv ≈ 0.684 and Kiv ≈ 1.18 (voltage loop). Identified from the staged voltage-reference steps. They are correlated with each other and with n.
- Tf ≈ 0 (the fit drove it to zero). It is not a real identified time constant, and I would not rely on any filter lag.

**Validation:** on the grid-equivalent replay, the held-out files give P RMSE about 1.4e-4 and 3.7e-4 and Q RMSE about 9e-4 and 1.3e-3. Flat-prediction errors are 6e-3 to 2.4e-2 for P and 3e-2 for Q, so the model is much better than flat. In open-loop replay, Q is weaker (RMSE 0.019 against 0.029 flat), so the reactive path is the least certain part.

**Structures tried:** a simpler voltage-behind-reactance structure fitted poorly (about 0.45 of flat error) and drove the reactive droop to zero, so I dropped it. I did not test the power-loop or inner current-loop variants, so the choice of this simpler structure is not tested against them.

```json
{
 "params": {
  "Tf": 1.449507449941474e-10,
  "m": 0.059394907687798,
  "n": 0.02579489126878604,
  "Kpv": 0.6837355578284532,
  "Kiv": 1.179882112947667,
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