The submission is saved as `submission.json`. It passes the checker on both validation recordings (at rest at t=0), but I did not run a closed-loop check in the grid, so stability in the scorer is untested.

**Model (reduced WECC droop structure, VFlag=1, Re=0, limits inactive)**

Internal states:
- Filtered P: `Pm' = (P − Pm)/TPf`
- Filtered Q: `Qm' = (Q − Qm)/TQf`
- Filtered V: `Vm' = (V − Vm)/TVf`
- Voltage-loop integrator: `xv' = kiv·(Vcmd − Vm)`, with `Vcmd = Vset + mq·(Q0 − Qm)`
- Absolute internal angle: `delta' = w0·mp·(P0 − Pm)`

Outputs:
- `P = V·xv·sin(delta − theta)/XL`
- `Q = (V·xv·cos(delta − theta) − V²)/XL`

Initial values are set from the operating point so the model starts at rest: `xv0 = |E0|` and `delta0 = theta0 + atan2(XL·P0/V0, (XL·Q0 + V0²)/V0)`.

**Fitted parameters** (fit on vref_op1, amb_op1 and vref_op3; the first fit used all three, not the other ambient recording):
- XL = 1.0 (hit the upper bound; poorly identified, trades off against mq and the voltage-loop gains)
- mq = 0.056, kiv = 4.86 pu/s, kpv = 0.074 (moderately identified)
- TVf = 0.02 s (the fit sits at a bound, so poorly identified), TQf = 0.001 s (at lower bound), TPf = 0.065 s, mp = 0.049 (poorly identified; P-f droop is weakly constrained by these recordings).

**Fit quality and known gaps**
- Open-loop replay RMS: P about 0.0003–0.001 pu, Q about 0.008–0.016 pu.
- The largest residual is Q on the staged voltage steps. The device overshoots in Q (to about 0.227 pu, then settling near 0.22), and this model under-predicts that fast jump by about 0.04 pu at the peak. Attempts to fix this with a constrained XL (0.15 or 0.3) or a fast feedthrough were not completed within the budget.
- Fault and generator-trip recordings were not fit. The current-limit logic from the reference model is not implemented, so severe-fault behaviour is not captured.
- The fitted XL = 1.0 is physically implausible for this unit, so the Q-side coupling is probably mis-specified. The steady-state Q-V droop and the frequency response may therefore be off, and the scorer's linearization checks may suffer.