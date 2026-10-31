I've written a terminal model to `submission.json`. It passes the checker on all five files I ran (both validation files plus the train fault, gentrip and line files): it starts at rest and replays open loop without failing. P is reproduced very well. Q is noticeably weaker, and part of the Q model is a data-driven fit I couldn't explain physically.

**Open-loop replay (error / error of a flat model):**

| File | P | Q |
|---|---|---|
| val load_op1 | 2.4e-4 / 2.35e-2 | 2.5e-3 / 2.76e-2 |
| val vref_op2 | 2.4e-4 / 5.85e-3 | 7.6e-3 / 2.95e-2 |
| train gentrip | 5.0e-4 / 9.4e-2 | 5.7e-3 / 9.7e-2 |
| train line_op3 | 3.3e-4 / 9.2e-3 | 9.6e-3 / 3.1e-2 |
| train fault | 1.9e-3 / 5.5e-3 | 1.0e-2 / 2.6e-2 |

The Q error on val vref_op2 is about a quarter of the flat-model error, and it's worst on the fault and on events at the other operating points.

I could only test stability closed loop in a crude way: the device connected to a fixed-voltage source through a reactance. It stayed stable for reactances from 0.1 to 0.6 pu on its 900 MVA base. At 0.8 pu and above that test went unstable, but the steady-state solve wasn't converging there, so I can't say whether the model or the operating point is at fault. I haven't tested it against a grid with generator inertia.

**Structure.** It behaves like a grid-following unit: a phase-locked loop (PLL) estimates the bus frequency, which drives P through a droop, and Q comes from a slow voltage loop. In the equations below, Δx means x minus its value at t = 0, and L(u,T) is a first-order lag with time constant T (one state each).

**PLL:**
- ε = θ − θp
- dθp/dt = ω0·ωp, where ωp = kpp·ε + xi and dxi/dt = kip·ε
- frequency filter: dwf/dt = (ωp − wf)/Tf

**Active power:**

Pu = P0 − Kp·wf + cPe·ε + cPV·ΔV + cPVm·ΔVm + cPS·ΔVset + cPSf·ΔVsf

where Vm = L(V,Tv) and Vsf = L(Vset,Tv).

**Reactive power:**

Qu = Q0 + (Q0/V0)·ΔV + P0·ε + Kqs·s1 + Kqff·(a1 − a2) + Kqv·(v1 − V0) + Kqe·e1 + Kqw·(l1 − l2) + Kqwdc·l3

where:
- s1 = L(Vset − Vq, Ts), with Vq = L(V, Tm)
- a1 = L(Vset, Ta) and a2 = L(Vset, Ts)
- v1 = L(V, Tvq)
- e1 = L(ε, Te)
- l1 = L(ωp, Tw1), l2 = L(l1, Tw2) and l3 = L(ωp, Tw2)

The fast terms (Q0/V0)·ΔV and P0·ε are fixed by physics rather than fitted. I fixed them deliberately: a freely fitted fast dQ/dV came out at about +1.4, which closed loop would act as positive feedback and could destabilise a weak grid.

**Output:** P = k·Pu and Q = k·Qu, with k = Min(1, Imax·V/|Su|) and |Su| = √(Pu² + Qu²). Imax = 1.2 is my assumption, added only to keep faults bounded; the limiter never engages in any recording.

**Steady-state droops:** dP/dω = −16.9 (about 5.9 % droop) and dQ/dV = −23.4.

**How well each parameter is pinned down**
- **Well identified:**
  - Kp ≈ 16.9.
  - The P coupling to Vset and V: a fast +0.61·ΔVset that decays with Tv ≈ 0.14 s, and dP/dV ≈ 0.21 that becomes −0.15 in steady state.
  - The slow Q loop: gain Kqs ≈ 23.8, Ts ≈ 2.9 s.
  - The steady-state dQ/dV.
