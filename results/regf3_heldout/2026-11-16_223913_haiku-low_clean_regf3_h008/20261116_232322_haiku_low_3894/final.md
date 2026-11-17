I saved a submission, but it is weak. Its mean validation error is 0.51, and the reactive-power channel is barely better than a constant output. Treat it as a placeholder rather than a validated model of the device.

**Submitted model (`submission.json`)**: the WECC droop structure, fitted by `tools/fit_model.py` with `w0` fixed. It has five states and passes the checker on both validation recordings: at rest at t=0, and no output mismatch.

- Measurement filters: `Pm`, `Qm` and `Vm` are first-order lags of P, Q and V (time constants `TPf`, `TQf`, `TVf`).
- Angle: `delta' = w0*mp*(P0 - Pm)`. This is a P–f droop acting on the internal angle.
- Voltage loop: `xv' = kiv*(Vcmd - Vm)`, with `Vcmd = Vset + mq*(Q0 - Qm)`, and an internal voltage `Ei = xv + kpv*(Vcmd - Vm) + kff*(Vset - V0)`.
- Coupling: P and Q come from a voltage source `Ei` at angle `delta` behind `Re + j*XL`.

**Fitted values and identification:**
- `XL` = 4.27 pu. This is implausible for a grid-forming unit (the documented range is 0.05–0.25 pu) and is probably absorbing the weak Q–V sensitivity. Poorly identified.
- `mq` = 679, which effectively disables the Q–V droop. Poorly identified, and it contradicts the documented Q–V droop.
- `mp` = 0.052 is the P–f droop gain. Its value is not compared with the documented range here.
- `TPf` = 0.097 s is the only time constant clearly above the sample period. `TQf` and `TVf` sit at the 0.001 s floor, so they are not identified.
- `kff` = 0.06 feeds the setpoint step through directly. `kpv` = 0 and `Re` = 0.

**Fit quality:** P error is roughly 0.06–0.3 on most train and validation recordings. Q error is 0.85–0.94 on nearly all of them, so the reactive response to voltage and setpoint is essentially not captured.

**What I tried:** a 60-evaluation fit of the template (about 34 s) was the only completed fit. Longer fits timed out, and a background run was lost. Physically plausible hand-set values (XL 0.15–0.5 pu, mq 0.01–0.05) gave far larger errors, with P error around 4, so the structure itself, not just the starting point, is the problem. I did not test other structures such as the virtual synchronous machine variant.

**Next steps if budget allowed:** run the fit longer in the foreground in shorter chunks, add a Q-channel structure that responds to the setpoint and voltage, and check whether the reactive response is actually a slow voltage-loop effect rather than an algebraic one.

```json
{"params": {"XL": 4.269063417260875, "Re": 0.0, "mp": 0.051766729559749605, "mq": 679.0376540757234, "kpv": 0.0, "kiv": 0.5680667325877105, "kff": 0.06027167610869206, "TPf": 0.09657855450774372, "TQf": 0.0009999999999994462, "TVf": 0.0009999999999994458, "w0": 376.99111843077515}, "defs": {"Vcmd": "Vset + mq*(Q0 - Qm)", "Ei": "xv + kpv*(Vcmd - Vm) + kff*(Vset - V0)", "dl": "delta - theta", "Pe": "V*(Re*(Ei*cos(dl) - V) + XL*Ei*sin(dl))/(Re**2 + XL**2)", "Qe": "V*(XL*(Ei*cos(dl) - V) - Re*Ei*sin(dl))/(Re**2 + XL**2)"}, "states": {"delta": {"rhs": "w0*mp*(P0 - Pm)", "init": "theta0 + atan2((XL*P0 - Re*Q0)/V0, V0 + (Re*P0 + XL*Q0)/V0)"}, "xv": {"rhs": "kiv*(Vcmd - Vm)", "init": "sqrt((V0 + (Re*P0 + XL*Q0)/V0)**2 + ((XL*P0 - Re*Q0)/V0)**2)"}, "Pm": {"rhs": "(Pe - Pm)/TPf", "init": "P0"}, "Qm": {"rhs": "(Qe - Qm)/TQf", "init": "Q0"}, "Vm": {"rhs": "(V - Vm)/TVf", "init": "V0"}}, "outputs": {"P": "Pe", "Q": "Qe"}}
```