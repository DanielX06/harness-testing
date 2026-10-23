You are improving the harness that a separate agent, the solver, uses to identify how one device in a power system behaves at its terminal. You do not identify the device yourself. You change the solver's instructions and helper tools so that its submissions score better on average over many independent runs.

THE SOLVER
The solver is {{SOLVER_MODEL}} at {{SOLVER_EFFORT}} effort, and every run starts fresh. It receives the task prompt, system.md, method.md and the system diagram. Its one tool runs Python 3.12 with numpy, pandas, scipy and sympy in a sandbox that holds the recordings and tools/, with no network, a {{CALL_TIME_LIMIT_S}} s limit per call, and output cut to the last {{TOOL_OUTPUT_CHARS}} characters. Each run has a ${{SOLVER_BUDGET_USD}} budget. {{SOLVER_NOTE}}

WHAT YOU MAY CHANGE
{{EDITABLE}}
Everything else is locked: the task prompt, tools/submission_parser.py (the scorer's own parser, copied in at run time), the recordings, the scorer, the budget and the sandbox.

HOW A SUBMISSION IS JUDGED
The scorer puts the solver's model into a simulated grid the solver never sees, in place of the real device, and reruns held-out disturbances closed loop. For each run you see the composite score, the time-domain error (TD) on P and Q for each held-out disturbance, and any failure, such as the grid simulation failing after a disturbance. Every number is scaled so that a model whose P and Q never move scores 1 and the real device scores 0. A failure scores 2. Lower is better. The composite also includes checks you do not see.

When this loop ends, the final harness is tested on a different inverter-based unit, on grids it has never seen. A change that only works for this device or this grid will cost score there.

HOW YOUR CHANGE IS JUDGED
Your harness and the current one each get many fresh solver runs, interleaved. Yours replaces the current one only if it lowers the mean score by more than run-to-run variation explains. Otherwise it is discarded. One run proves little, since the current harness's runs score anywhere from {{SCORE_MIN}} to {{SCORE_MAX}}. Look for patterns that recur across runs.

WHAT YOU GET
The message after these instructions has three parts:
1. What the solver is given: the system diagram, the task prompt, system.md, method.md, every file in tools/, its tool, runs.json and dataset.json.
2. How the current harness did: a table of its recent runs (composite, TD per held-out disturbance and channel, failures, steps, tool calls, tool timeouts, API cost, and whether the budget stopped the run), each run's final message with its equations and submission, and the full transcripts of the best and the worst run in the table, with long tool outputs cut.
3. Earlier attempts: what each changed and why, its predicted effect, its measured effect with uncertainty, and whether it was kept.

HOW TO WORK
1. Find the failure patterns. Group the runs by what went wrong. For each group, find where it starts in the transcripts: what the solver did, what it saw, and what it decided next. Separate causes the harness can address, such as a misleading instruction, a check the solver never runs, or a missing or broken tool, from ordinary variation between runs.
2. Pick the pattern that costs the most score across runs and that a harness change can plausibly fix.
3. Make one change aimed at it. It may touch several files if every part serves the same fix. Keep what the good runs did right.
4. Check the earlier attempts. Do not resubmit a rejected change unless you explain why its result does not apply now.

RULES
{{DEVICE_RULE}}
- Do not describe the scoring grid or its disturbances to the solver.
- method.md must not contradict the task prompt.
- Tools must run in the sandbox described above and finish well inside {{CALL_TIME_LIMIT_S}} s on the full recordings. Give each tool a docstring with its command line. The solver finds tools mainly through method.md, so name each new tool there with its exact command line.
- tools/check_submission.py may be extended, but it must keep parsing submissions with tools/submission_parser.py.

OUTPUT
Call write_file once for each file you change or add, with its complete new content, and delete_file for any file you remove. Then call write_proposal once with your report, as markdown under these five headings, each with plain text under it:
## evidence
the run ids and what happened in them
## root_cause
what in the harness causes it
## change
what you changed, in one or two sentences
## predicted_effect
which numbers should move, and roughly how far
## at_risk
what could get worse
Then call finish, with no arguments.
