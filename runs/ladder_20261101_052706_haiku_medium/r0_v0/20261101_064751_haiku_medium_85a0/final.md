The P path is a well-identified droop model. The Q path is a black-box linear fit that replays well on the setpoint tests but only partly on the disturbances, and I did not get a physically clean Q law.

**P (active power).** The device's own frequency droop, with frequency taken from a fast washout of θ:
- ω_f = (θ − xw)/(Tw·2π·60), with xw′ = (θ − xw)/Tw, xw(0) = θ0 and Tw ≈ 3.1 ms, so ω_f is effectively dθ/dt.
- xp′ = (−Kp·ω_f − xp)/Tp, with Kp ≈ 17.0 pu/pu and Tp ≈ 30 ms.
- P = P0 + xp + a·(V − V0), with a ≈ −0.035.

Kp and Tp are well identified: P replays at 3e-4 to 1.4e-3 RMSE on ambient, load-step and trip recordings. The small V coefficient a is weakly identified.

**Q (reactive power).** A 3-state linear state-space model in (Vset − V0) and (V − V0), with output Q = Q0 + C·x + D1·(Vset − V0) + D2·(V − V0).
- Its steady gains are about +28 on Vset and −28 on V, which corresponds to a strong voltage droop. The slow pole (about 0.045/s) and the individual A, B, C entries are poorly identified and trade off against each other.
- Setpoint steps and validation load and setpoint replays come out at 2–4e-3 RMSE, against a flat baseline of 0.03.
- Fault and line-trip replays are essentially no better than flat (Q RMSE 0.023 and 0.026 vs 0.026 and 0.031). The fast, large-signal Q dynamics during faults are not captured.
- Rejected candidates: a single-lag Q law with a direct V term (the V coefficient came out positive, which I attributed to network reverse-causation, so it would destabilise the loop); a 2-state linear fit (fails the trip at 0.10 RMSE); and a Vset/V filter structure (0.0064 on the setpoint tests).
- Closed-loop check: under a crude Thevenin coupling (X ≈ 0.34), the 3-state Q model settles to the observed plateau without oscillating. This is not the scorer's grid, so it is only a sanity check.

**Frequency-response and droop checks.** The P droop is credible. The Q steady droop is uncertain because its sign and size come from a fit whose split between Vset and V gains is not well determined.

```json
{"params": {"A11": 0.26646906718734403, "A12": -0.43000661211803753, "A13": 0.043214754491217755, "A21": 0.4434252253238506, "A22": -0.5753967776177265, "A23": 0.37495140857907333, "A31": 0.13371269545397033, "A32": -0.5442460857037702, "A33": -1.4136854091089759, "B11": -0.9730838088132389, "B12": 0.3520796017738819, "B21": 0.1702495727054335, "B22": -1.0416441585109812, "B31": 0.1580351121121606, "B32": -1.4808835945312393, "C1": -0.38997214436884253, "C2": -0.0015994665186760864, "C3": 1.5088908455047976, "D1": 1.384307075645816, "D2": 1.0111122119622864, "Tw": 0.00309, "Tp": 0.02988, "Kp": 16.98676, "a": -0.03521, "W": 376.99111843077515}, "defs": {}, "states": {"x1": {"rhs": "A11*x1 + A12*x2 + A13*x3 + B11*(Vset-V0) + B12*(V-V0)", "init": "0.0"}, "x2": {"rhs": "A21*x1 + A22*x2 + A23*x3 + B21*(Vset-V0) + B22*(V-V0)", "init": "0.0"}, "x3": {"rhs": "A31*x1 + A32*x2 + A33*x3 + B31*(Vset-V0) + B32*(V-V0)", "init": "0.0"}, "xw": {"rhs": "(theta-xw)/Tw", "init": "theta0"}, "xp": {"rhs": "(-Kp*(theta-xw)/(Tw*W)-xp)/Tp", "init": "0.0"}}, "outputs": {"P": "P0+xp+a*(V-V0)", "Q": "Q0+C1*x1+C2*x2+C3*x3+D1*(Vset-V0)+D2*(V-V0)"}}
```