# WECC-docs baselines (Nov 10)

The solver on harness v0 and on harness wecc_docs (v0 plus the WECC generic grid-forming equations in system.md), on both training devices, before run4. The wecc_docs harness is run4's starting point (h000). Haiku 5.5 low, clean data, config_rsi (REGF1) or config_rsi_regf2 (REGF2), parallel 2 on the desktop.

| folder | device | harness | runs | selection mean | old name |
|---|---|---|---|---|---|
| `2026-11-10_regf1_v0_haiku-low_clean_10runs` | REGF1 | v0 | 10 | 0.691 | `unfiled/2026-11-10_165202_haiku-low_clean` |
| `2026-11-10_regf1_wecc-docs_haiku-low_clean_10runs` | REGF1 | wecc_docs | 10 | 0.799 | `unfiled/2026-11-10_135630_haiku-low_clean_wecc_docs` |
| `2026-11-10_regf2_v0_haiku-low_clean_10runs` | REGF2 | v0 | 10 | 0.795 | `unfiled/2026-11-10_183452_haiku-low_clean_regf2` |
| `2026-11-10_regf2_wecc-docs_haiku-low_clean_10runs` | REGF2 | wecc_docs | 10 | 0.763 | `unfiled/2026-11-10_223350_haiku-low_clean_regf2_wecc_docs` |

The analysis is in the project doc "Baselines with the WECC docs" (Nov 12).
