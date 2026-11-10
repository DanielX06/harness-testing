The model passes both validation checks at rest and reproduces the validation recordings reasonably well. I'm submitting it now rather than iterating further, because the remaining Q misfit is in the event recordings.

**Equations** (V, θ, Vset live; V0, θ0, P0, Q0 are the t=0 operating point):

- Q-path lag on voltage: `xv' = (V − xv)/Tf`, `dv = (V − xv)/Tf`
- Angle washouts (frequency proxies): `xwq' = (θ − xwq)/Twq`, `wq = (θ − xwq)/Twq`; `xwp' = (θ − xwp)/Twp`, `wp = (θ − xwp)/Twp`
- P-path lag: `xp' = (wp − xp)/Tp`
- **P = P0 − Dp · xp / (2π·60)**
- **Q = Q0 + A·(Vset − V0) + B·(V − V0) + C·dv + Eq·wq**

**Fitted values:** A ≈ 1.55 (setpoint gain), B ≈ 0.55 (voltage gain, positive), C ≈ −0.017, Tf ≈ 0.018 s, Eq ≈ −0.049 (frequency term on Q), Dp ≈ 17.1 (≈6% active-power droop), Twq ≈ 3.9 s, Twp ≈ 0.097 s, Tp ≈ 0.0027 s.

**Identification:**
- **Well identified:** the P droop Dp (consistent across the generator trip, the load step and ambient data) and the P dynamics. Validation P RMSE is about 6e-4 pu against a flat-line baseline of 6e-3 to 2e-2.
- **Moderately identified:** A and B. Vset and V move together in most data, so separating them relies on the staged steps.
- **Poorly identified:** C and Tf. The fast voltage-derivative term is only weakly constrained, and Tf is near the sample scale. Twq and Eq trade off against each other, and Twq is only roughly determined.
- **Structural gap:** Q is the weak channel. Validation Q RMSE is about 4–7e-3 pu against a flat baseline of about 3e-2. The line-trip and fault recordings still leave residuals of 0.02–0.04 pu, so the true Q dynamics are not fully captured by this linear form.

**Caveat:** the fitted voltage gain B is positive, which means the device raises Q as its terminal voltage rises. This is the opposite sign to a conventional reactive droop, and I have not checked the closed-loop stability of that sign in the grid.

```json
{
 "params": {
  "A": 1.5484670936211034,
  "B": 0.5454014758167234,
  "C": -0.017401312369701317,
  "Tf": 0.01794286279307398,
  "Eq": -0.04902142496996558,
  "Dp": 17.10870152030325,
  "Twq": 3.8771541275695958,
  "Twp": 0.09708655160148882,
  "Tp": 0.0026715793863525787
 },
 "defs": {
  "wq": "(theta-xwq)/Twq",
  "wp": "(theta-xwp)/Twp",
  "dv": "(V-xv)/Tf"
 },
 "states": {
  "xv": {"rhs": "(V-xv)/Tf", "init": "V0"},
  "xwq": {"rhs": "(theta-xwq)/Twq", "init": "theta0"},
  "xwp": {"rhs": "(theta-xwp)/Twp", "init": "theta0"},
  "xp": {"rhs": "(wp-xp)/Tp", "init": "0.0"}
 },
 "outputs": {
  "P": "P0-Dp*xp/(2*pi*60)",
  "Q": "Q0+A*(Vset-V0)+B*(V-V0)+C*dv+Eq*wq"
 }
}
```