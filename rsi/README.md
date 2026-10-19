# RSI loop

The recursive self-improvement loop for `harness_v0`. An updater model reads how the current harness did and proposes one change, fresh solver runs decide whether the change stays, and the loop repeats. It is built in six steps (plan of Oct 17). Step 1, the runner changes and the hidden monitor grid M, lives in `harness_v0/`, `scorer/` and `test_cases/`. Step 2 is the updater's instructions and the code that assembles everything it sees. Step 3 is one updater call that turns the current harness into a checked candidate. Step 4 is the loop, `run_rsi.py`, which starts clean from harness_v0 and iterates. Steps 5 and 6 (a calibration pool for the accept rule, the long run) come next.

| file | what it is |
|---|---|
| `updater_prompt.md` | the updater's instructions, with placeholders that `context.py` fills |
| `context.py` | builds the updater's system prompt, its one user message and its three tools from a set of runs, the harness folder they used and the history of earlier attempts |
| `test_context.py` | 25 checks on temporary copies of the Oct 13 batch: both scopes, history rendering, scrubbing, every leak check, the budget reductions, and that caches and dotfiles stay out of part 1 and out of the harness hash |
| `propose.py` | one updater call: builds the context, lets the updater edit a copy of the harness, checks the result and writes a candidate folder |
| `test_propose.py` | 29 checks with a scripted fake updater (no API call): refused paths, every check, every status, cost |
| `run_rsi.py` | the loop: fresh baseline runs of harness_v0, then propose, fresh solver runs, keep or reject, for --iters iterations; `--resume` carries on an interrupted experiment |
| `test_rsi.py` | 27 end-to-end checks with a fake updater and a fake solver (re-stamped Oct 13 runs), including a crash during confirmation runs, a crash mid-proposal, both resumes and the cycle record |
| `previews/oct13_clean/` | the context built from the Oct 13 clean batch: `context.md` (readable, with the diagram as a placeholder line) and `stats.json` |

## Building a context

```bash
PY=../../.venv/bin/python
$PY context.py --runs ../harness_v0/runs/batch_20261013_095747_m1e1_clean --harness ../harness_v0/harness --out previews/oct13_clean
$PY context.py ... --scope all               # edit-anything scope: system.md becomes editable and the device-generic rule goes
$PY context.py ... --history history.jsonl   # with earlier attempts
$PY context.py ... --count-tokens            # exact count from the API, free, needs ANTHROPIC_API_KEY
```

`--runs` takes run folders or batch folders, and the table shows the newest 20 (`--last`). The build stops if any of those runs was made with a different harness than `--harness`, comparing the hash in each `meta.json` with the folder's hash computed by `run_harness.py`'s own function, or if they mix models, efforts or noise settings. It warns if a run got a different task prompt than today's `prompt.md`. `context.py` needs only the standard library (`anthropic` only for `--count-tokens`). It reads the noise sentences, the solver's tool, the output limit, the budget and the hash function from `run_harness.py`, and the forbidden-name list from `build_cases.py`, so none of them can drift apart.

From the loop:

```python
from context import build
ctx = build(run_dirs, harness_dir, scope="tools", history=records)
client.messages.create(model="claude-haiku-5-5", system=ctx.system, tools=ctx.tools,
                       messages=[{"role": "user", "content": ctx.content}], ...)
```

`ctx.tools` holds `write_file`, `delete_file` and `finish`. The loop will apply the writes to a copy of the current harness, refuse paths outside the scope's editable files, and stop at `finish`, whose fields are the manifest (evidence, root cause, change, predicted effect, what is at risk).

## Running the loop (step 4)

```bash
$PY run_rsi.py --iters 5 --reps 4 --parallel 2       # smoke test
$PY run_rsi.py --iters 30 --reps 10 --confirm 20 --parallel 4 --patience 10
```

Nothing from earlier batches is used. The loop copies harness_v0 to `candidates/h000`, makes `--baseline-reps` fresh runs of it (default `--reps`), and the first updater sees only those. Each iteration then calls `propose.py` on the current harness's runs and the history, runs the candidate `--reps` times with `run_harness.py` (scored with `config_rsi.json`, so grid M is scored too), and keeps it if its mean composite on grid B is lower by a one-sided permutation test at `--alpha` (0.10) against all of the current harness's runs. With `--confirm N` a kept candidate gets N more runs and is tested again, and reverted if it no longer passes. A candidate that fails `propose.py`'s checks is never run and counts as a miss. It stops at `--iters`, after `--patience` misses in a row (10), or past `--max-usd` (20).

