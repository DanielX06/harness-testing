The submission is written to `submission.json` and passes the scorer's checks. It starts at rest and replays the two validation recordings with P and Q errors well below a flat-line baseline. I did not run a closed-loop grid simulation, so grid stability is untested.

**Model**

- **Reactive power** has two internal lags driven by the voltage error `e = Vset − V`:
  - `T1·dx1/dt = g1·e − x1`
  - `T2·dx2/dt = g2·e − x2`
  - `Q = Q0 + a·(Vset − V0) + b·(V − V0) + x1 + x2`
  - Fitted values: a = 1.77, b = 0.72, g1 = −6.89, T1 = 4.93 s, g2 = 34.25, T2 = 19.93 s.
- **Active power** has a frequency-droop term on bus-angle rate, followed by a first-order lag:
  - `xp` is a washout of θ with Tw = 0.02 s, so `w = (θ − xp)/Tw` approximates dθ/dt.
  - `Tp·dP/dt = (P0 + Kp·w + Kv·(V − V0)) − P`
  - Fitted values: Kp = −0.0451 pu per rad/s, Tp = 0.100 s, Kv = −0.080.

**Identification**

- **Active power** is well identified. Kp and Tp are consistent across the generator-trip, fault, line-trip and ambient recordings, with train RMS of about 0.001 pu. Tw sits at its lower bound, so the washout is effectively a derivative and is only roughly identified.
- **Reactive power** is the weak part. Train RMS is about 0.017 pu, and the fault and line-trip recordings fit worst (about 0.023–0.026 pu) because the linear structure does not capture large voltage swings. The split between g1 and g2 and the time constants T1 and T2 trade off against each other.
- **Steady-state voltage droop** is poorly identified. The implied dQ/dV at fixed setpoint is about −27 pu, from b − (g1 + g2). That is much stiffer than a typical 4–5% droop, and the staged-test data does not pin it down well. It is also the main risk for the scorer's closed-loop runs and its droop check.
- **Validation:** open-loop replay on `A_val_vref_op2` gives P RMSE 9.5e-4 and Q RMSE 1.0e-2. On `A_val_load_op1` it gives P 4.1e-4 and Q 5.5e-3.

```json
{
  "params": {"a": 1.7674310485802935, "b": 0.7241971079234382, "g1": -6.887060506993201, "T1": 4.926400419307519, "g2": 34.25049743851244, "T2": 19.93330483479537, "Kp": -0.045063968494182004, "Tw": 0.02, "Tp": 0.10009254652875509, "Kv": -0.0796767068898977},
  "defs": {"w": "(theta-xp)/Tw"},
  "states": {
    "x1": {"rhs": "(g1*(Vset-V)-x1)/T1", "init": "0.0"},
    "x2": {"rhs": "(g2*(Vset-V)-x2)/T2", "init": "0.0"},
    "xp": {"rhs": "(theta-xp)/Tw", "init": "theta0"},
    "yp": {"rhs": "((P0+Kp*w+Kv*(V-V0))-yp)/Tp", "init": "P0"}
  },
  "outputs": {"P": "yp", "Q": "Q0+a*(Vset-V0)+b*(V-V0)+x1+x2"}
}
```