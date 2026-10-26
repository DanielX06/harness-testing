# RSI loop

The recursive self-improvement loop for the solver's harness. An updater model reads how the current harness did and proposes one change, fresh solver runs of the candidate and of the current harness, side by side, decide whether the change stays, and the loop repeats. Haiku 5.5 at low effort is both the solver and the updater unless you say otherwise.

| file | what it is |
|---|---|
| `rsi_experiment.py` | the loop: a baseline of the starting harness, then propose, a test block, a confirmation block, keep or not, for `--iters` iterations; `--resume` carries on an interrupted experiment |
| `harness_proposal.py` | one updater call: builds the context, lets the updater edit a copy of the harness, checks the result and writes a candidate folder |
| `updater_context.py` | builds the updater's system prompt, its one user message and its three tools from a set of runs, the harness they used and the history of earlier attempts |
| `updater_prompt.md` | the updater's instructions, with placeholders that `updater_context.py` fills |
| `tests/test_rsi_experiment.py` | 45 end-to-end checks with a fake updater and a fake solver (re-stamped Oct 13 runs): the accept rule, early rejection, confirmation, crashes and resumes, failed runs resumed and replaced, runs left going by a killed loop, the cycle record, spend and the command line |
| `tests/test_harness_proposal.py` | 33 checks with a scripted fake updater (no API call): refused paths, every check and warning, every status, the self-test, cost |
| `tests/test_updater_context.py` | 29 checks: both scopes, history rendering, scrubbing, every leak check, the budget reductions, and that the Oct 13 context is unchanged by the rewrite apart from the parser |
| `tests/fixtures/` | the ten Oct 13 clean runs and the harness that made them (fingerprint f141be203a8a40f4), so the tests never depend on `harness_v0/runs` |
| `previews/oct13_clean/` | the context built from the Oct 13 clean batch in `tests/fixtures/`: `context.md` (readable, with the diagram as a placeholder line) and `stats.json` |

Commands below run from `Harness_testing/` with the project's Python (on the Mac, `PY=../.venv/bin/python`). The tests need no API key, no Docker and no ANDES: `$PY rsi/tests/test_rsi_experiment.py` and the other two.

## Running the loop

```bash
$PY rsi/rsi_experiment.py --iters 2 --baseline-runs 4 --pairs 4 --early-stop-pairs 2 --confirm-pairs 4   # smoke test
$PY rsi/rsi_experiment.py --iters 30                                                                    # the real thing
```

It needs `ANTHROPIC_API_KEY` and Docker with the solver's image (`harness-v0-py`, built from `solver/Dockerfile`). The loop copies the starting harness (`--start`, default `harness_v0/harness`) to `candidates/h000` and makes `--baseline-runs` (20) runs of it, so the first updater has something to read. Each iteration then goes like this.

1. Propose. `harness_proposal.py` shows the updater the newest `--newest-runs` (20) runs of the current harness, from every block it has run in, and the history of earlier attempts. It edits a copy, and a copy that fails a check is never run.
2. Test block. Pairs of fresh runs, one of the candidate and one of the current harness in each pair, started together; which one starts first alternates. After `--early-stop-pairs` (8) pairs, a candidate whose mean composite on grid B is not below the current harness's is rejected early. Otherwise, after `--pairs` (20) pairs, it passes if its mean is lower and a one-sided permutation test on this block's 20 + 20 runs gives p ≤ `--alpha` (0.10).
3. Confirmation block. A candidate that passed gets `--confirm-pairs` (20) new pairs, run and judged the same way, the early stop included, on their own. Passing both makes it the current harness; failing this one reverts it.
4. Stop after `--iters` iterations, after `--patience` (20) attempts in a row that were not kept, or once `--max-usd` (20) has been spent, checked before each iteration. Budgets are in USD, the currency of the per-token prices in `common/api_pricing.py`.

Each block compares the candidate with runs of the current harness made in the same block, not with older runs. Over the days a loop takes, the solver's behavior can drift (API changes, load, a new Docker image), and a candidate measured against last week's runs would be credited or blamed for the drift. Every block also gives the current harness new runs, so each updater reads fresh evidence rather than the same 20 transcripts. Because the two blocks share no runs, a candidate no better than the current harness passes both with probability α² (1% at 0.10). The early stop can only reject, so it cannot raise that.

What the rule can detect, from resampling the ten Oct 13 composites (mean 0.884, SD 0.433) and a normal approximation to the permutation test, so take the numbers as rough:

