I have a 6-state model with 13 parameters. The active-power side fits closely and I trust it. The reactive-power side is only partly right: replay misses on the line trip and the fault, and part of the Q model is a guess I couldn't confirm.

**Equations** (pu on 900 MVA; ωb = 2π·60)

Phase-locked loop (PLL) that tracks the bus angle, plus frequency droop on P:
- e = sin(θ − θp)
- ωp = Kpp·e + xi
- dθp/dt = ωb·ωp (starts at θ0)
- dxi/dt = Kpi·e
- dwf/dt = (ωp − wf)/Tf
- dys/dt = (Vset − V0 − ys)/Tps
- Pu = P0 − Kp·wf + Kps·(Vset − V0 − ys)

Reactive power from droop voltage control, a setpoint feedforward and a frame-rotation term:
- dxq/dt = Ki·(Vset − V − mq·(Qu − Q0))
- dxf/dt = (Kff·(Vset − V0) − xf)/Tff
- Qu = V·(Q0/V0 + xq + xf) + Kr·e

Current limit (my assumption, see below): P = Pu·lim and Q = Qu·lim, with lim = min(1, Imax·V/|Pu + jQu|).

Every state starts at rest, so the model sits exactly at (P0, Q0) at any operating point. The steady droops are dP/dω = −17 and, with Vset held, dQ/dV = −1/mq ≈ −29.

**How it checks out**
- **P:** open-loop replay error on ambient and validation files is 2–6×10⁻⁴, against 6×10⁻³ to 2.4×10⁻² for an output that never moves. On the fault and generator trip it is about 2–3×10⁻³.
- **Q, validation:** error is 6.4×10⁻³ on the load change (flat 2.8×10⁻²) and 2.9×10⁻³ on the voltage-reference test (flat 3.0×10⁻²).
- **Q, training events:** the generator trip is about 1.7×10⁻², against a spread of about 4×10⁻². The fault is about 2.0×10⁻², against about 2.5×10⁻². The line trip is about 2.5×10⁻², which is **worse than a flat output** (about 1.6×10⁻²). In that recording Q keeps rising while V is above setpoint, and this model can't reproduce that.
- **Closed loop:** I coupled the model to a simple equivalent grid (a source behind a reactance plus one swing-equation machine). It was stable for grid reactance 0.2–0.4 pu on the device base; that range brackets the ~0.4 the voltage-reference steps imply. At 0.8 pu it misbehaved, but my crude network solver may be the cause there.
- `tools/check_submission.py` passes on both validation files and the fault file, with zero residual at t = 0.

**Parameters: how well each is identified**
- **Well identified:**
  - Kp = 17.0, the frequency droop. Steady ΔP/Δω is −17.0 in every event.
  - Kpp ≈ 0.027 and Tf ≈ 2 ms. Together these give the instant P response to an angle step (about −0.46 per rad) and its ~0.1 s recovery.
  - Kps ≈ 0.69 and Tps ≈ 0.12 s. These cover the instant P jump of about 0.63×ΔVset at voltage-reference steps.
  - Kff ≈ 2.4 and Tff ≈ 0.06 s, which cover the fast Q rise after Vset steps.
- **Moderately identified:**
  - mq ≈ 0.035. Steady states put it at 0.03–0.045, but slow voltage wander in the ambient data makes it noisy.
  - Kr ≈ 0.63, the angle-to-Q term. It is consistent with the 0.3–3 Hz response seen in the data.
- **Poorly identified:**
  - Kpi only sets slow drift and can't be separated from Kpp using P alone.
  - Ki ≈ 0.9 trades off against mq and Kff.
  - Imax = 1.2 is assumed, not identified. No recording drives the current near a limit; I added it only so a deep fault doesn't demand unrealistic current.

**What I rejected and why**
- **Voltage source behind an impedance:** it can't match both the weak P-angle coupling and the strong slow Q-voltage behaviour at once.
- **High-gain voltage integrators:** they predicted far more Q swing in the ambient recordings than the data shows.
- **A linear black-box Q model:** it replayed better, but its Q response to V was positive at 0.1–1 Hz, an artefact of V following Q through the grid. It went unstable in the closed-loop test.

The data suggest Q also depends on the device's internal angle, which is the integral of its own P. Capturing that properly would probably fix the line-trip miss, but I didn't get it to replay reliably.

```json
{
 "params": {
  "Kpp": 0.026946806452816132,
  "Kpi": 0.01593751744955606,
  "Tf": 0.0021388004427806587,
  "Kp": 17.0,
  "Kps": 0.6877355449152021,
  "Tps": 0.11757698568960802,
  "wb": 376.99111843077515,
  "Ki": 0.9331203015367875,
  "mq": 0.034537774860851245,
  "Kff": 2.4463960243532945,
  "Tff": 0.06325215893199317,
  "Kr": 0.6293480915879452,
  "Imax": 1.2
 },
 "defs": {
  "e": "sin(theta - thp)",
  "wp": "Kpp*e + xi",
  "Pu": "P0 - Kp*wf + Kps*(Vset - V0 - ys)",
  "Qu": "V*(Q0/V0 + xq + xf) + Kr*e",
  "lim": "Min(1.0, Imax*V/sqrt(Pu**2 + Qu**2 + 1e-9))",
  "Pout": "Pu*lim",
  "Qout": "Qu*lim"
 },
 "states": {
  "thp": {"rhs": "wb*wp", "init": "theta0"},
  "xi": {"rhs": "Kpi*e", "init": "0"},
  "wf": {"rhs": "(wp - wf)/Tf", "init": "0"},
  "ys": {"rhs": "(Vset - V0 - ys)/Tps", "init": "0"},
  "xq": {"rhs": "Ki*(Vset - V - mq*(Qu - Q0))", "init": "0"},
  "xf": {"rhs": "(Kff*(Vset - V0) - xf)/Tff", "init": "0"}
 },
 "outputs": {"P": "Pout", "Q": "Qout"}
}
```