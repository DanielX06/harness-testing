I'm submitting a two-part model. Active power is a droop-driven frequency path with a fast filter. Reactive power is a proportional-integral voltage loop with a reactive droop and a slow voltage measurement. It replays both validation files well, but the reactive channel is the weaker part.

**Equations** (V, θ, Vset live; P0, Q0, V0, θ0 from the operating point)

- Frequency estimate: `w = (θ − y)/Tp`, with state `y' = (θ − y)/Tp`, `y(0) = θ0`. This is a high-pass of the terminal angle, which stands in for the device's internal frequency deviation.
- Active power: `Pf' = (P0 − Dp·w − Pf)/Tf`, `P = Pf`, `Pf(0) = P0`.
- Reactive droop: `Vin = Vset − kd·(Qf − Q0)`.
- Reactive measurement: `Qf' = (Q − Qf)/Tm`, `Qf(0) = Q0`.
- Voltage measurement: `Vm' = (V − Vm)/Tv`, `Vm(0) = V0`.
- Integrator: `X' = Ki·(Vin − Vm)`, `X(0) = 0`.
- Reactive power: `Q = Q0 + X + Kp·(Vin − Vm)`.

At t = 0 every right-hand side is zero and the outputs equal P0 and Q0.

**Evidence for the structure**
- The power-loop output equals `Pf + 0.0743·w` exactly, and the gentrip steady state fits `w ≈ 22·(P0 − Pf)`.
- The inner voltage reference matches `Vset − 0.04·(Qf − Q0)` in the logs.

**Fit and validation**
- Active power: RMSE about 6–7e-4 on validation, against 2.4e-2 for a flat model.
- Reactive power: RMSE about 5e-3 on validation, against 2.9e-2 for a flat model. Training RMSE was 0.015 overall, and the largest errors are after the line trip and the generator trip.
- Grid-equivalent replay is stable on both validation files, with P RMSE about 5–7e-4 and Q RMSE about 4–5e-3.

**Parameter identifiability**
- `Dp` (about 0.045) and `Tf` (about 0.0025 s) are well identified from the frequency events.
- `Tp` (about 0.022 s) is moderately identified and mostly sets the high-pass that estimates frequency.
- `kd` (about 0.036) is reasonably identified from the setpoint tests.
- `Kp`, `Ki`, `Tm` and `Tv` are poorly identified. `Tv` (about 2.7 s) and `Ki` trade off against each other. `Tm` is tiny and its effect is small. The steady-state reactive gain `dQ/dV` in the model comes from `Kp` and `Ki` together, so it is less reliable than the active-power droop.
- I did not find a clean physical explanation for the reactive slope of about 2 pu/pu seen in the static data, so the reactive structure is an empirical fit rather than a verified control law.

```json
{
  "params": {
    "Dp": 0.04512211344541472,
    "Tf": 0.0025359299205231067,
    "Tp": 0.022371353200983886,
    "kd": 0.03573594177837408,
    "Kp": 0.565363284194482,
    "Ki": 1.208743068112289,
    "Tm": 0.000531287572362954,
    "Tv": 2.6913733225734666
  },
  "defs": {
    "w": "(theta-y)/Tp",
    "Vin": "Vset-kd*(Qf-Q0)",
    "Qc": "Q0+X+Kp*(Vin-Vm)"
  },
  "states": {
    "y": {"rhs": "(theta-y)/Tp", "init": "theta0"},
    "Pf": {"rhs": "(P0-Dp*w-Pf)/Tf", "init": "P0"},
    "Qf": {"rhs": "(Qc-Qf)/Tm", "init": "Q0"},
    "X": {"rhs": "Ki*(Vin-Vm)", "init": "0.0"},
    "Vm": {"rhs": "(V-Vm)/Tv", "init": "V0"}
  },
  "outputs": {"P": "Pf", "Q": "Qc"}
}
```