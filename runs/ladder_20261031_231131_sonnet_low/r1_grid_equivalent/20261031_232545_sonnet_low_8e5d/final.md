I fitted a simple two-channel terminal model on train/. In the grid-equivalent replay on the two validation recordings it cut the P and Q errors well below the "flat" (never-moving) baseline. I did not run `check_submission.py`, but both replays ran, so the model parses. I also didn't run the grid-equivalent replay on any fault recording.

**Equations** (ω is the frequency deviation in pu, with 377 rad/s as nominal):
- Frequency estimate: dx/dt = (θ − θ0 − x)/Tw, and ω = (θ − θ0 − x)/(Tw·377). This is a filtered derivative of the bus angle.
- Active power: P = P0 − kp·ω. This is active-power droop on frequency.
- Reactive power state: dq/dt = (a1·(Vset − V0) + b1·(V − V0) − q)/Tq.
- Reactive power output: Q = Q0 + q + c1·(V − V0) + kw·ω.

Both states start at 0, so the model is at rest at t = 0 with P = P0 and Q = Q0.

**Validation (grid-equivalent replay, RMSE in pu, flat baseline in brackets):**

| Recording | P | Q |
|---|---|---|
| `A_val_vref_op2` | 2.4e-3 (5.9e-3) | 5.4e-3 (2.95e-2) |
| `A_val_load_op1` | 5.6e-3 (2.35e-2) | 8.8e-3 (2.76e-2) |

**Parameter identification:**
- **Well identified:**
  - kp ≈ 17.4 gives the P droop. It is driven by the large angle drift in the generator-trip recording.
  - The Vset → Q path (a1 ≈ 1.88 with Tq ≈ 0.30 s) is clear in the staged voltage-reference tests.
- **Poorly identified:**
  - Tw ≈ 1.7 s is a slow filter, and the fit is not sharp about it.
  - kw ≈ −17 is large and nearly equal and opposite to kp. It probably compensates for something the model lacks, so it is an empirical term rather than a physical one.
  - b1 and c1 trade off against each other. Their sum is what matters (about 0.16 pu Q per pu V), because b1 enters through the filter and c1 acts directly. The Q fit on the generator-trip and line-outage recordings is the weakest, and I did not resolve it.

```json
{"params": {"kp": 17.40203721, "Tw": 1.73717755, "a1": 1.88078463, "b1": -1.06019373, "c1": 1.22065565, "Tq": 0.29767566, "kw": -16.95565534}, "defs": {"w": "(theta-theta0-x)/Tw/377"}, "states": {"x": {"rhs": "(theta-theta0-x)/Tw", "init": "0"}, "q": {"rhs": "(a1*(Vset-V0)+b1*(V-V0)-q)/Tq", "init": "0"}}, "outputs": {"P": "P0-kp*w", "Q": "Q0+q+c1*(V-V0)+kw*w"}}
```