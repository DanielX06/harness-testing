# Information ladder results

The solver on rungs r0 (harness v0) to r6, each rung adding one kind of information or tooling (`../../harnesses/information_ladder/README.md` lists them; `../../information_ladder/README.md` is the write-up). Made with `information_ladder/run_ladder.sh`, clean data, `config_rsi`. Each folder has `ladder_summary.md` (one row per rung, from `information_ladder/summarize_ladder.py`) and one folder per rung holding its runs.

| folder | solver | rungs | runs a rung | old name |
|---|---|---|---|---|
| `2026-10-31_haiku-low` | Haiku 5.5 low | r0 to r6 | 10 | `ladder_20261031_233559_haiku_low` |
| `2026-10-31_sonnet-low` | Sonnet 5.5 low | r0, r1 | 5 | `ladder_20261031_231131_sonnet_low` |
| `2026-11-01_haiku-medium` | Haiku 5.5 medium | r0 | 10 | `ladder_20261101_052706_haiku_medium` |
| `smoke_test` | Haiku 5.5 low | | 1 | a single run from 22:48 on Oct 31, before the ladders |

Grid B mean for Haiku low: r0 0.858, r1 0.906, r2 0.720, r3 0.730, r4 0.239, r5 0.310, r6 0.671. Only the block menu with its fitter (r4, r5) made a significant difference (p < 0.001 and 0.003 against r0). The analysis is in the project doc "Information ladder results and why the RSI loop stalls" (Nov 4).
