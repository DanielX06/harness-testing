The submission is written to `submission.json` and passes the checker on both validation files. It is a four-state model: a P channel that tracks frequency and a Q channel that tracks voltage setpoint and voltage. I did not run any closed-loop grid simulation, so stability in the scorer's grid is untested.

**Equations** (V, θ, Vset are live; subscript 0 is the operating point at t = 0)

- **Frequency droop (P):** y is a washout filter on θ with τw = 0.0195 s. Then
  dpz/dt = [P0 + Kd·(θ − y)/τw + Kpv·(V − V0) − pz] / τp, with Kd = −0.0453, τp = 0.0275 s, Kpv = −0.0137.
  The output is P = pz.
- **Voltage control (Q):** qs is a lag on the setpoint change, dqs/dt = (Kq·(Vset − V0) − qs)/τq, with Kq = 1.525 and τq = 2.28 s. vf is a fast filter on V, τv = 0.0028 s. The output is
  Q = Q0 + qs + Kv·(vf − V0) + c·(P − P0), with Kv = 0.799 and c = 0.961.

**Identification**

- **P:** well identified. Kd and τw trade off against each other, and the angle-level term was rejected. An angle-level term fit to the ambient data drove the model unstable, and the generator trip drives θ to about −55 rad, which no P model can use. P replays to about 0.0014 to 0.0019 pu RMSE on validation, against 0.001 pu noise.
- **Q:** the setpoint response (Kq, τq) is well determined by the staged tests. The voltage droop Kv is less certain, and the coupling c to the device's own P is empirical; it was needed to explain a Q step after the −8% load change at bus 8, which V alone did not explain.
- **Poorly fitted:** the generator-trip recording still shows a persistent Q offset of about 0.025 pu, and the fault recording about 0.03 pu. An integral-action variant was tried and rejected because its fitted voltage-droop sign was wrong, so the large-disturbance Q behaviour is not captured.

**Validation (open-loop replay, RMSE)**

| File | P | Q | Q flat baseline |
|---|---|---|---|
| A_val_load_op1 | 1.4e-3 | 1.1e-2 | 2.8e-2 |
| A_val_vref_op2 | 1.9e-3 | 3.8e-3 | 2.8e-2 |

```json
{
  "params": {"Kq": 1.5249, "Kv": 0.7987, "tq": 2.2767, "Kd": -0.0453, "tw": 0.0195, "tp": 0.0275, "Kpv": -0.0137, "c": 0.9614},
  "defs": {"dv": "V-V0", "dth": "theta-y"},
  "states": {
    "qs": {"rhs": "(Kq*(Vset-V0)-qs)/tq", "init": "0.0"},
    "vf": {"rhs": "(V-vf)/0.0028", "init": "V0"},
    "y": {"rhs": "(theta-y)/tw", "init": "theta0"},
    "pz": {"rhs": "(P0+Kd*(theta-y)/tw+Kpv*(V-V0)-pz)/tp", "init": "P0"}
  },
  "outputs": {"P": "pz", "Q": "Q0+qs+Kv*(vf-V0)+c*(pz-P0)"}
}
```