The smallest p a permutation test can give is 1/C(n_candidate + n_current, n_candidate): 1/6 for 2 runs against 2, 1/20 for 3 against 3, 1/70 for 4 against 4. So below 3 runs a side nothing can be kept at α = 0.10, and the loop warns if that's the case.

Everything goes in `experiments/<date>_<time>/` (or `--out`): `candidates/hNNN/` (each proposal, with its harness), `runs/hNNN/` (each harness's solver runs), `history.jsonl` (what later updaters see), `state.json` and `loop.log`. `monitor.jsonl` and `summary.md` are for you only: they put grid M and grid A's held-out runs beside grid B for every block, with the M - B gap, and nothing reads them back into the loop. `cycles.jsonl` is also yours only. For every candidate it lists the earlier harnesses (other than its parent) it returns to: the same whole harness by hash, or the same content for a file it changed, with trailing whitespace and blank lines ignored. A match with a rejected candidate is a repeated proposal; a match with h000 or an older kept harness is a step back. summary.md shows the matches in its `repeats` column.

### Resuming

```bash
$PY run_rsi.py --resume experiments/20261020_210000                # carry on where it stopped
$PY run_rsi.py --resume experiments/20261020_210000 --iters 40     # extend a finished run
```

`history.jsonl` is the record of finished iterations, and a line is written there last, so everything else is rebuilt from it and from the run folders. An interrupted iteration picks up where it stopped. A saved `proposal.json` is reused rather than paid for again. Scored runs are kept and only the missing ones are run. The keep test uses the candidate's first `--reps` runs, so a crash during confirmation runs reaches the same decision as an uninterrupted loop. A proposal cut off before `proposal.json` was written is moved to `candidates/hNNN.interrupted_<time>` and made again; its updater cost (usually about $0.13, at most `--updater-max-usd`) is the one thing not counted. Spend is recomputed from every `meta.json` and `proposal.json` each iteration, so `--max-usd` holds across resumes. `--resume` accepts only `--iters`, `--patience`, `--max-usd`, `--parallel`, `--workers` and `--updater-max-usd`; anything else would change the experiment, and `config.json` records each resume and what it changed.

`loop.lock` holds the running loop's pid, and a second loop on the same machine refuses the folder. After a reboot a stale lock is ignored unless the old pid now belongs to a live process; if the loop refuses a folder you know is idle, delete `loop.lock`. Stopping the loop (Ctrl-C, `kill`, closing its terminal) stops its solver runs as well, so a resumed loop never shares a folder with orphaned runs. The updater client retries API errors 6 times before the loop gives up.

For a run that should survive crashes while you're away, run it inside tmux (WSL on the desktop) with a retry loop. The loop exits 0 when it finishes or stops on patience or budget, and non-zero when it crashes, so only a crash leads to a resume (up to 5, five minutes apart):

```bash
EXP=experiments/long1
$PY run_rsi.py --iters 30 --reps 10 --confirm 20 --parallel 4 --workers 4 --patience 10 --out $EXP || \
  for i in 1 2 3 4 5; do sleep 300; $PY run_rsi.py --resume $EXP && break; done
```

A machine reboot (Windows Update) kills tmux too, so after one, open WSL, start Docker Desktop and run the `--resume` line by hand.

## Proposing a candidate (step 3)

```bash
$PY propose.py --runs ../harness_v0/runs/batch_20261013_095747_m1e1_clean ../harness_v0/runs/batch_20261017_153512_m1e1_clean \
               --harness ../harness_v0/harness --out candidates/h001
```

It needs `ANTHROPIC_API_KEY`, and Docker with the solver's image (`harness-v0-py`) for the smoke run. The updater is Haiku 5.5 at high effort unless `--model` and `--effort` say otherwise, stops after 20 turns (`--max-turns`) or $2 (`--max-usd`), and is priced with `run_harness.py`'s own rates. Its edits go into a copy of the harness. Paths outside the scope's editable files are refused and the refusal goes back to it as a tool error, as does a `finish` before any edit or with an empty manifest field. If it stops without calling `finish`, it gets one reminder.

`--out` gets `harness/` (the candidate, ready for `run_harness.py --harness`), `proposal.json`, `diff.patch`, `transcript.json`, and the `context.md` and `context_stats.json` it was given. The manifest lives in `proposal.json`, outside `harness/`, so it doesn't change the candidate's hash. `status` is `ok` only if the candidate passes every check before any solver run:

- every `.py` in `tools/` compiles, `method.md` is there and not empty, no forbidden device name appears anywhere, and in the tools scope `system.md` is unchanged;
- `tools/check_submission.py` still imports `symbolic`, directly or through another tool;
- a smoke run in the solver's Docker image: the best submission among the runs must pass the candidate's checker on a validation file within 120 s, and an empty submission must be rejected.

The other statuses are `invalid` (a check failed), `no_change`, `no_finish` and `over_budget`. Some things only warn, because a reviewer should look at them but they don't break a run: a new tool that `method.md` never names or that has no docstring, and numbers added to `method.md` that are in neither the parent nor the task prompt (a possible fitted value, the device-specific leak the tools scope forbids). Before a `finish` is accepted, the updater gets one self-test round: the candidate's checker on the best and worst runs' submissions, run the way the solver runs it, after which it has to call `finish` again (h001's screen called the best Oct 13 model unstable, and its updater never ran the tool). `--no-self-test` skips this. `--smoke local --smoke-python PATH` runs the smoke check without Docker, and `--smoke off` skips it.

