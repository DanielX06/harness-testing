The model is reasonable outside the fault transient, and I'm out of budget for further refinement, so I'll submit this version.

## Terminal model

The device is modelled as a P-droop path and a Q path, each with lagged filters on the inputs.

**Frequency and P path.** The frequency deviation is a fast washout of the bus angle, `wf = (θ − xt)/(Tw·ω0)`, with `xt' = (θ − xt)/Tw`. Active power follows a lagged droop:
`xP' = (P0 − Kp·wf − xP)/Tpd`, and `P = xP`.

**Q path.** Five states in total. Three are first-order filters: `x1` on V, `x2` on Vset, and `x3` on P. The raw reactive power is
`Qraw = Q0 + k1(V−V0) + k2(x1−V0) + k3(Vset−V0) + k4(x2−V0) + k5(xP−P0) + k6(x3−P0)`,
and `Q = clamp(Qraw, −0.5, 0.75)`. The clamp is a safety choice, not a fitted feature.

At t = 0 every state equals its input or P0, so the model starts at rest.

**Fitted values.** The steady-state Q sensitivities are about −30 pu per pu of V (k1+k2) and about +29 pu per pu of Vset (k3+k4). Active-power droop is about 17 pu on the device base.

## Identifiability

- **Kp ≈ 17.0**: well identified. The P channel fits to about 8e-4 RMS across all training recordings.
- **Tpd, Tw ≈ 0.017 s**: pinned at the fast limit. They are only bounded by the sampling, so they are poorly identified. The fault recording shows that this fast angle-derivative path is the weakest part of the model.
- **t1, t2 ≈ 7 s and k2, k4**: the slow V and Vset filters trade off strongly with each other and with the fast terms k1 and k3. Their net steady gains (k1+k2, k3+k4) are well determined, but their split is not.
- **t3, k5, k6**: weakly identified, since k5 and k6 nearly cancel.

## Checks

- Validation replay: P RMSE ≈ 6e-4 and Q RMSE ≈ 4–6e-3 on both files, against flat-line errors of 0.03.
- The generator-trip recording replays well (Q RMSE 0.011 against a flat-line 0.097).
- The fault recording is the weakest case. Q follows the transient only roughly and the replay error is about 0.025 Q RMSE. The steady-state tail tracks well.

I did not run a closed-loop simulation of the grid, so stability in the scorer's network is untested. The slow Q filter and the modest loop gain should keep it stable, but that is an assumption.

```json
{
  "params": {
    "Kp": 17.011442687068985,
    "Tpd": 0.017013790202596104,
    "Tw": 0.017000634072672254,
    "t1": 7.377955249239211,
    "t2": 6.980983240726465,
    "t3": 4.957729819731902,
    "k1": 1.1290770627615494,
    "k2": -31.119689639328804,
    "k3": 2.8817887375179208,
    "k4": 26.351525164087192,
    "k5": -3.695929172547877,
    "k6": 3.4864459815588185,
    "w0": 376.99111843077515,
    "Qlo": -0.5,
    "Qhi": 0.75
  },
  "defs": {
    "wf": "(theta-xt)/(Tw*w0)",
    "Qraw": "Q0+k1*(V-V0)+k2*(x1-V0)+k3*(Vset-V0)+k4*(x2-V0)+k5*(xP-P0)+k6*(x3-P0)"
  },
  "states": {
    "xt": {"rhs": "(theta-xt)/Tw", "init": "theta0"},
    "xP": {"rhs": "(P0-Kp*wf-xP)/Tpd", "init": "P0"},
    "x1": {"rhs": "(V-x1)/t1", "init": "V0"},
    "x2": {"rhs": "(Vset-x2)/t2", "init": "V0"},
    "x3": {"rhs": "(xP-x3)/t3", "init": "P0"}
  },
  "outputs": {
    "P": "xP",
    "Q": "Min(Max(Qraw,Qlo),Qhi)"
  }
}
```