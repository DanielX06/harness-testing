HOW TO WORK
1. Read runs.json and dataset.json, then look at the data before fitting anything. Check what moves after each event and on what time scales, how the device's P and Q relate to V, theta and the voltage setpoint, and how large the noise is.
2. Use both kinds of recording. The staged voltage-reference tests show the device's voltage control directly. The ambient recordings and natural events show how it responds to the grid.
3. Propose a candidate structure and fit its parameters on train/, with P and Q as outputs and V, theta and Vset as inputs, the way the scorer uses them.
4. Check each candidate as close to how it will be scored as you can: drive it with the measured V, theta and Vset from val/, integrate it forward, and compare its P and Q with the measured ones. The scorer runs closed loop, inside the grid. A model that reacts too strongly can destabilize the grid even if it replays well.
5. Revise based on what the residuals show, not on the fit score alone. Keep track of which candidates you rejected and why.
6. Stop when the residuals are close to the noise or further terms stop improving the validation fit. Note any parameter that is poorly identified or trades off against another one.
7. SAFETY GATE, required before submitting. Run:
   python tools/stability_check.py submission.json val/A_val_load_op1.csv
   It must print PASS. If it reports an unstable eigenvalue, a time constant under 5 ms, a failed synthetic step, or a large excursion, the model will likely destabilize the grid. Fix it first: lower the gain on the fastest path, lengthen the shortest time constant, or drop the term that causes it. Do not submit a model that fails this check.
8. Write the model to submission.json. Run python tools/check_submission.py submission.json val/<file>.csv on each validation file, fix anything it reports, and then submit.

NOTES ON STABILITY
- A gain that acts on a near-derivative of the angle (a washout with a very short time constant) is the usual cause of grid failure. Keep such washouts at a time constant of at least 5 ms, and check the frequency-type gain against the droop the recordings show, not against a large number.
- A purely proportional voltage path with a fast lag can ring in the grid. Prefer a slower lag on the voltage loop unless the staged tests clearly need it.
- Keep the model small. Two or three states is enough for most of the behaviour here.
