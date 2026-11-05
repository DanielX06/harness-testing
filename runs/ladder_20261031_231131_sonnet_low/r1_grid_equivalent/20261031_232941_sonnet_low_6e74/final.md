The model below is my final submission. In the grid-equivalent replay on the two validation files, P and Q errors are well below the flat (no-movement) errors. The one exception is V on `A_val_load_op1`, where my model's error (6.6e-3) is above the flat value (4.8e-3). I did not run `check_submission.py` on the validation files. The replay ran without errors, which suggests the file parses.

**Equations**
- Frequency estimate: `xw` is a first-order lag of θ, so ω ≈ (θ − xw)/Tw.
- Active power: `xp` is a first-order lag (time constant Tp) of −kp·ω, and P = P0 + xp. This is a pure frequency droop with no direct dependence on V.
- Reactive power: `xq` is a first-order lag (time constant Tq) of kq·(Vset − V). Then Q = Q0 + xq + kv·(V − V0).
- All states start at rest: xw = θ0, xq = 0, xp = 0, so P = P0 and Q = Q0 at t = 0.

**Parameter identification**
- **kp (0.045):** well identified from the generator-trip and load events, where the angle drifts steadily and P follows.
- **kq (5.7), Tq (3.6 s) and kv (1.6):** only moderately identified. The fit drove Tq toward very slow dynamics, and kq, Tq and kv trade off against each other. Q is the weaker fit: on the generator-trip recording the Q residual was about as large as the Q signal itself.
- **Tw and Tp (0.02 s each):** fixed by hand, not fitted. Tw is the derivative filter. The fit drove Tp to about zero, so I set it small. Their effect on the result is small.
- **P dependence on V:** I tried one and it came out near zero (−0.017), so I left it out.

```json
{"params":{"kq":5.73,"Tq":3.577,"kp":0.0451,"Tp":0.02,"Tw":0.02,"kv":1.63},"defs":{},"states":{"xw":{"rhs":"(theta-xw)/Tw","init":"theta0"},"xq":{"rhs":"(kq*(Vset-V)-xq)/Tq","init":"0"},"xp":{"rhs":"(-kp*(theta-xw)/Tw-xp)/Tp","init":"0"}},"outputs":{"P":"P0+xp","Q":"Q0+xq+kv*(V-V0)"}}
```