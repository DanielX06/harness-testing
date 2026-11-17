The submission is saved as `submission.json` and passes the checker on both validation recordings (at rest at t=0, output mismatch ~1e-16). I did not run a closed-loop grid test, so stability in the scorer's network is unverified.

**Model:** a grid-forming droop-type source behind a reactance, with the WECC droop structure reduced to five states.

- Output: `P = E·V·sin(δ−θ)/XL`, `Q = (E·V·cos(δ−θ) − V²)/XL`, with `E = clip(kpv·(Vc−Vm) + xv, 0, 1.5)`.
- Voltage command: `Vc = Vset + mq·(Q0 − Qm)`.
- States:
  - `Pm' = (P − Pm)/TPf`, `Qm' = (Q − Qm)/TQf`, `Vm' = (V − Vm)/TVf` (measurement filters);
  - `xv' = kiv·(Vc − Vm)` (voltage integrator);
  - `δ' = ω0·mp·(P0 − Pm)` (P–f droop, where `P0` is the dispatch).
- Initial state comes from the power flow: `E0 = |V0 + j·XL·P0/V0 ... |` in the form `(V0 + XL·Q0/V0) + j·XL·P0/V0`, and `δ0 = θ0 + atan2(XL·P0/V0, V0 + XL·Q0/V0)`.

**Fitted parameters** (fit on 5 training recordings, first 20 s each, by open-loop replay of measured V, θ, Vset):

| Parameter | Value | Assessment |
|---|---|---|
| XL | 1.00 | Poorly identified. Outside the documented 0.05–0.25 range. Trades off against mq. |
| mq | 19.4 | Poorly identified and outside the documented 0–0.2 range. Only its ratio to XL matters for the terminal behaviour. |
| kiv | 3.60 | Within range. |
| kpv | 0.0046 | Small; hardly constrained. |
| mp | 0.0587 | Just above the documented 0.005–0.05 range. Sets the frequency droop (dP/dω ≈ −17 pu/pu). |
| TPf | 0.0148 s | Within range. |
| TQf | 0.0025 s | Below the documented 0.01 s minimum. Fast, so it has little effect on the fit. |
| TVf | 0.090 s | Within range. |

**Validation:** the open-loop fit on the two validation recordings gives P rms about 1e-4 (staged vref test) and 1.7e-3 (load test), and Q rms about 6e-4 and 1.5e-3. The result is insensitive to the integration step (1, 2 and 4 ms give the same errors).

**Rejected:** a refit constrained to the documented parameter ranges fit much worse (Q rms 0.034 on validation against 0.0006 for the unconstrained fit). The unconstrained fit was kept because it validates well, but its large mq and XL, and the high mp, are the main risks. Two of them shape the Q-voltage and frequency responses the scorer checks, so they may not match the real device's droops even though the replay matches.

```json
{
  "params": {
    "XL": 1.0029006315767721,
    "mq": 19.39272080918347,
    "kiv": 3.5968024722779752,
    "kpv": 0.004595288267965651,
    "mp": 0.05867294434077516,
    "TPf": 0.014831788643149156,
    "TQf": 0.0025328352234397374,
    "TVf": 0.09044136923216248,
    "w0": 376.99111843077515
  },
  "defs": {
    "Vc": "Vset + mq*(Q0 - Qm)",
    "Ee": "Min(Max(kpv*(Vc - Vm) + xv, 0.0), 1.5)",
    "s": "d - theta",
    "Pe": "Ee*V*sin(s)/XL",
    "Qe": "(Ee*V*cos(s) - V**2)/XL"
  },
  "states": {
    "Pm": {"rhs": "(Pe - Pm)/TPf", "init": "P0"},
    "Qm": {"rhs": "(Qe - Qm)/TQf", "init": "Q0"},
    "Vm": {"rhs": "(V - Vm)/TVf", "init": "V0"},
    "xv": {"rhs": "kiv*(Vc - Vm)", "init": "sqrt((V0 + XL*Q0/V0)**2 + (XL*P0/V0)**2)"},
    "d": {"rhs": "w0*mp*(P0 - Pm)", "init": "theta0 + atan2(XL*P0/V0, V0 + XL*Q0/V0)"}
  },
  "outputs": {"P": "Pe", "Q": "Qe"}
}
```