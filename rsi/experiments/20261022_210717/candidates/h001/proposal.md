## evidence
Runs ddbf, d554, fb30, 517e: 3 of 4 failed the grid simulation (d554 on all three held-out disturbances at t=2 to 15 s; fb30 and 517e on B_line at t=2.6 and 6.3 s). Failures came early in the disturbance, which points to instability rather than poor fit. Mean composite 0.967 with runs spanning 0.73 to 1.38. The tool-timeout pattern (2 of 65 calls) shows solvers also spent time on slow fits, but timeouts did not decide the scores.

## root_cause
Nothing in the harness checks whether a candidate model is stable in closed loop. method.md tells the solver to validate open-loop replay and says a model that reacts too strongly can destabilize the grid, but gives no test for it. Solvers therefore submit high-gain or very fast-washout structures (for example a near-derivative angle path with a 10 ms washout, or a large voltage-path gain) that replay well and fail in the grid.

## change
Added tools/stability_check.py, which linearizes the submission at the recording's operating point, flags unstable eigenvalues and time constants under 5 ms, and runs a synthetic voltage and angle step to check for ringing or large excursions. method.md now makes this check a required gate before submitting, and adds short notes on which structures tend to destabilize the grid.

## predicted_effect
Fewer grid failures: B_line and B_load failures should drop from about 4 of 4 failing runs to a minority, and failed-disturbance count per run should fall from about 1.25 toward 0.5. The mean composite should fall by roughly 0.2 to 0.4 where failures are removed, since a failure scores 2. Non-failing TD values should change little.

## at_risk
The 5 ms threshold and 1% step are heuristics, so a correct but fast device model may be rejected and pushed toward a slower, worse fit. The check does not simulate the grid, so stable-looking models can still fail. The extra step adds a few tool calls and some cost per run.