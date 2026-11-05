The submission is in `submission.json`. It passes the scorer-style checks on both validation recordings and on the two held-out training recordings, but I dropped the documented current loop to get there, so it is a modified version of the menu structure.

**What the model does** (the menu's P and Q paths, with the current loop replaced by an ideal current):

- **Power path:** the device's P follows its dispatch through a power-loop lag. The frequency droop is an internal angle, `delta' = w0·m·(Kpp·(Ps − Pf) + xp − Pf)`, where `Ps` is a lagged copy of `Pf` and `xp` is an integral of `Kip·(Ps − Pf)`.
- **Reactive path:** Q follows a reactive-droop reference `vr = Vset + n·(Kpq·(Qs − Qf) + xq − Qf)`, with `Qs` a lagged copy of `Qf` and `xq` an integral of `Kiq·(Qs − Qf)`.
- **Voltage path:** `Idref = Kpv·(vr − vd) + xvd` and `Iqref = Kpv·(0 − vq) + xvq`, with `xvd` and `xvq` integrating `Kiv` times the same errors.
- **Injection:** `Id = Idref`, `Iq = Iqref`, `P = vd·Id + vq·Iq`, `Q = −vd·Iq + vq·Id`.

**Why the current loop was removed.** With the documented PI current loop, the open-loop replay blew up within about a second on every recording, whatever gains I tried. The blow-up starts inside the fast current loop, with no input change. Replacing it with an ideal current made the model stable everywhere I tested. The cost is that the model no longer represents any inner-loop dynamics, so its fast response is approximated.

**Results.** Errors are RMSE against flat-prediction error:
- Validation `A_val_vref_op2`: P 3.4e-4 vs 5.9e-3 flat; Q 9.9e-4 vs 2.8e-2 flat (grid-equivalent replay).
- Validation `A_val_load_op1`: P 1.1e-4 vs 5.9e-3 flat; Q 1.8e-4 vs 2.9e-2 flat (grid-equivalent replay).
- Unseen train `A_fault_op1` and `A_line_op3`: stable, with P and Q errors well below flat, though the fault case is the weakest (P 1.6e-3 vs 5.5e-3 flat).

**Identifiability.** I did not run the frequency-response or droop linearization checks, so the scorer's linearization comparisons are untested.
- Reasonably identified: the frequency droop `m` (about 0.041) and the voltage-path gains, which the validation errors support.
- Poorly identified: `Tf` (fitted at about 2.6 ms, so the P output is nearly algebraic), `Tpl` and `Kip` (their effect is small), and `n` against `Kpq`, which trade off. `Kpi`, `Kii`, `Te`, `xf` and `rf` no longer affect the model.
- Fitting used only 6-second windows and a short optimizer run, so the parameters are not fully converged.

```json
{
  "params": {
    "Tf": 0.00264233024135123,
    "m": 0.04104325963319395,
    "Tpl": 0.04624120764262424,
    "Kpp": 1.6693443428171972,
    "Kip": 9.00904757576685,
    "n": 0.03453722544418228,
    "Tql": 0.03336594529439893,
    "Kpq": 0.8708424733756563,
    "Kiq": 5.96576874719327,
    "Kpv": 0.6287889922233151,
    "Kiv": 1.152137812905237,
    "Kpi": 1.0186873463082458,
    "Kii": 49.802332818983515,
    "Te": 0.009852136250649063,
    "xf": 0.14914113349629135,
    "rf": 0.0,
    "w0": 376.99111843077515
  },
  "defs": {
    "vd": "V*cos(delta - theta)",
    "vq": "-V*sin(delta - theta)",
    "vr": "Vset + n*(Kpq*(Qs - Qf) + xq - Qf)",
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
    "Ps": {"rhs": "(Pf - Ps)/Tpl", "init": "P0"},
    "xp": {"rhs": "Kip*(Ps - Pf)", "init": "P0"},
    "delta": {"rhs": "w0*m*(Kpp*(Ps - Pf) + xp - Pf)", "init": "theta0"},
    "Qs": {"rhs": "(Qf - Qs)/Tql", "init": "Q0"},
    "xq": {"rhs": "Kiq*(Qs - Qf)", "init": "Q0"},
    "xvd": {"rhs": "Kiv*(vr - vd)", "init": "P0/V0"},
    "xvq": {"rhs": "Kiv*(0 - vq)", "init": "-Q0/V0"}
  },
  "outputs": {"P": "Pe", "Q": "Qe"}
}
```