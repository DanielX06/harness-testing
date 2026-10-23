The submission is written to `submission.json` and passes the scorer's checks: it starts at rest, and the open-loop replay runs on both validation files. P is well captured. Q is only partly captured, especially on the load recording, so treat Q as the weaker part.

**Structure (four states)**

- **Frequency proxy:** `w = (theta − xw)/Tw`, where `xw` is a washout state started at `theta0`. This estimates the angle rate, which is the grid frequency deviation.
- **Active power:** `P = zp`, a fast filter (tp ≈ 1 ms, at its lower bound) of `P0 − Kp·w + Kpv·(V − V0)`. Kp ≈ 0.045 per rad/s (about 17 pu per pu frequency), so the device acts as a droop unit.
- **Reactive power:** `Q = Q0 + K1·x1 − K2·x2`, where `x1` is a lag (≈ 6.8 s) on the voltage setpoint change and `x2` is a lag (≈ 10 s, at its upper bound) on the voltage change.
  - K1 ≈ 14.6 and K2 ≈ 15.2, so the quasi-steady dQ/dV ≈ −15 pu/pu and dQ/dVset ≈ +14.6 pu/pu.

**Fit quality (train, RMSE in pu on the 900 MVA rating)**

| Recording | P | Q |
|---|---|---|
| A_vref_op1 | 0.0014 | 0.013 |
| A_vref_op3 | 0.0006 | 0.006 |
| A_amb_op1 | 0.0003 | 0.005 |
| A_fault_op1 | 0.0021 | 0.025 |
| A_line_op3 | 0.0005 | 0.026 |
| A_gentrip_op1 | 0.0017 | 0.052 |
| A_load_op2 | 0.0002 | 0.014 |

Validation open-loop replay: P RMSE 7e-4 and 5e-4 against flat-line baselines of 6e-3 and 2e-2. Q RMSE 7.5e-3 on A_val_vref_op2 (flat 0.03) and 1.5e-2 on A_val_load_op1 (flat 0.028).

**Identification**

- **Well identified:** Kp (the frequency droop) and the P filter's near-instant behaviour. The P response to the generator trip and the staged tests is clean.
- **Moderately identified:** K1 and t1, the Vset response. The Q steps in the staged tests are well fitted.
- **Poorly identified:** the Q response to voltage excursions during events. K2 and t2 hit their bound (10 s), and K1 and K2 nearly cancel in the net low-frequency gain, so their individual values are uncertain. The fault and generator-trip Q residuals (0.025–0.05 pu) show a fast Q response to grid voltage that this model misses.
- **Tried and rejected:** adding a Q term on frequency and on P. It improved Q on the staged tests but made P worse on the generator trip and left the fault and line-trip Q residuals large. I did not carry it forward because it was inconsistent across recordings.

```json
{
  "params": {
    "Kp": 0.045111183313164556,
    "Tw": 0.10255117147524401,
    "tp": 0.001000000000014466,
    "K1": 14.59957637682261,
    "K2": 15.229362875124034,
    "t1": 6.7676509858309295,
    "t2": 9.999999999999998,
    "Kpv": -0.04538549632852165
  },
  "defs": {
    "w": "(theta-xw)/Tw",
    "Pinst": "P0-Kp*w+Kpv*(V-V0)"
  },
  "states": {
    "xw": {"rhs": "w", "init": "theta0"},
    "zp": {"rhs": "(Pinst-zp)/tp", "init": "P0"},
    "x1": {"rhs": "((Vset-V0)-x1)/t1", "init": "0.0"},
    "x2": {"rhs": "((V-V0)-x2)/t2", "init": "0.0"}
  },
  "outputs": {
    "P": "zp",
    "Q": "Q0+K1*x1-K2*x2"
  }
}
```