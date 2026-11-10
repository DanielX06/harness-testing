# Harness wecc_docs (the base harness from Nov 10)

v0 plus information, and one checker fix. It is the starting harness for run4 and for the REGF1 and REGF2 baselines. Daniel's rule for it (Nov 9): the base harness gets information only; any tool in the final harness should come from the RSI loop.

| file | against v0 |
|---|---|
| `harness/system.md` | says the unit is grid-forming; adds the short-circuit equivalent at the terminal (about 0.5 pu on 900 MVA, from ladder r1) and the two WECC generic grid-forming models written out as equations with their example values and normal ranges: the droop model (PNNL-35110, Sep 2023, Literature/"WECC - Droop.pdf") and the virtual synchronous machine model (NREL/TP-5D00-90260, Jun 2024, Literature/"WECC - VSM.pdf") |
| `harness/method.md` | unchanged |
| `harness/tools/check_submission.py` | parses the submission and checks that it starts at rest, as before, but no longer replays the recording open loop. The replay diverges on the true REGF1 (ladder r6), so its verdict pushed solvers to detune right models; how to check a model before submitting is left to the loop (option 1 of Nov 9). `open_loop_replay.py` is gone with it |

Fingerprint a58ba73badbc54e5. The WECC model names (REGFM_A1, REGFM_B1) are left out of `system.md` on purpose: `common/hidden_names.py` hides every REGF name so nothing points at the simulator's own REGF1 to REGF3.

Two pipeline changes on Nov 10 apply to every harness from then on, v0 included, so compare runs on this harness with v0 runs made after Nov 10, not with the October baselines: `solver/task_prompt.md` no longer describes the checker's replay and says `submission.json` is what gets scored, and `solver/solver_run.py` scores the sandbox's `submission.json` before the final message's copy.

How the transcription was checked: every equation was read off the specifications' block diagrams (Figures 3 and 4 of the droop model, Figures 2 to 7 of the VSM model) and the steady-state droops were derived from them. One thing in the VSM specification is ambiguous and is flagged in `system.md`: the unit of the washout corner wD, listed as 50 pu.
