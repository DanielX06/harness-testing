# Baselines on harness v0

The solver on `../../harnesses/v0/` with nothing added: how well each model does before any harness work. All scores are the grid B composite (0.5 TD + 0.3 FR + 0.2 PAR, normalized so the flat model scores 1.0, lower is better, a failed run scores 2), from each batch's `summary.md`.

| folder | solver | data | finished runs | grid B mean (SD) | grid M mean | $ a run | v0 fingerprint |
|---|---|---|---|---|---|---|---|
| `2026-10-11_haiku-low_noisy_10runs` | Haiku 5.5 low | noisy | 10 | 0.894 (0.374) | see `analyses/monitor_grid` | 0.02 | f141be203a8a40f4 |
| `2026-10-13_haiku-low_clean_10runs` | Haiku 5.5 low | clean | 10 | 0.884 (0.433) | see `analyses/monitor_grid` | 0.02 | f141be203a8a40f4 |
| `2026-10-17_haiku-low_clean_2runs` | Haiku 5.5 low | clean | 2 | 1.011 (0.393) | see `analyses/monitor_grid` | 0.03 | f141be203a8a40f4 |
| `2026-10-20_1125_opus-high_clean_1run` | Opus 5.5 high | clean | 1 | 0.057 | 0.085 | 4.37 | f141be203a8a40f4 |
| `2026-10-20_1802_opus-high_clean_1run` | Opus 5.5 high | clean | 1 | 0.264 | 0.385 | 4.89 | f141be203a8a40f4 |
| `2026-10-25_opus-low_clean_10runs` | Opus 5.5 low | clean | 10 | 0.492 (0.321) | 0.632 | 0.76 | 9a035ad12d528ea0 |
| `2026-10-30_opus-high_clean_10runs` | Opus 5.5 high | clean | 10 | 0.208 (0.105) | 0.308 | 6.73 | 9a035ad12d528ea0 |
| `2026-10-11_early_checks` | Haiku 5.5 low | | 1 | 0.714 | | | f141be203a8a40f4 |

Notes:

- f141be203a8a40f4 is v0 before the Oct 22 file renames. The checker prints the same thing on every saved submission, so the two fingerprints are the same harness in practice (`../../harnesses/v0/README.md`).
- The Oct 20 11:25 batch started two runs; the second (`aadf`) left only a transcript.
- The Oct 31 scorer fix: before it, a model using tanh, Abs, Min or Max failed with a NameError and scored 2. The Oct 30 batch was scored again on Oct 31, and the 0.208 above is after the fix (some of its runs had scored 2 only because of the bug). Every other batch was scored again on Nov 10 on the desktop and came back unchanged, so none of them had a model the bug hit. Each run's `meta.json` has a `rescored` entry, and its old scores are kept beside the new ones as `score_before_<time>/`.
- `2026-10-11_early_checks` is the first run of the project (`142b`) plus two checker test folders, `check_before` and `check_after`.
- The Haiku batches ran before grid M existed; `../../analyses/monitor_grid/` scores their 22 submissions on M afterwards.
