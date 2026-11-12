HOW TO WORK
1. Read runs.json and dataset.json, then look at the data before fitting anything. Check what moves after each event and on what time scales, how the device's P and Q relate to V, theta and the voltage setpoint, and how large the noise is.
2. Use both kinds of recording. The staged voltage-reference tests show the device's voltage control directly. The ambient recordings and natural events show how it responds to the grid.
3. Propose a candidate structure and fit its parameters on train/, with P and Q as outputs and V, theta and Vset as inputs, the way the scorer uses them.
4. Check each candidate as close to how it will be scored as you can: drive it with the measured V, theta and Vset from val/, integrate it forward, and compare its P and Q with the measured ones. The scorer runs closed loop, inside the grid. A model that reacts too strongly can destabilize the grid even if it replays well.
5. Run the stability check on every candidate before you accept it:
       python tools/stability_check.py submission.json train/<file>.csv
   It linearizes the model at the recording's first sample and prints its eigenvalues and its instantaneous P and Q sensitivities to V and theta.
   - UNSTABLE: do not submit this candidate. Refit with the offending gain or filter bounded, or simplify the structure. A grid simulation that goes unstable scores as a failure.
   - FAST: the model has a loop faster than 0.01 s. Check whether a filter or gain went to its bound to fit a fast event. If the fit needs it, keep the fast term small and say so in your final message.
   - A positive dQ/dV in the sensitivities means the model raises Q when V rises at fixed angle. Only keep such a term if the recordings show it clearly, and keep its size small.
   The check does not show whether the model fits. Use it together with step 4.
6. Revise based on what the residuals show, not on the fit score alone. Keep track of which candidates you rejected and why.
7. Stop when the residuals are close to the noise or further terms stop improving the validation fit. Note any parameter that is poorly identified or trades off against another one.
8. Write the model to submission.json. Run python tools/check_submission.py submission.json val/<file>.csv on each validation file, then python tools/stability_check.py submission.json val/<file>.csv, fix anything either reports, and then submit.
