The submission is saved as `submission.json`. It passes the scorer's parser and at-rest check on the validation and training files I tried. It is a deliberately small model, and it fits P well but not Q.

**Structure**

- **Active power (well identified):** P = P0 − K·(θ − φ). The state φ is a first-order tracker of the bus angle, φ' = w0·kp·(θ − φ), so θ − φ ≈ (dθ/dt)/(w0·kp). P therefore responds to the bus angle's rate of change like a frequency droop, with no stiffness on the angle itself. This matches the data, where P moves about −0.04 pu per rad/s of angle drift and does not move with the absolute angle.
- **Reactive power (poorly identified):** Q = Q0 + kq·(V − V0) + kqs·(Vset − V0), with both gains tiny. Q is essentially constant across every recording, with variations near the noise floor (about 0.0005 pu). The setpoint steps in the staged tests produced no measurable Q or V response.
- **Fitted values:** K ≈ 0.96, kp ≈ 0.054 (so the tracker bandwidth is about 20 rad/s, roughly 3 Hz), kq ≈ −0.002, kqs ≈ −0.0002.

**Fit quality**

- Mean validation error is 0.53. P errors are about 0.04–0.08 on every fitted recording. Q errors are about 1.0 (no better than a constant).
- The fault recording is excluded from the fit by the tool. The model's P error there is about 0.6, so the large-disturbance behaviour is not captured.
- The model is stable on its own and when tied to a source behind 0.3 or 0.6 pu reactance.

**Weak points**

- The Q-V droop check will likely score poorly: the data shows almost no reactive-voltage response, and I could not identify one. A small Q–P coupling was tried (≈0.1 pu per pu from regression) but the fit collapsed it, so I did not keep it.
- The generic droop and VSM templates fit far worse here (mean error about 1.5). The device behaves like a frequency-droop unit with a fast angle tracker and a constant reactive-power reference.

```json
{
  "params": {
    "w0": 376.99111,
    "K": 0.9588848290757741,
    "kp": 0.0539073760024907,
    "kq": -0.0021347820989559584,
    "kqs": -0.0002217039356255058
  },
  "defs": {},
  "states": {
    "phi": {
      "rhs": "w0*kp*(theta-phi)",
      "init": "theta0"
    }
  },
  "outputs": {
    "P": "P0 - K*(theta-phi)",
    "Q": "Q0 + kq*(V-V0) + kqs*(Vset-V0)"
  }
}
```