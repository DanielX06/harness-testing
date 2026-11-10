HOW TO WORK
1. Read runs.json and dataset.json, then look at the data before fitting anything. Check what moves after each event and on what time scales, how the device's P and Q relate to V, theta and the voltage setpoint, and how large the noise is.
2. Use both kinds of recording. The staged voltage-reference tests show the device's voltage control directly. The ambient recordings and natural events show how it responds to the grid.
3. Propose a candidate structure and fit its parameters on train/, with P and Q as outputs and V, theta and Vset as inputs, the way the scorer uses them.
4. Check each candidate as close to how it will be scored as you can: drive it with the measured V, theta and Vset from val/, integrate it forward, and compare its P and Q with the measured ones. The scorer runs closed loop, inside the grid. A model that reacts too strongly can destabilize the grid even if it replays well. A model with very fast internal dynamics can diverge in open-loop replay and still run fine in the grid.
5. Stability gate, before any submission (this is what has broken past submissions in the grid):
   `python tools/stability_check.py submission.json val/<file>.csv`
   It prints the model's eigenvalues and steady-state gains and lists FLAGS. Do not submit a model with a flag. In particular:
   - steady dQ/dV must be negative (more Q when V falls). A positive value is positive feedback and has crashed grid runs.
   - no eigenvalue may have a positive real part.
   - a fitted time constant must not be below 0.002 s.
   A zero eigenvalue (an integrator in the voltage path) is allowed: the tool prints a note, not a flag. Judge it by its staged-test replay. If the fit pushes a gain to its bound, bound it away from the unstable side and refit.
6. Revise based on what the residuals show, not on the fit score alone. Keep track of which candidates you rejected and why.
7. Stop when the residuals are close to the noise or further terms stop improving the validation fit. Note any parameter that is poorly identified or trades off against another one.
8. Write the model to submission.json. Run python tools/check_submission.py submission.json val/<file>.csv on each validation file, then tools/stability_check.py on it, fix anything reported, and then submit.
