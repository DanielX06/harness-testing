I fitted a grid-following (current-source) model with 9 states. The active power P is very well captured, and the steady droops are clear. The reactive power Q is only partly captured: it is the weak part of the model.

**Why grid-following:** at the fault I back-calculated an internal voltage behind a reactance. Its angle jumps about 0.2 rad with the bus angle for every reactance I tried, so a voltage-source (grid-forming) model doesn't fit.

**Open-loop replay on validation (model error vs. a model whose output never moves):**

| Recording | P error | Q error |
|---|---|---|
| A_val_load_op1 | 4.1e-4 vs 2.35e-2 | 3.4e-3 vs 2.76e-2 |
| A_val_vref_op2 | 2.2e-4 vs 5.9e-3 | 4.2e-3 vs 2.95e-2 |

On training, P error is 2–7e-4 except the fault (2.5e-3) and generator trip (1.3e-3). Q error is 1.1–8e-3, and up to 0.6 of the never-moving baseline on the op2 ambient recording. The checker found the model at rest at t=0 on both validation files.

## Equations
Angles are in rad, ωb = 377 rad/s, and P and Q are in pu on 900 MVA.

**Active power (fast PLL with frequency droop):**
- e_f = Dm·tanh((θ − θp)/Dm)
- θp' = kp·e_f + ξ
- ξ' = ki·e_f
- ω̂ = (kp·e_f + ξ)/ωb
- v_h' = (V − v_h)/Th
- vs_h' = (Vset − vs_h)/Th
- **P = P0 − Kf·ω̂ + cth·e_f + aV·(V − v_h) + aS·(Vset − vs_h)**

**Reactive power (slow voltage droop, slow angle term, low-voltage boost):**
- Slow angle tracker: Δs = θ − θq, with θq' = kpq·Δs + xq and xq' = kiq·Δs
- Filtered voltage: v_m' = (V − v_m)/Tv
- Droop lag: x_c' = ((Vset − v_m) − x_c)/Tc
- Fast voltage term: v_h2' = (V − v_h2)/Thq
- a1e = clip(a1 + a11·P0, −1.5, 0.9)
- **Q = Q0 + Kq·x_c + Kpq·(Vset − v_m) + (k0 + k1·P0)·Δs + a1e·(V − v_h2) + Kd·max(0, Vd − V)**

Steady state, with V, θ and Vset held:
- dP/dω = −Kf ≈ −17.0 pu/pu, which is about a 5.9% frequency droop.
- dQ/dV = −(Kq + Kpq) ≈ −26.3, which is about a 3.8% voltage droop.

## How well each parameter is identified
- **Well identified:**
  - **Kf = 17.01:** consistent across every recording and steady state.
  - **Kq + Kpq ≈ 25–26:** consistent across all my Q fits.
  - **Th ≈ 0.046 s, aS ≈ 0.79 and aV ≈ 0.45:** these give the brief P blip when the setpoint steps.
- **Moderately identified:**
  - **Fast PLL gains (kp ≈ 42, ki ≈ 430):** the pair trades off against cth.
  - **Tc ≈ 2.7 s, Tv ≈ 0.8 s and the slow tracker poles (≈ 0.46 and 1.3 rad/s):** these trade off against each other.
- **Poorly identified:**
  - **P0-dependent fast Q–V coefficient (a1, a11):** I only had two dispatch levels (P0 = 0.78 and 0.5). Its value is about +0.8 at op1 and about −1 at op2, so I clipped it to [−1.5, 0.9].
  - **k1:** close to zero.
  - **PLL error limit Dm = 0.03, low-voltage boost Kd = 2.5 and Vd = 0.92:** each was set from the single fault recording.

## Limitations and risks
- **Q is the weak part.** No linear model of V, Vset and θ that I tried carried over across recordings for Q. That points to nonlinear or operating-point-dependent behaviour I couldn't pin down.
- **Rejected models:** a plain voltage PI or lag, a remote-voltage or line-drop-compensated controller, a PLL-frame voltage V·cos(Δ), and fully black-box fits. All of them fitted single recordings but failed on others.
- **During faults:** Q is poorly reproduced inside the 100 ms of the fault. Q after clearing is captured well.
- **Weak grids:** I checked stability with the model on a simple source-behind-reactance grid. It is stable for reactance up to 0.6 pu at any dispatch I tried. It goes unstable at about 0.8–1.0 pu when P0 is 0.78 or higher, through the fast positive Q–V term. For reference, the measured dV/dQ suggests the real network is about 0.45 pu. The real device also oscillates lightly at about 1 Hz after the generator trip, so it may be near a similar margin.

```json
{"params": {"Kf": 17.00895114132334, "kp": 42.301216685529894, "ki": 428.689356668245, "cth": 0.9043279809771164, "aV": 0.4464134589423551, "aS": 0.7925271919052219, "Th": 0.046131289979696885, "kpq": 1.7348435638523603, "kiq": 0.5868372161104168, "k0": 0.5760297474277033, "Kq": 25.805777611287297, "Tc": 2.728171313265318, "Tv": 0.7727057940757689, "Kpq": 0.46236528419463147, "a1": -4.2607395748483246, "Thq": 4.860898630274181, "wb": 376.99111843077515, "Dm": 0.03, "Kd": 2.5, "Vd": 0.92, "k1": -0.024020017713951132, "a11": 6.497080020219277, "a1min": -1.5, "a1max": 0.9}, "defs": {"dlf": "theta - thp", "ef": "Dm*tanh(dlf/Dm)", "wpll": "(kp*ef + xi)/wb", "dls": "theta - thq", "a1e": "Min(Max(a1 + a11*P0, a1min), a1max)"}, "states": {"thp": {"rhs": "kp*ef + xi", "init": "theta0"}, "xi": {"rhs": "ki*ef", "init": "0"}, "vh": {"rhs": "(V - vh)/Th", "init": "V0"}, "vsh": {"rhs": "(Vset - vsh)/Th", "init": "V0"}, "thq": {"rhs": "kpq*dls + xq", "init": "theta0"}, "xq": {"rhs": "kiq*dls", "init": "0"}, "vm": {"rhs": "(V - vm)/Tv", "init": "V0"}, "xc": {"rhs": "((Vset - vm) - xc)/Tc", "init": "0"}, "vh2": {"rhs": "(V - vh2)/Thq", "init": "V0"}}, "outputs": {"P": "P0 - Kf*wpll + cth*ef + aV*(V - vh) + aS*(Vset - vsh)", "Q": "Q0 + Kq*xc + Kpq*(Vset - vm) + (k0 + k1*P0)*dls + a1e*(V - vh2) + Kd*Max(0, Vd - V)"}}
```