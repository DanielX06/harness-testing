The model is written to `submission.json`. It passes the scorer's parse and at-rest checks on both validation files and runs stably in the grid-equivalent replay.

**Structure (device terminal = bus 3, all quantities in pu on 900 MVA)**

- **Voltage measurement lag:** `vm` follows the terminal voltage V with time constant Tm ≈ 0.12 s.
- **Integral state:** `xi` integrates the error e = Vset − vm.
- **Angle washout:** `xw` tracks θ − θ0 with time constant Tw ≈ 0.037 s, so hp = (θ − θ0) − xw is a high-passed angle, a proxy for the frequency deviation.
- **Active power:** P = P0 + a·hp + b·(V − V0)
- **Reactive power:** Q = Q0 + Kp·e + Ki·xi + Kv·(vm − V0) + c·hp + Kd·(Vset − V)

Parameter values: a = −1.225, Tw = 0.0368, b = −0.0199, Kp = 2.884, Ki = 0.507, Tm = 0.1227, Kv = 2.507, c = −0.251, Kd = −1.251.

**Fit quality**

- Training RMS over all seven training recordings: about 0.0095 pu, with P errors around 1e-3 and Q errors around 0.003–0.01 on ambient and step data.
- Validation (grid-equivalent replay): P RMSE about 5e-4 and Q RMSE about 7–8e-3, against flat-line baselines of 6e-3 to 2e-2 for P and 3e-2 for Q.
- Known weak spot: the line-trip and generator-trip recordings still leave Q residuals of about 0.02–0.03 pu. These residuals are not consistent across files when regressed on angle, P or V, so I did not add those terms.

**Identifiability**

- **Well identified:** the fast voltage-loop gains (Kp, Kd and Tm) from the staged ±2% steps. The Q droop is their net, Kp + Kd ≈ 1.63 pu/pu.
- **Less well identified:** Ki and Kv. These trade off against each other, and the integrator form gives no unique steady-state dQ/dV.
- **Poorly identified:** the washout time constant Tw and the P-coefficient a. The angle effect is seen mainly during the large angle drifts after the trips. The fitted P sensitivity to the high-passed angle is sizeable, but its time structure is not well resolved.
- **Frequency droop:** the P response to angle is the only frequency-like channel. Its steady-state value is effectively zero because the washout removes slow drift, so the scorer's dP/dω check may not match the device's documented droop. This is a risk I did not resolve.
- **Not modelled:** the Q dependence on P that appears in the trip recordings, and any fast current-limit or fault behaviour. A fault recording was not used in fitting.

```json
{
  "params": {
    "a": -1.2246705097829478,
    "Tw": 0.03683209859031522,
    "b": -0.0199109562120019,
    "Kp": 2.8838269023648446,
    "Ki": 0.5066168426045367,
    "Tm": 0.12265340053964582,
    "Kv": 2.5068494850956675,
    "c": -0.2510525267865945,
    "Kd": -1.2506307135379964
  },
  "defs": {
    "e": "Vset-vm",
    "hp": "theta-theta0-xw"
  },
  "states": {
    "vm": {"rhs": "(V-vm)/Tm", "init": "V0"},
    "xi": {"rhs": "e", "init": "0.0"},
    "xw": {"rhs": "(theta-theta0-xw)/Tw", "init": "0.0"}
  },
  "outputs": {
    "P": "P0+a*hp+b*(V-V0)",
    "Q": "Q0+Kp*e+Ki*xi+Kv*(vm-V0)+c*hp+Kd*(Vset-V)"
  }
}
```