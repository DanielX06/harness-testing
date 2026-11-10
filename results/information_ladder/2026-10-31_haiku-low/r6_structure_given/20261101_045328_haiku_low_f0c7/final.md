The submitted model is a stable terminal model. It is fitted only partly, and its reactive-power response is weak on the generator-trip recording, so treat it as a provisional fit rather than a well-identified one.

**Equations (per unit on the 900 MVA rating)**

The structure is the documented one from `structure_menu.py`:

- **Active-power droop and power loop.** The internal angle `delta` runs at `w0·m·(Kpp·(Ps−Pf) + xp − Pf)`. Here `Pf` is the filtered output, `Ps` is the setpoint lagged by `Tpl`, and `xp` is an integrator of `Kip·(Ps−Pf)`.
- **Reactive droop and reactive loop.** The voltage reference is `vr = Vset + n·(Kpq·(Qs−Qf) + xq − Qf)`. `Qf` is the filtered reactive output, `Qs` is lagged by `Tql`, and `xq` integrates `Kiq·(Qs−Qf)`.
- **Voltage loop.** A PI loop in the internal frame gives `Id_ref = Kpv·(vr−vd) + xvd` and `Iq_ref = Kpv·(0−vq) + xvq`.
- **Current loop.** A PI loop with lag `Te` and filter reactance `xf` drives the converter voltage `(ud, uq)`.
- **Outputs.** `P = Pe` and `Q = Qe`, the injected power computed from the internal currents.

**Parameters submitted (set `m2`)**

| Parameter | Value | Note |
|---|---|---|
| m | 0.0497 | Well identified: the fit moved it little from its start. |
| n, Kpq, Kiq, Tql | 0.05, 1.0, 10, 0.05 | Left at defaults. Not fitted, so poorly identified. |
| Tpl, Kpp, Kip | 0.05, 1.0, 10 | Left at defaults. Not fitted, so poorly identified. |
| Kpv, Kiv | 1.0, 5.0 | Original fit values. |
| Kpi, Kii | 0.3, 5.0 | Reduced from the fit (1.0, 50), which was unstable. |
| Te, xf, rf, Tf | 0.01, 0.15, 0, 0.01 | Fixed by default. |

The fit ran only about 22 cost evaluations and did not converge. The P and Q parameters, apart from `m`, are weakly identified, and the inner-loop gains trade off strongly against each other. The fit left the outer gains near their defaults.

**Validation**

- The fitted set from the first pass (`cand_a`) was unstable in the scorer's open-loop replay on both validation files. Scaling down the inner and voltage gains fixed the open-loop replay. Only set `m2` also stayed accurate in the grid-equivalent replay.
- Grid-equivalent replay, `m2`:
  - Validation vref file: P RMSE 1.3e-3 (flat 5.9e-3), Q RMSE 3.7e-3 (flat 2.9e-2).
  - Validation load file: P RMSE 5.1e-3 (flat 2.4e-2), Q RMSE 7.9e-3 (flat 2.8e-2).
  - Generator-trip training file: P RMSE 2.0e-2 (flat 9.4e-2), Q RMSE 2.8e-2 (flat 9.7e-2).
- Open-loop on the generator-trip recording, Q is worse than flat (RMSE 0.18 against 0.097). The reactive response to that event is not captured.
- Not checked: the linearized frequency-response and droop checks, and the fault recording (excluded from the fit by design).

```json
{"params": {"Tf": 0.010000000000000004, "m": 0.04970117353254992, "Tpl": 0.05000000000000001, "Kpp": 1.0, "Kip": 10.000000000000002, "n": 0.05000000000000001, "Tql": 0.05000000000000001, "Kpq": 1.0, "Kiq": 10.000000000000002, "Kpv": 1.0, "Kiv": 4.999999999999999, "Kpi": 0.3, "Kii": 5.0, "Te": 0.010000000000000004, "xf": 0.15, "rf": 0.0, "w0": 376.99111843077515}, "defs": {"vd": "V*cos(theta-delta)", "vq": "-V*sin(theta-delta)", "vr": "Vset + n*(Kpq*(Qs - Qf) + xq - Qf)", "Idref": "Kpv*(vr - vd) + xvd", "Iqref": "Kpv*(0 - vq) + xvq", "det": "rf**2 + xf**2", "Id": "(rf*(ud - vd) + xf*(uq - vq))/det", "Iq": "(-xf*(ud - vd) + rf*(uq - vq))/det", "udref": "Kpi*(Idref - Id) + xid + vd + rf*Id - xf*Iq", "uqref": "Kpi*(Iq - Iq) + xiq + vq + rf*Iq + xf*Id", "Pe": "vd*Id + vq*Iq", "Qe": "vq*Id - vd*Iq"}, "states": {"Pf": {"rhs": "(P - Pf)/Tf", "init": "P0"}, "Qf": {"rhs": "(Q - Qf)/Tf", "init": "Q0"}, "Ps": {"rhs": "(Pf - Ps)/Tpl", "init": "P0"}, "xp": {"rhs": "Kip*(Ps - Pf)", "init": "0"}, "delta": {"rhs": "w0*m*(Kpp*(Ps - Pf) + xp - Pf)", "init": "theta0"}, "Qs": {"rhs": "(Qf - Qs)/Tql", "init": "Q0"}, "xq": {"rhs": "Kiq*(Qs - Qf)", "init": "0"}, "xvd": {"rhs": "Kiv*(vr - vd)", "init": "0"}, "xvq": {"rhs": "Kiv*(0 - vq)", "init": "0"}, "xid": {"rhs": "Kii*(Idref - Id)", "init": "0"}, "xiq": {"rhs": "Kii*(Iqref - Iq)", "init": "0"}, "ud": {"rhs": "(udref - ud)/Te", "init": "V0*cos(theta0-theta0)"}, "uq": {"rhs": "(uqref - uq)/Te", "init": "0"}}, "outputs": {"P": "Pe", "Q": "Qe"}}
```