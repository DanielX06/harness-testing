I've written and checked a submission with six states. It passes the checker on both validation files: it starts at rest, and in open-loop replay its error is roughly 4–36 times smaller than a model whose output never moves. The active power (P) part is solid. The reactive power (Q) part is only partly right: it fits the voltage-setpoint tests well but misses part of Q's response after network events.

**Model**
- Frequency estimate: xt' = (θ − xt)/Tw, with xt(0) = θ0. The frequency deviation is ω = (θ − xt)/Tw, in rad/s.
- Active power with frequency droop: Pf' = (P0 − Kf·ω/377 − Pf)/Tp, and **P = Pf**.
- Measured voltage filter: vf' = (V − vf)/Tv.
- Reactive power filter: qf' = (Q − qf)/Tv.
- Voltage error with reactive droop: e = Vset − vf − mq·(qf − Q0).
- Proportional-integral voltage control: x' = Ki·e, and bf' = (x + Kpv·e − bf)/Tb, with x and bf both starting at Q0/V0².
- **Q = V²·bf**. This explains the instant drop in Q when V sags.
- Steady-state droops: dP/dω is about −17 pu per pu of frequency (a 5.9% droop). dQ/dV is about −1/mq, roughly −29 pu/pu, so the device holds V a little below Vset as Q rises.

**Fit results (open-loop replay; error as a share of how much P or Q actually varies)**
- **P:** errors were 4–14% of P's variation on most recordings. The fault recording was worse, at about 50%.
- **Q:** errors were about 21% on the voltage-setpoint tests, including the validation one, and 37–49% on the generator trip and validation load change. They were worse on the fault, line-trip and load-step recordings (about 0.9–1.6 times Q's variation). Q's response after events stays partly unexplained.

**How well each parameter is identified**
- **Well identified:**
  - Kf = 17.0, consistent with the generator-trip steady state.
  - mq = 0.0346, consistent across the setpoint tests, the line trip and the generator trip.
  - Tp ≈ 0.11 s.
- **Fair:** Ki ≈ 1.05 and Kpv ≈ 0.61. They trade off against each other and against Tv.
- **Poor:**
  - Tv ≈ 2.5 s. I made it shared by both the voltage and Q filters as a simplification.
  - Tb ≈ 0.055 s.
  - The V² exponent on Q was not fitted; it is a judgement from the instant Q drop.
  - Tw: the fit wanted about 5 ms, but I set 10 ms for numerical robustness in the grid simulation.

**Candidates I rejected**
- **Simple lag droop on Q:** Q following Kq·(Vset − V) through a lag. Its fitted lag ran to the 5 s limit and its Q fit was poor.
- **Grid-forming source behind a reactance:** P was fine, but the fitted reactance ran to its limit (1 pu) and Q was worse.
- **Same structure without the inner lag:** a worse fit to the voltage-setpoint tests.

```json
{"params":{"Kf":17.0245811,"Tw":0.01,"Tp":0.108137,"Ki":1.0476944,"Kpv":0.6068853,"mq":0.0345618,"Tv":2.4594704,"Tb":0.0545425,"wb":376.99111843},
"defs":{"w":"(theta-xt)/Tw","e":"Vset-vf-mq*(qf-Q0)","Qo":"V**2*bf"},
"states":{"xt":{"rhs":"(theta-xt)/Tw","init":"theta0"},
"pf":{"rhs":"(P0-Kf*w/wb-pf)/Tp","init":"P0"},
"x":{"rhs":"Ki*e","init":"Q0/V0**2"},
"bf":{"rhs":"(x+Kpv*e-bf)/Tb","init":"Q0/V0**2"},
"vf":{"rhs":"(V-vf)/Tv","init":"V0"},
"qf":{"rhs":"(Qo-qf)/Tv","init":"Q0"}},
"outputs":{"P":"pf","Q":"Qo"}}
```