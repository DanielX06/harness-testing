I fitted a model for the device's terminal behaviour. It passes the checker on both validation recordings, with open-loop replay errors of about 5e-4 to 7e-4 pu in P and 3e-3 to 6e-3 pu in Q. I did not run a closed-loop grid simulation, so stability in the scorer's grid is untested.

**Structure**

- **Active power:** P = P0 − 0.0464·ΔV + y. The state y is a first-order lag (Tp ≈ 0.10 s) driven by −Kp·ω, where ω = dθ/dt/(2π·60) is taken from a θ washout with Tw ≈ 3.7 ms. Kp ≈ 17 pu/pu gives a frequency droop of about 5.9%. This is the best-identified part of the model, with residuals 2e-4 to 3e-3 pu across all recordings.
- **Reactive power:** Q = Q0 + d·ΔV + e·ΔVset + x. Here d ≈ +0.64 and e ≈ +0.20 are instantaneous. The state x is a lag (Tq ≈ 30 s) driven by a·(vf − V0) + b·ΔVset, with a ≈ −32.7, b ≈ +30.8, and vf is V filtered with Tm ≈ 2.2 s. The steady-state droop is dQ/dV ≈ −32 and dQ/dVset ≈ +31, which agrees with the quasi-steady equilibrium points in the staged tests.

**Identification quality**

- Well identified: Kp, Tp, and p1 (P model), and the steady droop combination a + d and b + e, which is pinned by the staged tests.
- Poorly identified: Tq (somewhere around 20–30 s; the fit pushed toward slow values), the split between a and d, and the split between b and e. The instantaneous and lagged V paths trade off against each other.
- Not captured: the line-trip recording leaves a persistent Q offset of about 0.03 pu that decays over tens of seconds. P, frequency, and angle terms did not remove it, so it likely depends on remote network state I could not observe. The fault and generator-trip residuals are about 0.02 pu in Q.
- Risk: the 30 s Q lag with a −32 pu/pu steady droop is a strong slow loop. It is damped by the 2.2 s V filter, but I did not test it closed-loop in the scorer's grid. The Q model also has no θ or frequency dependence, so its frequency response relies on the P path alone.

```json
{
  "params": {
    "d": 0.639445194708263,
    "e": 0.1981825900001488,
    "a": -32.73097645145795,
    "b": 30.775974988090056,
    "Tq": 30.130536151905215,
    "Tm": 2.22570133881913,
    "Kp": 17.006,
    "Tp": 0.1032,
    "p1": -0.0464,
    "Tw": 0.0037,
    "two_pi_f": 376.99111843077515
  },
  "defs": {
    "dV": "V-V0",
    "dVs": "Vset-V0",
    "thr": "theta-theta0",
    "w": "(thr-thf)/(Tw*two_pi_f)"
  },
  "states": {
    "vf": {"rhs": "(V-vf)/Tm", "init": "V0"},
    "x": {"rhs": "(a*(vf-V0)+b*dVs-x)/Tq", "init": "0.0"},
    "thf": {"rhs": "(thr-thf)/Tw", "init": "0.0"},
    "y": {"rhs": "(-Kp*w-y)/Tp", "init": "0.0"}
  },
  "outputs": {
    "P": "P0+p1*dV+y",
    "Q": "Q0+d*dV+e*dVs+x"
  }
}
```