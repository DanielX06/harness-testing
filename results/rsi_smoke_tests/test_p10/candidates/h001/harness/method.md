HOW TO WORK
1. Read runs.json and dataset.json, then look at the data before fitting anything. Check what moves after each event and on what time scales, how P and Q relate to V, theta and the voltage setpoint, and how large the noise is.
2. Use both kinds of recording. The staged voltage-reference tests show the voltage control directly. The ambient recordings and natural events show how the device responds to the grid.
3. Start with the smallest structure that fits: a few first-order lags and static gains. Fit P and Q as outputs with V, theta and Vset as inputs, the way the scorer uses them. Fit on train/ only.
4. Gate every candidate with the closed-loop check before you trust its replay:
   python tools/grid_check.py submission.json val/A_val_load_op1.csv
   It linearizes the model and closes the loop through a constant source behind several reactances. It prints the closed-loop poles, the static gains and a verdict.
   - Any UNSTABLE pole: the model would likely destabilise the grid. Slow the term responsible, reduce its gain, or drop it, then refit. A model that replays better but is UNSTABLE scores worse than a stable one.
   - dQ/dV at fixed Vset should be negative. The device regulates voltage by reactive-power droop, so Q falls as V rises. A positive dQ/dV is destabilising voltage feedback.
   - Keep the fastest pole below 500 rad/s (time constant above 2 ms). The data have 1 ms samples, and faster states are not identified and can break a simulation.
   - LIGHTLY DAMPED poles (zeta below 0.05) mean ringing in the grid. Prefer a damped fit.
5. Replay the candidate on val/: drive it with the measured V, theta and Vset and compare P and Q with the measured ones. python tools/check_submission.py submission.json val/<file>.csv runs this replay and the closed-loop check together.
6. Revise from the residuals, not from the fit score alone. Note which candidates you rejected and why.
7. Stop when the residuals are near the noise or further terms stop improving the validation replay. Note any parameter that is poorly identified or trades off against another one.
8. Write the final model to submission.json, run python tools/check_submission.py submission.json val/<file>.csv on both validation files, fix anything reported (including UNSTABLE), and submit.
