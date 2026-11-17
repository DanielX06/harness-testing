The submission is saved as `submission.json` and passes `tools/check_submission.py` on both validation files. Open-loop RMS on those files is about 0.0004–0.0006 pu for P and 0.007 pu for Q. I did not run a closed-loop check inside the grid, so stability under the scorer is unverified.

**Structure.** A grid-forming voltage source behind a reactance, with a slow P-f droop on the internal angle and a Q-V droop with an integrator:

- Output: P = V·E·sin(δ−θ)/XL, Q = (V·E·cos(δ−θ) − V²)/XL, where E is the state `xv`.
- Angle: dδ/dt = ω0·mp·(P0 − Pm), starting at θ0 + atan2(P0·XL/V0, Q0·XL/V0 + V0).
- Power filters: Pm and Qm are first-order lags of P and Q (time constants TP, TQ).
- Voltage: Vm is a lag of the measured V (time constant TV). The integrator is dxv/dt = kiv·(Vcmd − Vm), with Vcmd = Vset + mq·(Q0 − Qm). Its initial value is E0 = √((P0·XL/V0)² + (Q0·XL/V0 + V0)²).
- Every state starts at rest at t = 0, and the output equals P0 and Q0 there.

**Fitted parameters** (train recordings, decimated to 4 ms):

| Parameter | Value | Notes |
|---|---|---|
| XL | 1.86 | Effective, not physical. Pinned at my upper bound until I widened it, and it trades off against the voltage loop. |
| mq | 0.0367 | Q-V droop gain. Reasonably identified; dQ/dV ≈ −1/mq ≈ −27 pu. |
| kiv | 2.82 | Voltage integral gain. Moderately identified. |
| mp | 0.0594 | P-f droop gain. Fits the post-trip angle drift, dP/dω ≈ −17 pu. |
| TP | 0.001 s | Hit its lower bound; effectively no filter. |
| TQ | 0.0011 s | Hit its lower bound; effectively no filter. |
| TV | 1.37 s | Large lag on measured V. Poorly identified and trades off with XL and kiv. |

**Limitations and rejected candidates.**
- My first fits (XL ≤ 0.5, TV ≤ 0.2) left a generator-trip recording at RMS 0.11 pu and every other event at 0.02–0.03 pu. Widening the bounds fixed most of that.
- I dropped the proportional voltage gain kpv in the final model. I included it as a parameter but never wired it into the simulation, so the fit gave it no effect.
- The fitted XL of 1.86 and TV of 1.37 s are effective values. Treat the voltage-loop dynamics and the Q-V response as an empirical fit; the reactance is not a physical reactance.
- The fit used only the train recordings. I did not refit on the fault and line-trip events with the final parameters, and I did not check the frequency-response or droop targets against the device.

```json
{"params": {"XL": 1.8644614950308673, "mq": 0.03666752605380366, "kiv": 2.815526646523107, "mp": 0.059435226867884994, "TP": 0.0010000029603646934, "TQ": 0.0011276657674795599, "TV": 1.3695387487858808, "w0": 376.99111843077515}, "defs": {"Vcmd": "Vset+mq*(Q0-Qm)", "dd": "delta-theta", "Pout": "V*xv*sin(dd)/XL", "Qout": "(V*xv*cos(dd)-V*V)/XL"}, "states": {"delta": {"rhs": "w0*mp*(P0-Pm)", "init": "theta0+atan2((P0*XL/V0),(Q0*XL/V0+V0))"}, "Pm": {"rhs": "(Pout-Pm)/TP", "init": "P0"}, "Qm": {"rhs": "(Qout-Qm)/TQ", "init": "Q0"}, "Vm": {"rhs": "(V-Vm)/TV", "init": "V0"}, "xv": {"rhs": "kiv*(Vcmd-Vm)", "init": "sqrt((P0*XL/V0)**2+(Q0*XL/V0+V0)**2)"}}, "outputs": {"P": "Pout", "Q": "Qout"}}
```