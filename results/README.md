# Results

Every solver run and batch, grouped by the study it was made for. RSI loops keep their own runs and live in `../rsi_loops/` (a separate git repository); one-off studies on saved runs are in `../analyses/`.

| folder | what it holds |
|---|---|
| `v0_baselines/` | batches of the solver on `harnesses/v0` (Oct 11 to 31): Haiku, Opus low and Opus high |
| `information_ladder/` | the information ladder (Oct 31 to Nov 1): the same solver on r0 to r6 |
| `rsi_smoke_tests/` | early tests of the RSI loop's machinery (Oct 18 to 22), not experiments |
| `scorer_reference/` | reference models scored once to check the scorer (the flat model that scores 1.0) |
| `unfiled/` | where new runs land by default; move a finished batch into its study folder |

## How a batch is named and laid out

A batch folder is `<date>_<model>-<effort>_<noise>_<N>runs` (date of the first run). Inside it, `summary.md` is the batch table from `solver/summarize_batch.py`, `batch.json` the settings (newer batches), and one folder per run named `<YYYYMMDD_HHMMSS>_<model>_<effort>_<id>`. A run folder holds `meta.json` (settings, harness fingerprint, cost, scores, and a `rescored` entry if it was scored again), `transcript.json`, `final.md` (the solver's last message), `submission.json`, and `score/` with `public.json` and `private.json` from the scorer. Sandboxes and debug logs are ignored by git and stay on the machine that made the run.

Score again after a scorer fix with `$PY scorer/rescore_runs.py results/<study>/<batch>/2*/ --reason "why"`, then `$PY solver/summarize_batch.py results/<study>/<batch>`.