`python test_propose.py --smoke-python ../../.venv/bin/python` runs the fake-updater checks.

## What the updater sees

The system prompt is `updater_prompt.md` filled in with the solver's model and effort, the files the scope lets it edit, the device-generic rule (tools scope only) and the range of the current harness's composites. The user message is the system diagram followed by three text blocks.

Part 1 is what the solver is given: the task prompt with its noise sentence, `system.md`, `method.md`, every file in `tools/`, `symbolic.py` marked locked, the `run_python` tool with its limits, `runs.json` and `dataset.json`. These are the files the next solver run will get.

Part 2 is how the current harness did. It opens with the composite's mean, median, SD and range, failure counts by held-out disturbance and the share of tool calls cut off at 120 s. Then comes a table with one row per run (composite, TD, P / Q TD for each held-out disturbance or "failed", steps, tool calls, timeouts, cost and budget stop), a plain-language note for each failure, and the mean TD where each disturbance didn't fail. After that come every run's final message and the transcripts of the best and the worst run, with each tool output cut to its first and last 1000 characters. The solver's thinking blocks are empty in all ten Oct 13 runs, so the transcripts show its text, code and outputs only.

Part 3 is the earlier attempts, from `history.jsonl`.

## What never goes in

From `score/public.json` the build reads only `score`, `td`, `td_runs` and `failures`. FR, PAR and their entries sit in the same file but are never read. From `meta.json` it reads only `tag`, `model`, `effort`, `harness_sha`, `spent_usd`, `steps`, `tool_calls`, `tool_timeouts`, `budget_stop`, `submission_source` and `noise`, never `components`, `role_scores` or `score_selection`. It never opens `private.json`. Scorer failure details become plain notes ("B_line: the grid simulation failed at t = 2.28 s"), so tracebacks and simulator messages don't reach the updater.

Two checks back this up. Text the build generates itself (the filled prompt, part 1, the run table and the fields the loop writes into the history) stops the build with a `LeakError` if it contains a hidden name. Those are the FR and PAR field names, fields only `private.json` has, and every grid that isn't a selection grid together with its held-out runs, read from `config_rsi.json` (`grid_M`, `M_vref`, `M_load`, `M_line`, `grid_A`, `A_test_line_op1`, `A_test_vref_op1`). Text the solver or an earlier updater wrote has the forbidden device names replaced with "[name removed]", and `stats.json` counts them. A coincidental hidden name in solver text, such as a variable called `M_load`, is left alone, since the solver can't know the real ones. The Oct 13 preview has no hidden or forbidden name anywhere in it.

