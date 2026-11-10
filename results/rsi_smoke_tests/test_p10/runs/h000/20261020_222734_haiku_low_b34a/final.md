The model is written to `submission.json` and passes the checker. Open-loop replay on the validation files is reasonable but not strong on the voltage-reference recording, so treat it as a first-pass model.

**Structure (fitted on train/)**

- **Active power:** a frequency droop plus a voltage term, filtered by a fast lag. Frequency deviation is estimated from a washed-out θ, with ω = (θ−θ0)/(2π·60) through a 0.17 s filter. P = P0 + xp, where xp′ = (Kv·(V−V0) − Kw·ω − xp)/tp, with Kw ≈ 17.4 pu and tp ≈ 0.004 s.
- **Reactive power:** a lagged voltage-regulator output. Q = xq, where xq′ = (Q0 + Kp·(Vset−V) + xi + Kpq·xp − xq)/tqv, with Kp ≈ 0.98, Kpq ≈ 0.99 and tqv ≈ 3.9 s.
- **Integrator:** xi′ = (Ki·(Vset−V) − xi)/ti, with Ki ≈ 2.27 and ti ≈ 4.7 s.

**Identification**

- **Frequency droop (Kw):** reasonably well identified from the generator-trip and load-step recordings.
- **Fast P lag (tp):** poorly identified. It sits near the simulation step, so its value mainly reflects the step size.
- **Q dynamics (Kp, Ki, ti, tqv, Kpq):** these trade off against each other. The integrator and lag time constants are only loosely determined.
- **Voltage term (Kqv):** the constrained fit drove it to zero, so the model has no direct V-dependence in Q. The unconstrained fits wanted a sizeable direct term with the opposite sign, which I rejected for stability.

**Known weaknesses**

- The Q residual on line-trip and fault recordings stays at about 0.02–0.04 pu, and the fault response (large Q rise as V collapses, then overshoot) is not captured. The device may have a current limit or a nonlinear reactive response I did not identify.
- Validation Q error on the voltage-reference recording is 0.020 against a flat-line baseline of 0.030. P there is barely better than flat (0.0046 vs 0.0059).
- I did not run the frequency-response or droop checks, and I did not test closed-loop behaviour beyond the open-loop replay.

```json
{
  "params": {
    "Kp": 0.9796510460836004,
    "Ki": 2.2742321845889784,
    "ti": 4.745700840527397,
    "Kqv": -1.21338974575027e-23,
    "tqv": 3.867860680158222,
    "Kpq": 0.9851699617427011,
    "Kw": 17.37640580237308,
    "tf": 0.16842671329849596,
    "Kv": 0.46545249130261235,
    "tp": 0.0038392422147379467
  },
  "defs": {
    "thd": "theta-theta0",
    "e": "Vset-V",
    "om": "(thd-wlp)/tf/(2*pi*60)"
  },
  "states": {
    "wlp": {"rhs": "(thd-wlp)/tf", "init": "0.0"},
    "xp": {"rhs": "(Kv*(V-V0)-Kw*om-xp)/tp", "init": "0.0"},
    "xi": {"rhs": "(Ki*e-xi)/ti", "init": "0.0"},
    "xq": {"rhs": "(Q0+Kp*e+xi+Kqv*(V-V0)+Kpq*xp-xq)/tqv", "init": "Q0"}
  },
  "outputs": {
    "P": "P0+xp",
    "Q": "xq"
  }
}
```