# Harness wecc_docs_any_grid (Nov 17)

wecc_docs with the two sentences of `system.md` that only held on grid A's layout made general, so the harness is
true on every grid of the random grid pool (`test_cases/build_grid_pool.py`), where the unit can sit in generator
2's, 3's or 4's place and circuits are out. The starting harness for an RSI loop run with `--grid-pool`.

| file | against wecc_docs |
|---|---|
| `harness/system.md` | "Its terminal is bus 3, which connects to bus 9 through its step-up transformer" becomes "Its terminal bus, and the step-up transformer that connects it to the network, are marked on system_diagram.png". The short-circuit study line (about 0.5 pu behind the terminal, SCR about 2, which was grid A's) is replaced by a line saying no study is available, because the strength at the terminal differs from draw to draw and the pool builder does not compute it |
| `harness/method.md` | unchanged |
| `harness/tools/` | unchanged |

Fingerprint 0d24bc7ab69977c1. Losing the short-circuit number is a real difference from run4's h000: a run on this
harness has less information about the network than a run4 run had.
