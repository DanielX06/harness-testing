I've written and checked a model. The active-power part fits well, but the reactive-power part is only partly right: I couldn't find the device's real voltage-control structure, so treat the Q equations as an approximation.

**Model**
- Frequency estimate: the state x_th follows theta with dx_th/dt = (theta − x_th)/Tw, and ω = (theta − x_th)/(Tw·2π·60), in pu.
- Active power: dp_f/dt = (−Kp·ω − p_f)/Tp, and P = P0 + p_f. This is a frequency droop of 17 pu/pu (about 5.9 % droop), with a lag of about 0.08 s.
- Slow voltage average: dv_s/dt = (V − v_s)/Ta.
- Reactive power: dq_f/dt = (Kq·(Vset − V) − q_f)/Tq, and Q = Q0 + a·(V − v_s) + q_f.
  - The steady-state droop is dQ/dV = −25 pu/pu, which is about 4 % voltage droop.
  - Q also moves instantly in the same direction as V, by about +1.7 pu/pu, and that term fades over tens of seconds.

All four states start at rest. The checker confirmed this on both validation files: every derivative is zero at t = 0, and P and Q start at P0 and Q0.

**How well it fits (open-loop replay on val/)**
- **P:** the error is about 0.0006 pu, against 0.006 to 0.023 pu for a model that never moves. Kp = 17.0 is well identified. Tp trades off against Tw, and only their total of about 0.1 s is pinned down.
- **Q:** the error is about 0.009 pu, against about 0.028 pu for a model that never moves. That's roughly 30 % of the flat error left over, which is not close to a perfect fit. In particular, I couldn't reproduce how Q follows V together after a setpoint step.
- **Q droop of 25:** estimated by hand from where Q and V settle after the line trip, the generator trip and the setpoint steps (a droop of about 0.04 each time), then held fixed in the fit. It is reasonably well identified.
- **Tq (about 23 s) and a, Ta:** poorly identified. Together they behave mostly like a slow integrator.

**Structures I tried and rejected**
- **Voltage source behind a reactance (grid-forming):** the implied internal voltage jumps at events for every reactance I tried, and P barely moved when the angle jumped 0.2 rad during the fault.
- **Proportional-integral voltage control with droop:** the fit failed.
- **Phase-locked-loop current-source model:** the fit came out worse; I bounded and shortened it to stay within time limits, so I didn't fully explore it.
- **Adding a frequency term to Q:** it didn't help.

I only replayed the model open-loop; I didn't run it inside the grid. I chose a slow, low-gain Q loop partly so it's less likely to destabilize the grid in closed loop.

```json
{"params":{"Kp":17.01639161,"Tp":0.07942018,"Tw":0.02,"Kq":25.0,"Tq":23.3554718,"a":1.67477801,"Ta":48.29063841},
"defs":{"w":"(theta - xth)/Tw/(2*pi*60)"},
"states":{"xth":{"rhs":"(theta - xth)/Tw","init":"theta0"},
"pf":{"rhs":"(-Kp*w - pf)/Tp","init":"0"},
"vs":{"rhs":"(V - vs)/Ta","init":"V0"},
"qf":{"rhs":"(Kq*(Vset - V) - qf)/Tq","init":"0"}},
"outputs":{"P":"P0 + pf","Q":"Q0 + a*(V - vs) + qf"}}
```