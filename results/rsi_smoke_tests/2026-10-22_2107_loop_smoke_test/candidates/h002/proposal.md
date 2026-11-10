## evidence
Current harness 9a035ad, 6 runs, mean composite 0.847. Four of six runs failed a held-out disturbance, and most failures were B_line grid divergence at t = 2 to 6.6 s (d554, fb30, 517e, e216). The failing models had fast or stiff paths: e216 Kd = +2.05 with Tq = 0.145 s, d554 Kd = +1.6 positive instantaneous dQ/dV, 517e Kp = 1.5 with Tq = 0.043 s and an integral voltage path, fb30 a tw = 1.5 s washout. c2d4 (Tw at its 0.02 s bound, positive K1+K2 cancelling to a small dQ/dV) survived all disturbances with the best composite, 0.469. ddbf also passed, with a positive net dQ/dV of 0.54. The sign rule is not a clean predictor, so this is evidence, not proof.

## root_cause
Nothing in the harness checks closed-loop stability before submission. method.md warns about reacting too strongly but gives no test, so the solver fits replay error alone and submits structures with a positive instantaneous voltage-to-Q path or very fast lags, which replay well and diverge in the grid. A failure scores 2, so each failure dominates the composite.

## change
Added tools/linear_screen.py, which linearizes the submission at the recording's operating point, reports eigenvalues, the fastest time constant and steady-state dP/dV, dP/dtheta, dQ/dV and dQ/dtheta, and flags instability, time constants under 5 ms and positive dQ/dV. method.md now gives structure rules (angle washout at least 0.02 s, reactive droop with negative dQ/dV, fast lags above 0.02 s), names the screen with its command line, and makes it a required step before check_submission.py.

## predicted_effect
B_line failures should drop from about 4 of 6 runs to 1 or 2 of 6. Mean composite should fall from about 0.85 to about 0.6 to 0.7, mainly through removing the failure penalty of 2 on a disturbance. Non-failing TD values should change little, though a slightly worse Q fit is possible where a positive dQ/dV had helped replay. The change is not yet measured.

## at_risk
Attempt 1 (stability_check in h001) was rejected after 2 runs with a worse composite, and this change overlaps with it: a 5 ms and sign-based gate may push the solver toward slower, less accurate fits. The sign rule is an assumption about reactive droop that the data sometimes contradict (ddbf and d554 fit a positive net gain). The screen does not simulate the grid, so stable-looking models can still fail. Expect some extra tool calls and cost. The rule must not be read as a device-specific fact.