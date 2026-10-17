"""Sanity checks for the closed-loop scorer. Plain script, no pytest needed.

    python tests/test_scorer.py [--quick] [--config ../config_min.json]

1. flat baseline scores exactly 1.0 on every component
2. true REGF1 written as a submission scores 0 (the ceiling), closed loop in ANDES, including
   runs with staged voltage-reference steps (the scorer steps the submission's Vset)
3. REGF1 with the current loop made ideal scores close to 0
4. true model with wdrp or Qdrp scaled scores worse the further the scale is from 1 (skipped by --quick)
5. invalid submissions, code injection and a timeout each score 2; a destabilising model
   crashes ANDES on every disturbance it sees and never beats flat
Each closed-loop score takes one to three minutes (every held-out run is a full ANDES simulation).
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from score import score_submission            # noqa: E402
from truth import regf1_spec as R             # noqa: E402

BROKEN = {
    "not_json": "{this is not json",
    "unknown_name": json.dumps({"states": {}, "outputs": {"P": "P0 + Kx*(V - V0)", "Q": "Q0"}}),
    "code_injection": json.dumps({"states": {}, "outputs": {"P": "__import__('os').system('echo hi')",
                                                            "Q": "Q0"}}),
    "attribute_access": json.dumps({"states": {}, "outputs": {"P": "P0.real", "Q": "Q0"}}),
    # unstable through the network on any grid: extra Q raises V, which grows x further
    "destabilising": json.dumps({"params": {"a": 5.0},
                                 "states": {"x": {"rhs": "a*x + 10*(V - V0)", "init": "0"}},
                                 "outputs": {"P": "P0", "Q": "Q0 + x"}}),
}


def check(name, cond, msg=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {msg}")
    return bool(cond)


def grid0(pub):
    return next(iter(pub["grids"].values()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(ROOT, "config_min.json"))
    ap.add_argument("--quick", action="store_true", help="skip the sensitivity sweep")
    a = ap.parse_args()
    
    import andes
    andes.config_logger(stream_level=40)
    cfg = json.load(open(a.config))
    case = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(a.config)), cfg["grids"][0]["path"]))
    key = os.path.join(case, "holdout", "answer_key.json")
    tmp = tempfile.mkdtemp(prefix="scorer_test_")
    ok = True
    try:
        print("1. flat baseline")
        pub, priv = score_submission(os.path.join(ROOT, "baselines", "flat.json"), a.config)
        g = grid0(pub)
        ok &= check("flat", all(abs(g[c] - 1.0) < 1e-9 for c in ("td", "fr", "par")),
                    f"td {g['td']} fr {g['fr']} par {g['par']} ({priv['wall_seconds']} s)")

        print("2. true REGF1 (13 states) as a submission: ceiling")
        pub, priv = score_submission(R.write(os.path.join(tmp, "full.json"), key, "full"), a.config)
        g = grid0(pub)
        errs = {r: v for r, v in next(iter(priv["grids"].values()))["terminal_errors"].items()}
        ok &= check("truth", g["score"] < 1e-3, f"score {g['score']} td {g['td']} fr {g['fr']} par {g['par']}; "
                                                 f"V/theta RMSE {errs}")

        print("3. REGF1 with ideal current loop (9 states)")
        pub, _ = score_submission(R.write(os.path.join(tmp, "ideal.json"), key, "ideal"), a.config)
        g = grid0(pub)
        ok &= check("ideal loop", g["score"] < 0.05, f"score {g['score']} td {g['td']} fr {g['fr']} par {g['par']}")

        if not a.quick:
            print("4. sensitivity (true structure, one parameter scaled)")
            kp = json.load(open(key))["params_used"]
            for param in ("wdrp", "Qdrp"):
                rows = []
                for s in (0.8, 1.0, 1.25):
                    p = os.path.join(tmp, f"{param}_{s}.json")
                    json.dump(R.spec(kp, "full", scale={param: s}), open(p, "w"))
                    g = grid0(score_submission(p, a.config)[0])
                    rows.append((s, g["score"], g["td"], g["fr"], g["par"]))
                    print(f"     {param} x{s:<5} score {g['score']:.4f}  td {g['td']:.4f}  fr {g['fr']:.4f}  par {g['par']:.4f}")
                ok &= check(f"{param}", rows[0][1] > rows[1][1] < rows[2][1])

        print("5. failures")
        for name, src in BROKEN.items():
            p = os.path.join(tmp, f"{name}.json")
            open(p, "w").write(src)
            pub, priv = score_submission(p, a.config)
            g = grid0(pub)
            kinds = sorted({f["failure"] for f in g["failures"]})
            if name != "destabilising":
                cond = g["score"] == 2.0
            else:
                # every run with a network disturbance crashes ANDES; a voltage-reference run is a
                # no-op for a model that ignores Vset, so it scores exactly like flat (1.0)
                runs = g["td_runs"].values()
                cond = (any(r.get("failure") in ("tds_failed", "unstable", "nan") for r in runs)
                        and all(min(r["P"], r["Q"]) >= 1.0 for r in runs))
            ok &= check(name, cond, f"score {g['score']} td {g['td']} failures {kinds}")
        fast = dict(cfg, run_timeout_s=3.0)
        for e in fast["grids"]:
            e["path"] = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(a.config)), e["path"]))
        fpath = os.path.join(tmp, "fast.json")
        json.dump(fast, open(fpath, "w"))
        g = grid0(score_submission(os.path.join(ROOT, "baselines", "flat.json"), fpath)[0])
        ok &= check("timeout", g["td"] == 2.0 and {f["failure"] for f in g["failures"]} == {"timeout"},
                    f"td {g['td']} failures {[f['failure'] for f in g['failures']]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