One leak is built into the Oct 17 decision. Because the composite and TD are both shown, anyone who knows the weights can compute $\text{composite} - 0.5\,TD = 0.3\,FR + 0.2\,PAR$ for every run. The updater isn't told the weights, but the task prompt in part 1 says the two linearization checks exist, and with 20 runs it could regress the composite on TD and see how much else moves the score. Hiding this would mean showing TD alone, which drops the number the accept rule actually uses.

## The history file

`history.jsonl` holds one JSON object per attempt, oldest first. The loop (step 4) writes it and `context.py` renders it.

| field | written by | meaning |
|---|---|---|
| `iteration`, `candidate`, `parent` | loop | attempt number, the candidate's folder name, and the harness it was made from |
| `outcome` | loop | `accepted`, `rejected`, `rejected_early`, `reverted`, `invalid` or `repeat` |
| `files_changed` | loop | the paths the attempt wrote or deleted |
| `root_cause`, `change`, `predicted_effect`, `at_risk` | updater | from its `finish` call; `evidence` is left out because it cites runs the next updater won't see |
| `n_candidate`, `n_incumbent`, `mean_candidate`, `mean_incumbent`, `se_diff`, `p_value` | loop | the selection-grid composites behind the decision |
| `td_candidate`, `td_incumbent` | loop | mean TD by held-out disturbance, `{"B_vref": {"P": .., "Q": ..}, ...}` |
| `fail_rate_candidate`, `fail_rate_incumbent` | loop | the share of runs in which each disturbance failed |
| `note` | loop | anything else, such as why a candidate was invalid |
| `diff_excerpt` | loop | the diff against the parent, of which the first 1500 characters are shown |

Only selection-grid numbers may go into the loop's fields. The build scans them for hidden names, but it can't tell whether a mean came from the right grid, so the loop's own code has to get that right.

## Size

The Oct 13 preview comes to an estimated 50.8k input tokens: 2.0k for the instructions, 13.4k for part 1, 33.4k for part 2 (11.0k of it the final messages and 21.4k the two transcripts) and 2.0k for the diagram. The estimate assumes 2.5 characters a token, which is deliberately high. English prose runs near 3.5 on earlier Claude tokenizers, code and tables of numbers run denser, and Claude 4.7 and later models use a tokenizer that can give up to about 35% more tokens for the same text. The diagram's 2040 comes from the vision docs' patch count for Claude 4.7 and later, $\lceil 1898/28 \rceil \times \lceil 814/28 \rceil = 68 \times 30$. One `--count-tokens` call on the Mac gives the exact count and the ratio to put in `CHARS_PER_TOKEN`. The counting endpoint is free but rate-limited.

The loop will show 20 runs, so the final messages roughly double, and each attempt adds about 1.1k characters to the history, or 2.7k with a full diff. With 20 runs the fixed part comes to about 62k, so the history fills the 80k budget after roughly 15 attempts with diffs. From then on reductions apply, cheapest first: tool outputs cut to 1000 characters, then 500; only the worst run's transcript; only the last 10, then 5 attempts in full, the older ones as one line each; only the last 10 runs' final messages. `stats.json` lists the ones that applied. The 80k sits under the 100k-token line past which Haiku 5.5 bills the whole request at five times the rate (see `rates()` in `run_harness.py`), with room for the updater's own `write_file` calls. At these prices that costs under a cent a call either way, so the budget is really about how much a small model can attend to.

## Open questions

1. `CHARS_PER_TOKEN` is a guess until the first `--count-tokens` call.
2. Whether the best run's transcript is worth its space. It shows the updater what to keep, but late in the loop it is the first full section to go. I don't know which of the two the updater uses more.
3. At 20 runs the final messages become the largest block, about 22k tokens, more than the two transcripts together. A run's final message averages 2.8k characters, of which the submission JSON is only about 600, so the bulk is the solver's own account of its model. They are the only place the updater sees every run's submitted structure, which it needs to group failures, so they go last. Whether the last 10 would serve as well as all 20, I don't know.

Sources: [token counting](https://docs.claude.com/en/docs/build-with-claude/token-counting), [vision](https://docs.claude.com/en/docs/build-with-claude/vision).
