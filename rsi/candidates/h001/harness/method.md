HOW TO WORK
1. Read runs.json and dataset.json, then look at the data before fitting anything. Check what moves after each event and on what time scales, how the device's P and Q relate to V, theta and the voltage setpoint, and how large the noise is.
2. Use both kinds of recording. The staged voltage-reference tests show the device's voltage control directly. The ambient recordings and natural events show how it responds to the grid.
3. Propose a candidate structure and fit its parameters on train/, with P and Q as outputs and V, theta and Vset as inputs, the way the scorer uses them.
4. Check each candidate on val/: python tools/check_submission.py submission.json val/<file>.csv
5. Run the closed-loop screen on every candidate before you submit it: python tools/screen.py submission.json val/<file>.csv
   The scorer runs your model closed loop inside a grid. Open-loop replay does not show whether the model destabilises the grid, and most failed candidates replayed well. The screen prints the device's poles, the static signs and the closed loop with a generic test network. It must end with "SCREEN: stable". If it says UNSTABLE, fix the cause before anything else.
6. Sign rules that the documentation requires, and that the screen checks:
   - Voltage regulation is by reactive-power droop: with Vset held, dQ/dV is negative (Q falls as V rises). Q should rise when Vset is raised. A positive dQ/dV is almost always a fitting artefact: load variation moves V and Q together in ambient data. Fit the steady voltage gain from the staged tests, and reject candidates whose dQ/dV is positive.
   - Active-power droop: dP/dw is negative (P falls as frequency rises).
   - Keep time constants at or above about 2 ms. Faster poles are not resolvable from 1 ms samples and make the grid simulation stiff.
7. Revise based on what the residuals show, not on the fit score alone. Keep track of which candidates you rejected and why. Do not stop at the first candidate that replays well: the scorer penalises closed-loop failure heavily.
8. Stop when the residuals are close to the noise, the screen is stable, and further terms stop improving the validation fit. Note any parameter that is poorly identified or trades off against another one.
9. Write the model to submission.json, run both checks on each validation file, fix anything they report, and then submit.
