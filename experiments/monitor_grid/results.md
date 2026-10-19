# The 22 v0 calibration runs scored on grid M (Oct 17)

Every submission from the three v0 batches (Haiku 5.5 at low effort: `batch_20261011_182645_m1e1` noisy, `batch_20261013_095747_m1e1_clean` and `batch_20261017_153512_m1e1_clean`) scored on grid M alone, closed loop, with `config_min.json`'s settings. No agent was re-run: a submission is pure data, so this is exactly what `config_rsi.json` would have recorded at run time. Grid B and grid A held-out scores come from each run's own `score/` files. Per-run components are in `runs_on_M.json`; `python score_runs_on_M.py` regenerates them (it skips runs already in the file).

| run | batch | grid B (selection) | grid M (monitor) | grid A held-out | B runs that failed | M runs that failed |
|---|---|---|---|---|---|---|
| 0665 | 20261011 noisy | 0.437 | 0.574 | 0.674 | - | - |
| 2563 | 20261011 noisy | 0.699 | 0.674 | 0.834 | - | - |
| d52d | 20261011 noisy | 0.733 | 0.645 | 0.756 | line | - |
| d72d | 20261011 noisy | 1.431 | 1.417 | 1.424 | vref, load, line | vref, load, line |
| dc99 | 20261011 noisy | 0.811 | 0.904 | 0.958 | line | - |
| 9191 | 20261011 noisy | 0.723 | 0.700 | 0.863 | - | - |
| 1b40 | 20261011 noisy | 1.337 | 1.432 | 1.458 | line | load, line |
| 1137 | 20261011 noisy | 1.412 | 1.471 | 1.427 | vref, load, line | vref, load, line |
| 606a | 20261011 noisy | 0.450 | 0.569 | 0.717 | - | - |
| 8b47 | 20261011 noisy | 0.912 | 0.984 | 1.039 | line | - |
| 78d1 | 20261013 clean | 0.510 | 0.566 | 0.660 | - | - |
| ef05 | 20261013 clean | 1.505 | 1.524 | 1.510 | vref, load, line | vref, load, line |
| 6cc3 | 20261013 clean | 0.676 | 0.607 | 0.855 | line | - |
| 9dfa | 20261013 clean | 0.899 | 1.012 | 0.982 | line | line |
| 63e2 | 20261013 clean | 1.519 | 1.531 | 1.521 | vref, load, line | vref, load, line |
| b9e3 | 20261013 clean | 1.387 | 1.434 | 1.403 | vref, load, line | vref, line |
| ea6a | 20261013 clean | 0.699 | 0.693 | 0.843 | - | - |
| 6074 | 20261013 clean | 0.502 | 0.586 | 0.659 | - | - |
| e1c7 | 20261013 clean | 0.369 | 0.526 | 0.506 | - | - |
| 79c9 | 20261013 clean | 0.777 | 0.701 | 0.808 | line | - |
| 142c | 20261017 clean (desktop) | 0.733 | 0.861 | 0.926 | - | - |
| 5bfb | 20261017 clean (desktop) | 1.290 | 1.397 | 1.365 | vref, line | load, line |

## What it shows

M ranks the v0 runs the way B does. Over the 22 runs B averages 0.900 (SD 0.386) and M 0.946 (SD 0.382), with a Pearson correlation of 0.98 (Spearman 0.98). Grid A's held-out runs track both just as closely (0.99 with B).

B is the harsher grid on crashes, M on the voltage loop. 13 runs fail somewhere on B against 8 on M, and every B failure includes B_line. Of the 7 runs that fail only B_line, 5 run cleanly on M. Six of the eight runs that fail on M also fail two or more of B's three runs. The deliberately wrong models in `../../test_cases/monitor_check.json` show the reverse for a 30% low voltage-loop gain, which saturates two of M's runs and one of B's.

The paired gap is the number to watch in an RSI run. Per run, $d = M - B$ averages $\bar d = +0.045$ with $s_d = 0.073$. Because the two scores come from the same submission, most of the run-to-run spread cancels. Over $n$ runs the standard error of the mean gap is

$$SE(\bar d) = \frac{s_d}{\sqrt{n}}$$

$$SE(\bar d) = \frac{0.073}{\sqrt{22}}$$

$$SE(\bar d) = \frac{0.073}{4.69}$$

$$SE(\bar d) = 0.016$$

The level of M alone carries the full run-to-run SD of 0.38, so the gap is roughly five times less noisy for the same runs ($0.38 / 0.073 \approx 5.2$). Comparing two harnesses with 20 runs each, the standard error of the change in mean gap is

$$SE(\Delta\bar d) = s_d\sqrt{\tfrac{1}{20} + \tfrac{1}{20}}$$

$$SE(\Delta\bar d) = 0.073\sqrt{0.1}$$

$$SE(\Delta\bar d) = 0.073(0.316)$$

$$SE(\Delta\bar d) = 0.023$$

so a harness whose gap has grown by 0.05 over v0's is about two standard errors out. A rising gap while B improves is the over-optimization signal. This assumes the gap's spread stays near v0's as the harness changes, which the RSI log should check.

Two caveats. These are 22 runs of one harness, so the 0.98 correlation says M and B agree on what v0 gets wrong. It doesn't yet say they will agree on what a tuned harness gets wrong, and that is the point of having M. Also, the M − B gap is not zero at v0 (+0.045), so later gaps have to be compared with v0's, not with zero.
