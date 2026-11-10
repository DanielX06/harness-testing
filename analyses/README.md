# Analyses

One-off studies on saved runs. Each folder has its script and a `results.md`.

| folder | question | answer, in short |
|---|---|---|
| `monitor_grid/` | how do the 22 Oct 11 to 17 Haiku-low v0 submissions score on grid M, the hidden monitor added after they ran? | M ranks them as B does (Pearson 0.98); B is harsher on crashes, M on the voltage loop |
| `qv_gain/` | does the size of a submission's fast Q-V gain decide whether grid B's line trip crashes? Two saved submissions (8b47, dc99) with the gain swept, then with a droop added | lowering the gain stops the crash but barely moves the grid B score (`results.md`, `results_droop.md`) |
