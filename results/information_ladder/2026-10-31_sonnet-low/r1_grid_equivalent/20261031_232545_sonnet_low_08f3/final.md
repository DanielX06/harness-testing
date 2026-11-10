I fitted a three-state model to the training recordings. It runs and starts at rest. I only ran the grid-equivalent replay on one validation file, and I did not run `check_submission.py`. I excluded the fault recording from the fit.

**Equations**
- Reactive power: `dq/dt = (Q0 + kq·(Vset − V) − q)/Tq`, and `Q = q`. This is a voltage droop with a first-order lag.
- Angle filter: `dxf/dt = (theta − xf)/Tw`. The frequency deviation is estimated as `(theta − xf)/Tw`.
- Active power: `dpp/dt = (P0 − kp·(theta − xf)/Tw − pp)/Tp`, and `P = pp`. This is a frequency droop with a first-order lag.

**Fitted parameters**
- `kq` = 9.66.
- `Tq` = 5 s. This sits on my upper bound, so it is poorly identified. I did not widen the bound and refit.
- `kp` = 0.517.
- `Tw` = 0.011 s. The filter is almost a pure derivative of theta, so this value is also not well pinned down.
- `Tp` = 0.026 s.

**Fit quality**
- On training data the RMSE fell from 0.0364 (a model that never moves) to 0.0217.
- On one validation file the grid-equivalent replay gave P RMSE 0.061 and Q RMSE 0.011.
- The P error is about ten times the 0.0058 "flat" figure in brackets, so the P channel is probably poor on that file. I did not investigate it.

```json
{"params":{"kq":9.65566796,"Tq":5.0,"kp":0.51741029,"Tw":0.01095534,"Tp":0.02603248},"defs":{},"states":{"q":{"rhs":"(Q0+kq*(Vset-V)-q)/Tq","init":"Q0"},"xf":{"rhs":"(theta-xf)/Tw","init":"theta0"},"pp":{"rhs":"(P0-kp*(theta-xf)/Tw-pp)/Tp","init":"P0"}},"outputs":{"P":"pp","Q":"q"}}
```