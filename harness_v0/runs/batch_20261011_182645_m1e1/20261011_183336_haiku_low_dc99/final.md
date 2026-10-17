The submission is written to `submission.json`. It passes the scorer's checks on both validation files and starts at rest. I did not run a closed-loop grid simulation, so stability in the grid is unverified.

**Model**

- **Reactive power (Q):** a first-order lag, Tq, tracks a target built from three terms:
  - a setpoint term, a·(Vset − V0). Gain a ≈ 1.46 pu/pu, the strongest effect and the staged tests show it clearly;
  - a voltage term, b·(V − V0). b ≈ 0.61;
  - an angle-rate term, c·(θ − xm), where xm is a lagged copy of θ (time constant Tw ≈ 1.5 s). This is a high-pass on angle, so it acts like a frequency-proportional term. c ≈ −0.029.
- **Active power (P):** P = P0 − Kpv·(θ − xp), where xp is a lagged copy of θ with time constant Tp ≈ 0.116 s. Kpv ≈ 0.383. For slow signals this is a frequency droop of roughly −0.045 pu P per rad/s of angle rate.
- **Initialisation:** both states start at rest (xq = Q0, xm and xp = θ0), so P = P0 and Q = Q0 at t = 0.

**Fit and validation**

- P validates close to the noise level: open-loop RMSE about 0.0017 to 0.0019 pu (noise 0.001), against 0.024 and 0.007 for a flat prediction.
- Q validates at 0.0095 on the load-change file and 0.0042 on the setpoint-test file, against 0.028 for flat. The load-change file was the worst case for the earlier voltage-only Q model.
- The model fits the staged setpoint steps well. It does not fit the fault and generator-trip recordings as well: the Q residuals there are about 0.02 to 0.03 pu. The remaining error looks like slow Q drift that I did not identify.

**Identifiability**

- a (setpoint gain) and Tq (Q lag) are well identified. The staged tests excite them directly.
- Tq is small (about 0.04 s before refitting, 0.04 s after) and the setpoint step response is quick, so the lag is only loosely constrained.
- b and c trade off against each other. Both are constrained only by the ambient and event data, so their individual values are less reliable than a.
- Kpv and Tw (in the P path) are poorly separated from each other. Only their product, the frequency droop, is well determined. The P droop was fitted from small angle-drift signals, so its magnitude carries noticeable uncertainty.
- The P model and Q angle term use different filters (Tp for P, Tw for Q). This was a deliberate choice to keep the P fit from degrading when I added the Q angle term.

```json
{
  "params": {"a": 1.4646, "b": 0.6115, "Tq": 0.0375, "c": -0.0293, "Tw": 1.5178, "Kpv": 0.383, "Tp": 0.1163},
  "defs": {
    "Qt": "Q0 + a*(Vset-V0) + b*(V-V0) + c*(theta-xm)",
    "dP": "-Kpv*(theta-xp)"
  },
  "states": {
    "xq": {"rhs": "(Qt-xq)/Tq", "init": "Q0"},
    "xm": {"rhs": "(theta-xm)/Tw", "init": "theta0"},
    "xp": {"rhs": "(theta-xp)/Tp", "init": "theta0"}
  },
  "outputs": {"P": "P0+dP", "Q": "xq"}
}
```