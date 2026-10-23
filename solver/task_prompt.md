You are identifying how one device in a power system behaves at its terminal, from recorded data. Your answer is a terminal model: equations, with any internal states they need, that take the voltage magnitude and angle at the device's terminal (and its voltage setpoint) and return the active and reactive power it injects.

DATA
Your working directory holds:
- train/ and val/: one CSV per recording.
- runs.json: the operator's log for each recording, with the operating conditions and every timestamped event.
- dataset.json: the device rating, units, sample period and measurement noise levels.
- system_diagram.png: the network (also attached to this message).
- tools/: helper code you can run or import.

CSV columns:
- time_s: time in s.
- active_power_pu, reactive_power_pu: P and Q injected by the device, in pu on its own 900 MVA rating.
- voltage_pu: terminal voltage magnitude, in pu.
- bus_angle_rad: terminal voltage angle, in rad, shifted so each recording starts at 0.
- voltage_setpoint_pu: the device's voltage setpoint from the control log. It is not a measurement and has no noise. It changes only during staged voltage-reference tests.

{{NOISE}} The recordings cover ambient operation, staged voltage-reference tests and natural events (faults, line and generator trips, load changes) at three operating points. Fit on train/. Use val/ only to check candidates you have already fitted.

HOW YOUR ANSWER IS SCORED
Your model is scored on a different grid that you never see, at a different operating point, with disturbances that differ in type, place and size from these recordings. For each held-out recording, the scorer puts your model into the network simulation in place of the real device, applies the same disturbance and compares the P and Q your model injects with the real device's. Your model's output feeds back into the grid, so a model that destabilizes the grid is penalized heavily. Staged voltage-reference tests are replayed by stepping your Vset.

Two more checks use your model's linearization at the operating point, with V, theta and Vset held:
- its frequency response from (V, theta) to (P, Q) between 0.1 and 10 Hz;
- its steady-state droops, dP/d(omega) and dQ/dV.
Both are compared with the real device's.

Every check is normalized so that a model whose P and Q never move scores 1 and the real device scores 0. Lower is better, and a model that fails to run scores 2. A model that fits the noise or these particular events will score worse than one that captures how the device actually behaves. A simple model that is right beats a complicated one that fits slightly better.

SUBMISSION FORMAT
A submission is JSON. Every expression is a string in Python syntax:

```json
{
  "params":  {"name": 1.0},
  "defs":    {"name": "expr"},
  "states":  {"name": {"rhs": "expr", "init": "expr"}},
  "outputs": {"P": "expr", "Q": "expr"}
}
```

- params: every numeric coefficient, at full precision.
- defs: optional named intermediate expressions. They are evaluated in order, and each may use defs defined before it.
- states: the internal states. rhs is d(state)/dt, and init is the state's value at t = 0.
- outputs: P and Q injected by the device, in pu on its rating.

These symbols may appear in expressions:
- V and theta: terminal voltage magnitude (pu) and angle (rad), live.
- Vset: the voltage setpoint (pu), live. It equals V0 until a staged test steps it.
- V0, theta0, P0, Q0: the operating point at t = 0, with P0 and Q0 in pu on the rating.
- pi, your params, your states, and defs already defined.

Allowed functions: sin, cos, tan, exp, log, sqrt, tanh, atan, atan2, Abs, Min, Max. Allowed operators: + - * / **. Time t and derivatives are not available; if your model needs a derivative or a filter, give it a state.

Init expressions may use V0, theta0, P0, Q0, pi, params and other states' inits, but not Vset (at t = 0, Vset = V0). At t = 0 the model must be at rest: every rhs zero, P equal to P0 and Q equal to Q0. This must hold at any operating point, so take setpoints from the operating point rather than hard-coding them. A model that starts away from rest produces a transient that counts as error.

In the simulation, theta is the absolute bus angle, and the files shift it to start at 0. Use theta only relative to theta0 or to an internal angle state that starts at theta0.

Limits: 60 states, 200 defs, 200 params, 4000 characters per expression.

TOOLS
run_python runs a Python script in your working directory, with numpy, pandas, scipy and sympy available. Each call starts a fresh Python process, but files you save persist for the rest of this run, so save fitted results you will reuse. Output is truncated to the last 20000 characters, and each call times out after 120 s.

python tools/check_submission.py submission.json val/<file>.csv parses a submission with the scorer's own rules, checks that the first sample is at rest, and replays the recording open loop: the measured V, theta and Vset drive your model, and its P and Q are compared with the measured ones.

You may be told mid-task that the budget is reached. You must then submit your best model immediately.

YOUR FINAL MESSAGE
State the equations in plain form and say which parameters are well or poorly identified. Then end with exactly one json code block containing the submission. It should be the same content as the submission.json you checked.
