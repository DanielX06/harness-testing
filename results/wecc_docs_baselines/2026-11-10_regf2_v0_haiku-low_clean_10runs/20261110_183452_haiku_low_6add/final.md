The model is saved to `submission.json`. It passes the checker on both validation recordings (at rest at t=0, no init or output mismatch), but it is a compromise: the fault and trip responses fit noticeably worse than the ambient and setpoint-test data.

**Model (terminal device, Vset-driven, with V and θ inputs)**

- Angle-rate estimate: `w = (θ − θx)/Tw`, where θx is a state starting at θ0.
- Filtered voltage: `xm' = (V − xm)/Tm`.
- Leaky integrator on the setpoint error: `xi' = Ki·(Vset − xm) − xi/Tr`, starting at 0.
- Active power: `Ps' = (P0 − Kp·w + Kpv·(V − V0) − Ps)/Tp`, output P = Ps.
- Reactive power: `Qs' = (Q0 + Kq·(Vset − xm) + Kqv·(V − V0) + xi − Qs)/Tq`, output Q = Qs.

Fitted values on train (all eight recordings, every 5th sample): Kq=1.51, Tq=0.103 s, Kqv=2.15, Kp=0.052, Tw=0.0055 s, Tp=0.100 s, Kpv=−0.120, Tm=0.132 s, Ki=0.756, Tr=33 s. Overall RMS ≈ 0.0097 pu.

**Validation (open-loop replay)**
- `A2_val_load_op1`: P RMSE 5.0e-4, Q RMSE 7.6e-3 (flat-line baseline 2.6e-2).
- `A2_val_vref_op2`: P RMSE 1.3e-3, Q RMSE 1.0e-2 (flat-line baseline 2.8e-2).

**Confidence by parameter**
- Well identified: the fast P response (Tp, Kp) and the Q setpoint-step response (Kq, Tq, Tm) are constrained by the staged tests and the faults.
- Poorly identified: Tr (33 s) is set by the slow tail only and is essentially unconstrained within the 40–60 s recordings, so the steady-state droop depends on it. Kqv and Ki trade off against each other; only their combination in the slow path is well defined.

**Concerns**
- The steady-state droop is about −24 pu Q per pu V (from Kq + Ki·Tr). This is stiff and comes from the poorly identified Tr, so it may not match the real device's dQ/dV check.
- Kqv gives a positive instantaneous dQ/dV at high frequency. The fitted Q path rises with V on fast timescales, which is what the post-fault data show. This may make the frequency response and closed-loop stability sensitive to the scorer's grid, and I did not check closed-loop stability.
- I did not complete the closed-loop or linearization checks. The fault and line-trip residuals (≈0.016 on train) are the largest misfit, so the large-disturbance behaviour is the weakest part of this model.

```json
{
  "params": {
    "Kq": 1.5095249352530182,
    "Tq": 0.10327439829717906,
    "Kqv": 2.150200932607188,
    "Kp": 0.052194364473413024,
    "Tw": 0.005515238378277275,
    "Tp": 0.09983483815282704,
    "Kpv": -0.11958645495252915,
    "Tm": 0.13170428231377707,
    "Ki": 0.75615213255896,
    "Tr": 33.03756144921551
  },
  "defs": {
    "w": "(theta-thx)/Tw",
    "Pt": "P0-Kp*w+Kpv*(V-V0)",
    "Qt": "Q0+Kq*(Vset-xm)+Kqv*(V-V0)+xi"
  },
  "states": {
    "thx": {"rhs": "w", "init": "theta0"},
    "Ps": {"rhs": "(Pt-Ps)/Tp", "init": "P0"},
    "Qs": {"rhs": "(Qt-Qs)/Tq", "init": "Q0"},
    "xm": {"rhs": "(V-xm)/Tm", "init": "V0"},
    "xi": {"rhs": "Ki*(Vset-xm)-xi/Tr", "init": "0.0"}
  },
  "outputs": {"P": "Ps", "Q": "Qs"}
}
```