- **Moderately identified:** the PLL gains (kpp ≈ 0.043, kip ≈ 1.09). These trade off against Tf.
- **Poorly identified:**
  - The Q response to frequency transients (Kqw = 148 with Tw1 ≈ 0.64 s and Tw2 ≈ 2.2 s; Kqwdc). Every fit wants it, and it is what lets the gentrip and line-trip recordings fit, but I can't explain it physically. It also makes val vref_op2 worse: about 0.008 against 0.002–0.003 for versions without it. So it may not carry over to a different operating point.
  - Ta and Kqff (a fast path from the setpoint into Q), Tm against Ts, Kqe/Te, and Tvq/Kqv. These are roughly interchangeable with each other.
- **Not identified:** Imax.

**What I tried and dropped**
- A grid-forming model (a voltage source behind a virtual reactance): it fitted P and Q much worse.
- A standard voltage loop on terminal V (proportional-integral control with droop and filters): Q error came out at about 0.01, as bad as or worse than a flat model.
- Fully flexible banks of filters: they overfit, with huge cancelling slow coefficients and implausible steady-state gains.
- There are hints that the true Q loop regulates a compensated voltage on the high side of the step-up transformer (bus 9). Steady-state gains are consistent with that, but I couldn't make its dynamics fit, so it isn't in the model.

```json
{
 "params": {
  "W0": 376.99111843077515,
  "kpp": 0.04294851508,
  "kip": 1.09251245,
  "Tf": 0.172942185,
  "Tv": 0.13793962,
  "Kp": 16.92075998,
  "cPe": -0.29162242,
  "cPV": 0.21198431,
  "cPVm": -0.36165931,
  "cPS": 0.60627978,
  "cPSf": -0.46970695,
  "Ts": 2.9067529,
  "Ta": 0.77462467,
  "Tm": 0.51419362,
  "Tvq": 0.01492755,
  "Te": 1.89433861,
  "Tw1": 0.63523023,
  "Tw2": 2.15985752,
  "Kqs": 23.77188417,
  "Kqff": 3.55629376,
  "Kqv": 0.22507345,
  "Kqe": -6.2614001,
  "Kqw": 148.06453448,
  "Kqwdc": -1.4875963,
  "Imax": 1.2
 },
 "defs": {
  "eps": "theta - thp",
  "wp": "kpp*eps + xi",
  "Pu": "P0 - Kp*wf + cPe*eps + cPV*(V - V0) + cPVm*(Vm - V0) + cPS*(Vset - V0) + cPSf*(Vsf - V0)",
  "Qu": "Q0 + (Q0/V0)*(V - V0) + P0*eps + Kqs*s1 + Kqff*(a1 - a2) + Kqv*(v1 - V0) + Kqe*e1 + Kqw*(l1 - l2) + Kqwdc*l3",
  "Su": "sqrt(Pu**2 + Qu**2) + 1e-9",
  "klim": "Min(1, Imax*V/Su)"
 },
 "states": {
  "thp": {"rhs": "W0*wp", "init": "theta0"},
  "xi": {"rhs": "kip*eps", "init": "0"},
  "wf": {"rhs": "(wp - wf)/Tf", "init": "0"},
  "Vm": {"rhs": "(V - Vm)/Tv", "init": "V0"},
  "Vsf": {"rhs": "(Vset - Vsf)/Tv", "init": "V0"},
  "Vq": {"rhs": "(V - Vq)/Tm", "init": "V0"},
  "s1": {"rhs": "((Vset - Vq) - s1)/Ts", "init": "0"},
  "a1": {"rhs": "(Vset - a1)/Ta", "init": "V0"},
  "a2": {"rhs": "(Vset - a2)/Ts", "init": "V0"},
  "v1": {"rhs": "(V - v1)/Tvq", "init": "V0"},
  "e1": {"rhs": "(eps - e1)/Te", "init": "0"},
  "l1": {"rhs": "(wp - l1)/Tw1", "init": "0"},
  "l2": {"rhs": "(l1 - l2)/Tw2", "init": "0"},
  "l3": {"rhs": "(wp - l3)/Tw2", "init": "0"}
 },
 "outputs": {"P": "klim*Pu", "Q": "klim*Qu"}
}
```