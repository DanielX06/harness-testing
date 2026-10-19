"""Score finished harness runs on grid M (the hidden monitor) without re-running the agent.

    python score_runs_on_M.py                            # every run under harness_v0/runs/batch_*
    python score_runs_on_M.py ../../harness_v0/runs/batch_20261013_095747_m1e1_clean --workers 4

A submission is pure data, so scoring it on a grid added later gives exactly what config_rsi.json
would have given at run time. Writes runs_on_M.json here (resumable: runs already in it are skipped)
and prints grid B against grid M per run. Run folders themselves are left untouched.
"""
import argparse
import glob
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))                     # Harness_testing
SCORER = os.path.join(ROOT, "scorer")
sys.path.insert(0, SCORER)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batches", nargs="*", help="batch folders (default: all of harness_v0/runs/batch_*)")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--out", default=os.path.join(HERE, "runs_on_M.json"))
    a = ap.parse_args()

    import andes
    import numpy as np
    from score import score_submission
    andes.config_logger(stream_level=40)

    base = json.load(open(os.path.join(SCORER, "config_min.json")))
    cfg = {k: v for k, v in base.items() if k not in ("_note", "grids")}
    cfg["grids"] = [{"name": "grid_M", "role": "monitor", "format": "kundur_family_v1",
                     "path": os.path.join(ROOT, "test_cases", "grid_M")}]
    cpath = os.path.join(tempfile.mkdtemp(prefix="on_M_"), "config.json")
    json.dump(cfg, open(cpath, "w"))

    batches = a.batches or sorted(glob.glob(os.path.join(ROOT, "harness_v0", "runs", "batch_*")))
    res = json.load(open(a.out)) if os.path.exists(a.out) else {}
    for b in batches:
        for run in sorted(glob.glob(os.path.join(b, "2*", "submission.json"))):
            d = os.path.dirname(run)
            tag = os.path.basename(d)
            if tag in res:
                continue
            _, priv = score_submission(run, cpath, n_workers=a.workers)
            g = priv["grids"]["grid_M"]
            pub_b = os.path.join(d, "score", "public.json")
            b_score = json.load(open(pub_b))["score"] if os.path.exists(pub_b) else None
            res[tag] = {"batch": os.path.basename(b), "grid_B": b_score,
                        "grid_M": {k: g.get(k) for k in ("score", "td", "fr", "par", "td_runs", "failures")}}
            json.dump(res, open(a.out, "w"), indent=1)
            print(f"{tag}  B {b_score}  M {g['score']}  M failures {[f['task'] for f in g.get('failures', [])]}",
                  flush=True)

    pairs = [(v["grid_B"], v["grid_M"]["score"]) for v in res.values() if v["grid_B"] is not None]
    if len(pairs) > 2:
        B, M = np.array(pairs).T
        print(f"{len(pairs)} runs: B mean {B.mean():.3f} (std {B.std(ddof=1):.3f}), "
              f"M mean {M.mean():.3f} (std {M.std(ddof=1):.3f}), correlation {np.corrcoef(B, M)[0, 1]:.2f}")


if __name__ == "__main__":
    main()
