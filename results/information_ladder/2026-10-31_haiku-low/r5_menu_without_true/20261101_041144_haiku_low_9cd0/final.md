I've written the submission as a grid-follower with a frequency droop on the angle, a reactive droop, and an ideal-current PI voltage loop. It passes the parser and the at-rest check on both validation files. Its open-loop Q error on the load-change validation file (≈0.018 pu RMSE) is only modestly better than a flat prediction (0.028), so the reactive path is the weakest part of the model.

**Equations** (V, θ are live terminal values; w0 = 2π·60 rad/s):

- Filtered active and reactive power: `Pf' = (Pe − Pf)/Tf`, `Qf' = (Qe − Qf)/Tf`, with Tf ≈ 0.
- Frequency droop on the internal angle: `δ' = w0·m·(P0 − Pf)`, starting at θ0.
- Reactive droop: `vr = Vset + n·(Q0 − Qf)`.
- Terminal voltage in the internal frame: `vd = V·cos(δ−θ)`, `vq = −V·sin(δ−θ)`.
- PI voltage loop, with ideal current tracking: `Id = Kpv·(vr − vd) + xvd`, `Iq = Kpv·(0 − vq) + xvq`, where `xvd' = Kiv·(vr − vd)` and `xvq' = Kiv·(0 − vq)`.
- Outputs: `P = vd·Id + vq·Iq`, `Q = −vd·Iq + vq·Id`.

**Parameters**
- **m ≈ 0.0594** (frequency droop): well identified; it sets the slow P response to frequency events.
- **Kpv ≈ 0.684, Kiv ≈ 1.18** (voltage loop): identified from the staged voltage steps and fit together; they trade off against each other somewhat.
- **n ≈ 0.026** (reactive droop): moderately identified; the earlier fit pushed it toward zero, so it is the least certain value.
- **Tf ≈ 0**: the fit drove it to the lower limit, so the filter is effectively switched off. The model has no real measurement-filter dynamics.
- **w0** is fixed at 2π·60.

**Validation:** the grid-equivalent replay gives P RMSE 3.6e-4 and 1.4e-4 on the two validation files, and Q RMSE 1.4e-3 and 9e-4. Only the first validation file (load change) was checked open-loop for Q, which is where the 0.018 error appears.

```json
{
 "params": {
  "Tf": 5.008179225991212e-13,
  "m": 0.059370959694070295,
  "n": 0.025979882606435543,
  "Kpv": 0.6835294695178564,
  "Kiv": 1.1819368500314065,
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
 "outputs": {
  "P": "Pe",
  "Q": "Qe"
 }
}
```