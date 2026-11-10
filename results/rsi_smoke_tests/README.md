# RSI smoke tests (Oct 18 to 22)

Early tests of the RSI loop's machinery, kept for the record. None of them is an experiment; the real loops are in `../../rsi_loops/`.

| folder | what it was |
|---|---|
| `2026-10-18_first_updater_proposal/` | the first updater proposal (h001, Haiku high), made by hand with `rsi/harness_proposal.py` from the 12 Oct 13 to 17 runs; it added `tools/screen.py` and changed the checker and `method.md` |
| `test_p10/` | a loop test with the pre-restructure code: 10 runs a candidate, one iteration; the updater (Haiku high) never called finish |
| `2026-10-22_1941_loop_smoke_test/` | the first smoke test of `rsi/rsi_experiment.py` with paired blocks (4 pairs, Haiku low updater, 2 iterations); both iterations were invalid because the updater never called finish |
| `2026-10-22_2107_loop_smoke_test/` | the same smoke test rerun that evening after a fix; both candidates (a linearized stability check, a linear screen tool) were rejected early |
