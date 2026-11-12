## evidence
696a (unit 1, 0.863): the grid simulation failed on B_line at t=10.83 s, so that disturbance scored as a failure. Its model was a droop structure with a fast direct Q-V term, and the solver never checked stability or the speed of its loops. a51d (unit 2, 0.590): all held-out TDs were moderate (P 0.16-0.27, Q 0.16-0.31); its Q fit was poor and it never checked the linearization. In the sandbox, the 696a submission linearizes stable with the fastest pole at about 100 rad/s, while the solver's stronger-looking candidate for the same family has a 200 rad/s pole and a positive dQ/dV sensitivity (+ from bq), which is the kind of thing the new check flags as FAST.

## root_cause
Nothing in the harness checks whether a candidate is stable or how fast its loops are before submission. The solver fits open-loop replays, which cannot show closed-loop instability, and it has no tool for the linear check the scorer runs. Fast fitted terms (filters at their bounds, a direct Q-V path) can therefore reach the grid unexamined and fail it.

## change
Added tools/stability_check.py, which linearizes submission.json at a recording's first sample and reports eigenvalues, time constants, UNSTABLE and FAST flags, and the instantaneous P/Q sensitivities to V and theta. Rewrote method.md to name the tool with its command line, add it as a required step before submitting, and say what to do with each flag.

## predicted_effect
Fewer grid failures, so fewer runs at 2 on a disturbance. Composite on the failing runs should drop by a fraction of a point, and the mean should move down by roughly 0.05 to 0.1 if failures are the main loss. The tool itself is not expected to change fit quality much.

## at_risk
The solver may over-react to FAST flags and drop a fast term that the data needs, which would worsen the fit. The 0.01 s threshold is a judgement, not a scorer rule. The check only covers the linearization at one point; it cannot show a closed-loop failure. The added method text makes the instructions a little longer, which a small model may skim.