| true improvement in composite | passes the test block | kept | rejected early | runs per iteration on average |
|---|---|---|---|---|
| none | 10% | 0.8% | 49% | 31 |
| 10% | 26% | 7% | 33% | 41 |
| 20% | 55% | 31% | 17% | 56 |
| 30% | 84% | 71% | 6% | 71 |
| 40% | 97% | 95% | 2% | 78 |

So a rejection means "not shown to be better", not "no better": a candidate that is truly 20% better is kept about a third of the time. At about $0.017 a Haiku-low run, an early rejection costs about $0.30, a full rejection about $0.70 and a kept or reverted candidate about $1.35, plus a few cents for the updater. The baseline is about $0.35.

The smallest p a block can give is 1/C(2n, n) for n pairs: 1/6 for 2, 1/20 for 3, 1/70 for 4. Below 3 pairs nothing can pass at α = 0.10, and the loop warns. Use an even `--parallel` (default 2) so the two runs of a pair run at the same time; `--workers` sets the ANDES simulations at once inside each run's scoring.

### Failed runs and resuming

A run that ends with a failure score (an invalid submission, a model that fails in simulation) is a result and counts. A run that stops for a reason outside the harness is not: an API outage longer than the 35 minutes `solver/solver_run.py` rides out, Docker failing, the scorer itself crashing. The loop resumes such a run from its checkpoint until it has failed more than `--max-resumes` (2) times, then replaces it with a new run for the same pair; the abandoned run's spend still counts. A conversation that outgrows the model's context window ends the run like a final message without a json block (the sandbox's `submission.json` is scored, or it scores 2), since that is the harness's doing. After `--max-failures-in-a-row` (6) failed sessions with no run finishing in between, or when Docker cannot run the candidate's checker, the loop stops with exit code 3 so you can fix the cause.

```bash
$PY rsi/rsi_experiment.py --resume rsi/experiments/20261022_090000               # carry on where it stopped
$PY rsi/rsi_experiment.py --resume rsi/experiments/20261022_090000 --iters 40    # extend a finished experiment
```

Everything is on disk, and a resumed loop decides exactly what an uninterrupted one would. `history.jsonl` is the record of finished iterations, and its line for an iteration is written last. A saved `proposal.json` is reused rather than paid for again. Scored runs are kept, crashed and stopped runs are resumed, and runs still going from a loop that was killed are waited for (the loop checks that the pid in `meta.json` is still a `solver_run.py` process on that run). Decisions use fixed pairs, the first `--early-stop-pairs` and then all `--pairs`, so it does not matter which runs finished first. A proposal cut off before `proposal.json` was written is moved to `candidates/hNNN.interrupted_<time>` and made again, and its updater spend, from its `transcript.json`, still counts. Spend is recomputed from every run's `meta.json` and every proposal each time, so `--max-usd` holds across resumes. `--resume` accepts only `--iters`, `--patience`, `--max-usd`, `--parallel`, `--workers`, `--updater-max-usd` and `--max-resumes`; anything else would change the experiment, and `config.json` records each resume and what it changed.

`loop.lock` holds the running loop's pid, and a second loop refuses the folder while that pid is a live `rsi_experiment.py` process. Stopping the loop (Ctrl-C, `kill`, closing its terminal) stops its solver runs too: each runs in its own session, and the loop sends them SIGTERM, which `solver_run.py` records as `stopped` before it saves and exits.

For a run that should carry on while you're away, use tmux on the desktop (in WSL) with a retry loop. The loop exits 0 when it finishes or stops on patience or budget, 3 when it stops on failed runs, and something else when it crashes; any non-zero exit leads to a resume, up to five, ten minutes apart:

```bash
EXP=rsi/experiments/long1
$PY rsi/rsi_experiment.py --iters 40 --parallel 4 --workers 4 --out $EXP || \
  for i in 1 2 3 4 5; do sleep 600; $PY rsi/rsi_experiment.py --resume $EXP && break; done
```

A machine reboot (Windows Update) ends tmux too, so after one, open WSL, start Docker Desktop and run the `--resume` line by hand. On a Mac, start the loop under `caffeinate -i` so the machine doesn't sleep.

### What the experiment folder holds

Everything goes in `rsi/experiments/<date>_<time>/` (or `--out`).

| path | what it is |
|---|---|
| `candidates/h000/harness` | the starting harness; `candidates/hNNN/` holds each proposal, with its harness |
| `runs/<block>/<run tag>/` | solver runs. Blocks are `h000_baseline`, `hNNN_test` and `hNNN_confirm`; each run's `meta.json` labels give its block, pair, arm (candidate or current) and harness |
| `runs/<block>/logs/` | the solver's output for each pair and arm |
| `history.jsonl` | what later updaters see about each attempt |
| `blocks.jsonl` | every block's numbers, the test block's included for a candidate that went on to confirmation |
| `monitor.jsonl`, `summary.md` | for you only: grid M (the hidden monitor) and grid A's held-out runs beside grid B for both arms of every block, with the M - B gap. The over-optimization signal is the candidate's gap rising while its B improves, and the current harness's B from block to block shows drift |
| `cycles.jsonl` | for you only: for every candidate, the earlier harnesses (other than its parent) it returns to, the whole harness by fingerprint or a file it changed by content (trailing whitespace and blank lines ignored). A match with a rejected candidate is a repeated proposal; a match with h000 or an older kept harness is a step back. `summary.md` shows them in its repeats column |
| `config.json`, `state.json`, `loop.log`, `loop.lock` | settings and resumes, where the loop stands, its log, and the lock while it runs |
| `archive.tar.xz`, `archive_manifest.json` | written when the loop ends on its own: every run's `transcript.json` and `checkpoint.json`, and what a leftover sandbox holds beyond unchanged copies of the recordings, packed into one file, with a manifest of sizes and hashes. The scorer's `*_partial.npz` and `*.debug.log` (failed closed-loop tasks only; nothing reads them, and they were most of an experiment's size) are deleted, not packed. `--resume` unpacks the archive first |

Nothing reads `monitor.jsonl`, `cycles.jsonl` or `summary.md` back into the loop.

### Packing a finished experiment

A run's transcript is the one bulky file the loop needs while it runs (the updater reads the best and worst ones), so nothing is packed until the loop ends. When it ends on its own (`--iters`, `--patience`, `--max-usd`), `rsi/experiment_archive.py` packs the bulky per-run files into `archive.tar.xz` and removes them, after reading every file back out of the archive and checking its hash, and deletes the scorer's failure files. Scoring a run's `submission.json` again writes those again if you ever need them. An archive made before this change still holds them; packing it again deletes them. A loop stopped by Ctrl-C, a signal or exit code 3 is left as it is; pack it by hand when you are done with it:

```bash
$PY rsi/experiment_archive.py rsi/experiments/run1              # pack
$PY rsi/experiment_archive.py rsi/experiments/run1 --restore    # unpack
```

Packing by hand is safe whenever the loop is not running. A leftover sandbox keeps only what is not an unchanged copy of its data folder, and the recordings are copied back from that folder on restore, so `--resume` (which unpacks first) carries stopped runs on as before. What stays unpacked (`meta.json`, `submission.json`, `final.md`, the scores, the INFO logs, `candidates/` and the experiment-level files) is what the experiments repository commits; the archive stays on the machine that ran the loop.

## Proposing a candidate by hand

```bash
$PY rsi/harness_proposal.py --runs runs/batch_20261022_101500_haiku_low_clean --harness harness_v0/harness --out rsi/candidates/h002
```

It needs `ANTHROPIC_API_KEY`, and Docker with the solver's image for the smoke run. The updater is Haiku 5.5 at low effort unless `--model` and `--effort` say otherwise, stops after 20 turns (`--max-turns`) or $2 (`--max-usd`), and is priced with `common/api_pricing.py`. Its edits go into a copy of the harness. Paths outside the scope's editable files are refused and the refusal goes back to it as a tool error, as does a `finish` before any edit or before a complete report. The report goes through `write_proposal`, one markdown string with five headings (`evidence`, `root_cause`, `change`, `predicted_effect`, `at_risk`), saved as `proposal.md` beside `harness/`; `finish` takes no arguments and parses that file, naming any heading that is missing, repeated or empty. (Until Oct 22 `finish` took the five fields as separate parameters, and Haiku at low effort kept leaking one parameter's markup into another, then copying its own broken call on every retry.) If it stops without calling `finish`, it gets one reminder.

`--out` gets `harness/` (the candidate, ready for `solver/solver_run.py --harness`), `proposal.md`, `proposal.json`, `diff.patch`, `transcript.json`, and the `context.md` and `context_stats.json` it was given. The report and the manifest parsed from it live in `proposal.md` and `proposal.json`, outside `harness/`, so it doesn't change the candidate's fingerprint. `status` is `ok` only if the candidate passes every check before any solver run.

- Every `.py` in `tools/` compiles, `method.md` is there and not empty, no forbidden device name appears anywhere, and in the tools scope `system.md` is unchanged.
- `tools/check_submission.py` still imports `submission_parser`, directly or through another tool. `tools/submission_parser.py` itself is locked, since the scorer's own copy replaces it in every run.
- A smoke run in the solver's Docker image: the best submission among the runs must pass the candidate's checker on a validation file within 120 s, and an empty submission must be rejected.

The other statuses are `invalid` (a check failed), `no_change`, `no_finish` and `over_budget`. Some things only warn, because a reviewer should look at them but they don't break a run: a new tool that `method.md` never names or that has no docstring, numbers added to `method.md` that are in neither the parent nor the task prompt, and numbers with three or more significant digits added to a tool that appear nowhere in the parent harness or the task prompt. The last two are possible fitted values, the device-specific leak the tools scope forbids. Before a `finish` is accepted, the updater gets one self-test round: the candidate's checker on the best and the worst runs' submissions, run the way the solver runs it, after which it has to call `finish` again (it may rewrite files or its report first). `--no-self-test` skips this. `--smoke local --smoke-python PATH` runs the smoke check without Docker, and `--smoke off` skips it.

## Building a context by hand

```bash
$PY rsi/updater_context.py --runs rsi/tests/fixtures/oct13_clean_batch --harness rsi/tests/fixtures/harness_v0_oct13 --out rsi/previews/oct13_clean
$PY rsi/updater_context.py ... --scope all               # edit-anything scope: system.md becomes editable and the device-generic rule goes
$PY rsi/updater_context.py ... --history history.jsonl   # with earlier attempts
$PY rsi/updater_context.py ... --count-tokens            # exact count from the API, free, needs ANTHROPIC_API_KEY
```

`--runs` takes run folders or batch folders, and the table shows the newest 20 (`--last`). Runs that did not finish (still going, crashed or stopped) are left out, since they say nothing about the harness. The build stops if any run was made with a different harness than `--harness` (it compares the fingerprint in each `meta.json` with the folder's, computed by `common/harness_files.py`), or if the runs mix models, efforts or noise settings. It warns if a run got a different task prompt than today's `solver/task_prompt.md`. It needs only the standard library (`anthropic` only for `--count-tokens`), and it reads the noise sentences, the solver's tool, the output limit and the budget from `solver/solver_run.py` and the forbidden names from `common/hidden_names.py`, so none of them can drift apart.

## What the updater sees

The system prompt is `updater_prompt.md` filled in with the solver's model and effort, the files the scope lets it edit, the device-generic rule (tools scope only), the solver's limits and the range of the current harness's composites. The user message is the system diagram followed by three text blocks.

Part 1 is what the solver is given: the task prompt with its noise sentence, `system.md`, `method.md`, every file in `tools/`, `submission_parser.py` marked locked, the `run_python` tool with its limits, `runs.json` and `dataset.json`. These are the files the next solver run will get.

Part 2 is how the current harness did. It opens with the composite's mean, median, SD and range, failure counts by held-out disturbance and the share of tool calls cut off at 120 s. Then comes a table with one row per run (composite, TD, P / Q TD for each held-out disturbance or "failed", steps, tool calls, timeouts, cost and budget stop), a plain-language note for each failure, and the mean TD where each disturbance didn't fail. After that come every run's final message and the transcripts of the best and the worst run, with each tool output cut to its first and last 1000 characters. The solver's thinking blocks are empty in all ten Oct 13 runs, so the transcripts show its text, code and outputs only.

Part 3 is the earlier attempts, from `history.jsonl`.

## What never goes in

From `score/public.json` the build reads only `score`, `td`, `td_runs` and `failures`. FR, PAR and their entries sit in the same file but are never read. From `meta.json` it reads only `tag`, `model`, `effort`, `harness_sha`, `spent_usd`, `steps`, `tool_calls`, `tool_timeouts`, `budget_stop`, `submission_source` and `noise`, plus `status` to leave out unfinished runs, never `components`, `role_scores` or `score_selection`. It never opens `private.json`. Scorer failure details become plain notes ("B_line: the grid simulation failed at t = 2.28 s"), so tracebacks and simulator messages don't reach the updater.

Two checks back this up. Text the build generates itself (the filled prompt, part 1, the run table and the fields the loop writes into the history) stops the build with a `LeakError` if it contains a hidden name. Those are the FR and PAR field names, fields only `private.json` has, and every grid that isn't a selection grid together with its held-out runs, read from `scorer/config_rsi.json` (`grid_M`, `M_vref`, `M_load`, `M_line`, `grid_A`, `A_test_line_op1`, `A_test_vref_op1`). Text the solver or an earlier updater wrote has the forbidden device names replaced with "[name removed]", and `stats.json` counts them. A coincidental hidden name in solver text, such as a variable called `M_load`, is left alone, since the solver can't know the real ones.

One leak is built into the Oct 17 decision. Because the composite and TD are both shown, anyone who knows the weights can compute $\text{composite} - 0.5\,TD = 0.3\,FR + 0.2\,PAR$ for every run. The updater isn't told the weights, but the task prompt in part 1 says the two linearization checks exist, and with 20 runs it could regress the composite on TD and see how much else moves the score. Hiding this would mean showing TD alone, which drops the number the accept rule actually uses.

## The history file

`history.jsonl` holds one JSON object per attempt, oldest first. `rsi_experiment.py` writes it and `updater_context.py` renders it.

| field | written by | meaning |
|---|---|---|
| `iteration`, `candidate`, `parent` | loop | attempt number, the candidate's folder name, and the harness it was made from |
| `outcome` | loop | `accepted`, `rejected`, `rejected_early`, `reverted` or `invalid` |
| `files_changed` | loop | the paths the attempt wrote or deleted |
| `root_cause`, `change`, `predicted_effect`, `at_risk` | updater | from its `proposal.md`; `evidence` is left out because it cites runs the next updater won't see |
| `n_candidate`, `n_current`, `mean_candidate`, `mean_current`, `se_difference`, `p_value` | loop | the selection-grid composites behind the decision: the confirmation block's for an accepted or reverted candidate, the test block's (its first pairs, if it stopped early) otherwise |
| `td_candidate`, `td_current` | loop | mean TD by held-out disturbance, `{"B_vref": {"P": .., "Q": ..}, ...}` |
| `fail_rate_candidate`, `fail_rate_current` | loop | the share of runs in which each disturbance failed |
| `note` | loop | why a candidate was never run |
| `diff_excerpt` | loop | the diff against the parent, of which the first 1500 characters are shown |

A kept candidate's test-block numbers stay out of the history (they are in `blocks.jsonl`). They are the numbers that got it selected, so they flatter it; the confirmation block's are an honest estimate. Only selection-grid numbers may go into the loop's fields. The build scans them for hidden names, but it can't tell whether a mean came from the right grid, so the loop's own code has to get that right.

## Size

The Oct 13 preview comes to an estimated 54.3k input tokens: 2.0k for the instructions, 16.9k for part 1 (the parser alone is about 8k), 33.4k for part 2 (11.0k of it the final messages and 21.4k the two transcripts) and 2.0k for the diagram. The estimate assumes 2.5 characters a token, which is deliberately high. English prose runs near 3.5 on earlier Claude tokenizers, code and tables of numbers run denser, and Claude 4.7 and later models use a tokenizer that can give up to about 35% more tokens for the same text. The diagram's 2040 comes from the vision docs' patch count for Claude 4.7 and later, $\lceil 1898/28 \rceil \times \lceil 814/28 \rceil = 68 \times 30$. One `--count-tokens` call gives the exact count and the ratio to put in `CHARS_PER_TOKEN`. The counting endpoint is free but rate-limited.

The loop shows 20 runs, so the final messages roughly double, and each attempt adds about 1.1k characters to the history, or 2.7k with a full diff. With 20 runs the fixed part comes to about 66k, so the history fills the 80k budget after roughly 13 attempts with diffs. From then on reductions apply, cheapest first: tool outputs cut to 1000 characters, then 500; only the worst run's transcript; only the last 10, then 5 attempts in full, the older ones as one line each; only the last 10 runs' final messages. `stats.json` lists the ones that applied. The 80k sits under the 100k-token line past which Haiku 5.5 bills the whole request at five times the rate (see `common/api_pricing.py`), with room for the updater's own `write_file` calls. At these prices that costs under a cent a call either way, so the budget is really about how much a small model can attend to.

## Open questions

1. `CHARS_PER_TOKEN` is a guess until the first `--count-tokens` call.
2. Whether the best run's transcript is worth its space. It shows the updater what to keep, but late in the loop it is the first full section to go. I don't know which of the two the updater uses more.
3. At 20 runs the final messages become the largest block, about 22k tokens, more than the two transcripts together. A run's final message averages 2.8k characters, of which the submission JSON is only about 600, so the bulk is the solver's own account of its model. They are the only place the updater sees every run's submitted structure, which it needs to group failures, so they go last. Whether the last 10 would serve as well as all 20, I don't know.
4. The detection table above resamples only ten runs and approximates the permutation test; the first real baseline (20 runs) gives a better spread to redo it with.

Sources: [token counting](https://docs.claude.com/en/docs/build-with-claude/token-counting), [vision](https://docs.claude.com/en/docs/build-with-claude/vision).
