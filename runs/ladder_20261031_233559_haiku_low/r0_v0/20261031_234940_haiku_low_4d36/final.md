I've written a submission that passes the scorer's checks on both validation files, but its reactive-power behaviour during grid events is not captured. On the load-change validation file, Q replay is worse than a flat line.

**Model (3 states, 7 params):**

- **Reactive power:** a lagged voltage-control law, Tq·dxq/dt = Q0 + Kq·(Vset−V0) + Kv·(V−V0) − xq, with Q = xq. Kq ≈ 0.87 pu/pu is the setpoint gain, which is well identified from the staged steps. Kv ≈ +1.86 is the coefficient on V. It is positive, which is physically odd for a droop, but constraining it to be non-positive fits clearly worse (RMS 0.0078 against 0.0050). I read it as partly absorbing grid coupling. Tq is fixed at 0.01 s, because the fitted value (~0.002 s) would make the model stiff.
- **Active power:** a lagged law, Tp·dxp/dt = P0 + Kp·(V−V0) − Dp·ω_f − xp, with P = xp. Kp ≈ −0.095 pu/pu is a weak voltage sensitivity. Dp ≈ 0.045 is a frequency droop, where ω_f is a low-passed bus-angle rate, implemented as (θ − xth)/Tw with Tw ≈ 0.107 s. Tp is fixed at 0.01 s because the fit pushed it to its lower bound. Dp and Tw are weakly identified and trade off against each other.

**Validation results (open-loop replay, from `check_submission.py`):**

| File | P RMSE (flat) | Q RMSE (flat) |
|---|---|---|
| `A_val_vref_op2` | 0.0011 (0.0059) | 0.0048 (0.0295) |
| `A_val_load_op1` | 0.0005 (0.0235) | 0.0298 (0.0276) |

**Known gaps:**
- Q during the fault and load-change events is poorly captured. A refit of Kq, Kv and Tq across the ambient, fault and staged-step data gave Kq ≈ 1.58, Kv ≈ 1.13, Tq ≈ 0.049 s, but its fault-case Q residual was still 0.022. I did not adopt it, and I did not check it on validation.
- The Kv sign and the closed-loop stability of the Q–V feedback are unverified. The scorer's closed-loop run is the real test, and I did not run it.
- The P frequency droop is small and weakly identified, so the frequency-response check will likely be off.

```json
{
  "params": {"Kq": 0.86910662, "Kv": 1.85758555, "Tq": 0.01, "Kp": -0.0947, "Dp": 0.045, "Tp": 0.01, "Tw": 0.1067},
  "defs": {"omf": "(theta-xth)/Tw"},
  "states": {
    "xq": {"rhs": "(Q0+Kq*(Vset-V0)+Kv*(V-V0)-xq)/Tq", "init": "Q0"},
    "xp": {"rhs": "(P0+Kp*(V-V0)-Dp*omf-xp)/Tp", "init": "P0"},
    "xth": {"rhs": "(theta-xth)/Tw", "init": "theta0"}
  },
  "outputs": {"P": "xp", "Q": "xq"}
}
```