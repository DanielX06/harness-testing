HOW TO WORK
1. Read runs.json and dataset.json, then look at the data before fitting anything. Check what moves after each event and on what time scales, how the device's P and Q relate to V, theta and the voltage setpoint, and how large the noise is.
2. Use both kinds of recording. The staged voltage-reference tests show the device's voltage control directly. The ambient recordings and natural events show how it responds to the grid.
3. Propose a candidate structure and fit its parameters on train/, with P and Q as outputs and V, theta and Vset as inputs, the way the scorer uses them.
4. Check each candidate as close to how it will be scored as you can: drive it with the measured V, theta and Vset from val/, integrate it forward, and compare its P and Q with the measured ones.
5. STABILITY GATE (required before you submit). Run `python tools/stability_check.py submission.json val/A_val_load_op1.csv`. The model goes into a grid that feeds its P and Q back into V and theta, so a model that is unstable there scores worst. The check must show:
   - no eigenvalue with real part >= 0;
   - dQ/dV steady-state sensitivity <= 0 (Q must not rise with V);
   - no time constant below 2 ms.
   If any check fails, change the structure or the gains until it passes. Do not submit with a failing check. Common causes: a voltage-driven Q path with a large positive gain, a pure integrator on V with no leak, or a very fast lag. Fitted values that hit a bound are a warning sign for this check.
6. Revise based on what the residuals show, not on the fit score alone. Keep track of which candidates you rejected and why. A simpler structure that passes the gate beats a better fit that fails it.
7. Stop when the residuals are close to the noise or further terms stop improving the validation fit. Note any parameter that is poorly identified or trades off against another one.
8. Write the model to submission.json. Run `python tools/check_submission.py submission.json val/<file>.csv` on each validation file, and `python tools/stability_check.py submission.json val/<file>.csv`. Fix anything they report, then submit.
