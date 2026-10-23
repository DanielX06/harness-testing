HOW TO WORK
1. Read runs.json and dataset.json, then look at the data before fitting anything. Check what moves after each event and on what time scales, how the device's P and Q relate to V, theta and the voltage setpoint, and how large the noise is.
2. Use both kinds of recording. The staged voltage-reference tests show the device's voltage control directly. The ambient recordings and natural events show how it responds to the grid.
3. Propose a candidate structure and fit its parameters on train/, with P and Q as outputs and V, theta and Vset as inputs, the way the scorer uses them.
   Structure rules that keep the model stable in the grid:
   - Get frequency from the bus angle through a washout with a time constant of at least 0.02 s. Do not use a raw derivative or a washout faster than that.
   - Keep the reactive path a droop: steady-state dQ/dV negative. Do not add an instantaneous positive V-to-Q term to fit a few samples.
   - Keep fast lags (Tq, T2) above about 0.02 s unless the data clearly need them.
4. Screen every candidate linearly before any replay: `python tools/linear_screen.py submission.json val/A_val_load_op1.csv`. Reject a candidate with an UNSTABLE line. Treat FLAGGED warnings (fast mode, positive dQ/dV, large dP/dtheta) as reasons to refit with a slower or sign-constrained structure, and say why in your notes if you keep one.
5. Check each surviving candidate by driving it with the measured V, theta and Vset from val/, integrating it forward, and comparing its P and Q with the measured ones: `python tools/check_submission.py submission.json val/<file>.csv`. Replay error alone is not enough; a model that replays well can still destabilize the grid.
6. Revise based on what the residuals show, not on the fit score alone. Keep track of which candidates you rejected and why.
7. Stop when the residuals are close to the noise or further terms stop improving the validation fit. Note any parameter that is poorly identified or trades off against another one.
8. Write the model to submission.json, run the linear screen and check_submission.py on each validation file, fix anything they report, and then submit.
