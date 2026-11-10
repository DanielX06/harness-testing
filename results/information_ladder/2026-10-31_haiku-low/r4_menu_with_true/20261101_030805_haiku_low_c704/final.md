I'm submitting a menu-structure model: a frequency-droop active path, a reactive-droop voltage loop with a PI current loop. It fits well in the grid-equivalent replay but fails the open-loop check, so treat it as a risky candidate.

**Structure (all in pu on the 900 MVA rating, w0 = 2π·60):**
- **Active power:** `Pf` is P filtered with time constant Tf (about 2 µs, effectively unfiltered). The internal angle `delta` drifts as `d(delta)/dt = w0·m·(P0 − Pf)`, with droop m ≈ 0.059. Starts at theta0.
- **Reactive droop:** the voltage reference is `vr = Vset + n·(Q0 − Qf)`, with n ≈ 0.041.
- **Voltage loop:** PI in the internal frame. `Id_ref = Kpv·(vr − vd) + xvd` and `Iq_ref = Kpv·(0 − vq) + xvq`, with Kpv ≈ 0.70 and Kiv ≈ 1.09.
- **Current loop:** PI driving a converter voltage (ud, uq) through lag Te ≈ 0.016 s and filter reactance xf (rf = 0). Kpi ≈ 3.38, Kii ≈ 70.6.
- **Outputs:** P = vd·Id + vq·Iq and Q = −vd·Iq + vq·Id.
- The model starts at rest; `check_submission.py` confirms init residuals ≈ 0 and matching outputs at t = 0.

**Fit quality:** on the grid-equivalent replay of the held-out validation files, RMSE is about 2e-4 in P, 3e-4 in Q, 1.5e-4 in V and 1.3e-4 in theta. Flat-prediction errors are about 0.003–0.03 for P and Q. The model is therefore close on both validation recordings.

**Identifiability:**
- **Well identified:** the droop m (≈0.059) and the voltage-loop gains Kpv and Kiv. Their values barely moved across fits.
- **Poorly identified:** xf and Kpi trade against each other. xf moved from the start value 0.15 to 1.15 even when I tried to fix it, and Kii and Te also shift between fits. The current-loop parameters should not be read as physical values.
- **Q droop n:** about 0.04, but its estimate depends on the voltage-reference tests. It was not checked separately.

**Known risk:** when I replay the validation recordings open loop (measured V and theta driving the model), the output diverges after about 2 s. I did not resolve this. The grid-equivalent closed-loop replay is stable and accurate, and the scorer uses closed-loop simulation. But the divergence suggests the current loop is poorly damped, so the model may not hold up to larger disturbances or to the linearization check.

```json
{
  "params": {
    "Tf": 1.7661203751805159e-06,
    "m": 0.05875734237063252,
    "n": 0.04063942474832929,
    "Kpv": 0.6961260521919679,
    "Kiv": 1.09466624855241,
    "Kpi": 3.3791308413372705,
    "Kii": 70.61852559588718,
    "Te": 0.015801180569629536,
    "xf": 1.150055922190779,
    "rf": 0.0,
    "w0": 376.99111843077515
  },
  "defs": {
    "vd": "V*cos(delta - theta)",
    "vq": "-V*sin(delta - theta)",
    "vr": "Vset + n*(Q0 - Qf)",
    "Idref": "Kpv*(vr - vd) + xvd",
    "Iqref": "Kpv*(0 - vq) + xvq",
    "det": "rf**2 + xf**2",
    "Id": "(rf*(ud - vd) + xf*(uq - vq))/det",
    "Iq": "(-xf*(ud - vd) + rf*(uq - vq))/det",
    "udref": "Kpi*(Idref - Id) + xid + vd + rf*Id - xf*Iq",
    "uqref": "Kpi*(Iqref - Iq) + xiq + vq + rf*Iq + xf*Id",
    "Pe": "vd*Id + vq*Iq",
    "Qe": "-vd*Iq + vq*Id"
  },
  "states": {
    "Pf": {"rhs": "(Pe - Pf)/Tf", "init": "P0"},
    "Qf": {"rhs": "(Qe - Qf)/Tf", "init": "Q0"},
    "delta": {"rhs": "w0*m*(P0 - Pf)", "init": "theta0"},
    "xvd": {"rhs": "Kiv*(vr - vd)", "init": "P0/V0"},
    "xvq": {"rhs": "Kiv*(0 - vq)", "init": "-Q0/V0"},
    "xid": {"rhs": "Kii*(Idref - Id)", "init": "0"},
    "xiq": {"rhs": "Kii*(Iqref - Iq)", "init": "0"},
    "ud": {"rhs": "(udref - ud)/Te", "init": "V0 + rf*P0/V0 + xf*Q0/V0"},
    "uq": {"rhs": "(uqref - uq)/Te", "init": "-rf*Q0/V0 + xf*P0/V0"}
  },
  "outputs": {
    "P": "Pe",
    "Q": "Qe"
  }
}
```