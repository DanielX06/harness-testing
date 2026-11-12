I saved a submission, but it is a rough model. It passes the checker and runs at rest, and it is only partly validated.

**Model** (saved in `submission.json`, 2 states, 8 params):
- Let `phi` be an internal angle state that tracks `theta` with time constant `Tw`, and let `om = (theta - phi)/Tw` be a frequency-like signal.
- `z` is an integrator driven by the voltage error: `z' = Ki*(Vset - V) - z/Tq`.
- `P = P0 + Kvp*(Vset - V0) - Dw*om + KpV*(V - V0)`
- `Q = Q0 + Kvs*(Vset - V0) - Kp*(V - V0) + z`

**Fitted values** (pooled fit on five training recordings, 10 ms decimated):
- Kp = -1.03, Ki = 0.76, Tq = 33.5, Kvs = 1.24, Kvp = 0.10, Dw = 0.052, Tw = 0.086, KpV = -0.11.

**Fit quality:**
- Validation open-loop replay: P RMSE about 7e-4 and Q RMSE about 1e-2 on the vref recording; P and Q RMSE about 6e-4 and 7e-3 on the load recording.
- Train residuals were about 0.010 for the vref recording, 0.017 for the fault, and 0.016 for the generator trip, against 0.0037 for the earlier vref-only fit.

**Concerns:**
- The negative Kp (Q falling with V) is physically odd and probably compensates for something the structure misses. Treat the Q-to-V sensitivity as unreliable.
- Tq (33 s) and the Dw/Tw pair are poorly identified. Dw is small and trades off against Tw. The frequency-response and droop checks will likely be weak.
- The instantaneous P and Q jumps at Vset steps are captured through Kvs and Kvp. These are reasonably identified.
- The fault and generator-trip residuals are still roughly three times the vref noise floor. The model's large-disturbance behaviour is probably wrong.
- I did not run the closed-loop grid simulation or the frequency-response and droop checks, so stability in the grid is untested.

```json
{
  "params": {"Kp": -1.0347, "Ki": 0.7616, "Tq": 33.5189, "Kvs": 1.2392, "Kvp": 0.1014, "Dw": 0.0521, "Tw": 0.0857, "KpV": -0.1093},
  "defs": {"om": "(theta-phi)/Tw"},
  "states": {
    "z": {"rhs": "Ki*(Vset-V)-z/Tq", "init": "0.0"},
    "phi": {"rhs": "(theta-phi)/Tw", "init": "theta0"}
  },
  "outputs": {
    "P": "P0+Kvp*(Vset-V0)-Dw*om+KpV*(V-V0)",
    "Q": "Q0+Kvs*(Vset-V0)-Kp*(V-V0)+z"
  }
}
```