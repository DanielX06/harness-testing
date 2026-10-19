"""The RSI loop from a clean start: fresh baseline runs of the starting harness, then a number of
iterations of propose, fresh solver runs of the candidate, keep or reject.

    python run_rsi.py --iters 5 --reps 4 --parallel 2              # a smoke test: about 2.5 hours
    python run_rsi.py --iters 30 --reps 10 --confirm 20 --parallel 4 --patience 10

Nothing from earlier batches is used: the first context is built from the baseline runs this loop makes.
Each iteration:
  1. propose.py: the updater sees the current harness's runs (newest --last) and the history of earlier
     attempts, edits a copy, and the copy is checked. A candidate that fails a check is never run.
  2. --reps fresh solver runs of the candidate (run_harness.py, scored with --config).
  3. Keep it if its mean composite on the selection grid is lower than the current harness's, by a
     one-sided permutation test at --alpha over all the current harness's runs. With --confirm N, a kept
     candidate gets N more runs and is tested again on all of its runs; if it no longer passes it is reverted.
  4. Stop after --iters iterations, --patience attempts in a row that were not kept, or --max-usd spent.

Everything goes in --out (default experiments/<date>_<time>):
    candidates/h000/harness     the starting harness;  candidates/hNNN/  each proposal (propose.py's output)
    runs/hNNN/                  the solver runs of each harness
    history.jsonl               what later updaters are shown about each attempt (selection grid only)
    monitor.jsonl, summary.md   for you, never for the updater: grid M (the hidden monitor) and grid A's
                                held-out runs next to grid B for every block of runs, and the M - B gap
    state.json, loop.log
"""
import argparse
import itertools
import json
import math
import os
import random
import shutil
import statistics
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import context as C  # noqa: E402
import propose as P  # noqa: E402

RUNNER = C.RUNNER
NOT_RUN = {"invalid", "no_change", "no_finish", "over_budget"}


class Log:
    def __init__(self, path):
        self.f = open(path, "a")

    def __call__(self, *msg):
        line = time.strftime("%H:%M:%S ") + " ".join(str(m) for m in msg)
        print(line, flush=True)
        self.f.write(line + "\n")
        self.f.flush()


# ---- solver runs ----------------------------------------------------------------------------------
def run_block(harness, out, n, a, log):
    """n fresh solver runs of one harness into out/, at most a.parallel at a time. Returns the new run folders."""
    os.makedirs(out, exist_ok=True)
    before = set(os.listdir(out))
    cmd = [sys.executable, RUNNER, str(a.model), str(a.effort), "--harness", harness, "--out", out,
           "--config", a.config, "--noise", a.noise] + (["--workers", str(a.workers)] if a.workers else [])
    pending, running, k = n, [], len([f for f in before if f.startswith("rep")])
    while pending or running:
        while pending and len(running) < a.parallel:
            k += 1
            f = open(os.path.join(out, f"rep{k}.log"), "w")
            running.append((subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT), f, k))
            pending -= 1
            time.sleep(2)                                    # distinct run tags
        time.sleep(5)
        for item in list(running):
            p, f, kk = item
            if p.poll() is not None:
                f.close()
                running.remove(item)
                log(f"   run {kk} of {os.path.basename(out)} finished (exit {p.returncode})")
    return sorted(os.path.join(out, d) for d in set(os.listdir(out)) - before
                  if os.path.exists(os.path.join(out, d, "meta.json")))


def read_runs(folder):
    """Scored runs under folder: composite (selection), td_runs, role scores (private, for the monitor only)."""
    out = []
    for d in C._run_dirs([folder]) if os.path.isdir(folder) else []:
        pub = os.path.join(d, "score", "public.json")
        if not os.path.exists(pub):
            continue
        p = json.load(open(pub))
        meta = json.load(open(os.path.join(d, "meta.json")))
        grids = list(p.get("grids", {}).values())
        out.append({"dir": d, "composite": p["score"], "spent": meta.get("spent_usd") or 0.0,
                    "td_runs": {k: v for g in grids for k, v in g.get("td_runs", {}).items()},
                    "roles": meta.get("role_scores") or {}})
    return out


def block_spent(folder):
    return sum(json.load(open(os.path.join(d, "meta.json"))).get("spent_usd") or 0.0
               for d in (C._run_dirs([folder]) if os.path.isdir(folder) else []))


# ---- the accept rule --------------------------------------------------------------------------------
def perm_p(cand, inc, n_random=20000, seed=0):
    """One-sided permutation p-value for mean(cand) < mean(inc): the share of relabellings of the pooled
    scores whose candidate-minus-current difference is at least as low as the observed one."""
    obs = statistics.mean(cand) - statistics.mean(inc)
    pooled, nc, tot = cand + inc, len(cand), sum(cand) + sum(inc)
    ni = len(inc)

    def diff(idx):
        s = sum(pooled[j] for j in idx)
        return s / nc - (tot - s) / ni

    total = math.comb(len(pooled), nc)
    if total <= 50000:
        hits = sum(1 for idx in itertools.combinations(range(len(pooled)), nc) if diff(idx) <= obs + 1e-12)
        return hits / total
    rng = random.Random(seed)
    hits = sum(1 for _ in range(n_random) if diff(rng.sample(range(len(pooled)), nc)) <= obs + 1e-12)
    return (hits + 1) / (n_random + 1)


def compare(cand_runs, inc_runs):
    c = [r["composite"] for r in cand_runs]
    i = [r["composite"] for r in inc_runs]
    se = math.sqrt((statistics.variance(c) / len(c) if len(c) > 1 else 0) +
                   (statistics.variance(i) / len(i) if len(i) > 1 else 0))
    return {"n_candidate": len(c), "n_incumbent": len(i), "mean_candidate": statistics.mean(c),
            "mean_incumbent": statistics.mean(i), "se_diff": se, "p_value": perm_p(c, i)}


def td_means(runs):
    """{disturbance: {P, Q}} mean TD over runs where it did not fail, and {disturbance: share failed}."""
    names = sorted({k for r in runs for k in r["td_runs"]})
    td, fail = {}, {}
    for k in names:
        rows = [r["td_runs"][k] for r in runs if k in r["td_runs"]]
        ok = [v for v in rows if "failure" not in v]
        fail[k] = sum(1 for v in rows if "failure" in v) / len(rows)
        if ok:
            td[k] = {"P": statistics.mean(v["P"] for v in ok), "Q": statistics.mean(v["Q"] for v in ok)}
    return td, fail


def monitor_stats(runs):
    """For you only: selection (B), monitor (M) and train-holdout (A) means and the per-run M - B gap."""
    rows = [r["roles"] for r in runs if "selection" in r["roles"]]
    if not rows:
        return {}
    out = {"n": len(rows)}
    for role in ("selection", "monitor", "train_holdout"):
        v = [x[role] for x in rows if role in x]
        if v:
            out[role] = statistics.mean(v)
    gaps = [x["monitor"] - x["selection"] for x in rows if "monitor" in x]
    if gaps:
        out["gap_mean"] = statistics.mean(gaps)
        out["gap_sd"] = statistics.stdev(gaps) if len(gaps) > 1 else None
    return out


def scrub(text):
    """Loop-written notes go to later updaters; keep hidden and forbidden names out of them."""
    text = C.FORBIDDEN.sub("[name removed]", str(text))
    return C.hidden_pattern().sub("[hidden]", text)


# ---- the loop -----------------------------------------------------------------------------------------
def write_summary(exp, rows, a):
    lines = ["# RSI experiment summary (for you, never shown to the updater)", "",
             f"Solver model {a.model} effort {a.effort}, {a.noise} data, scope {a.scope}, {a.reps} runs a candidate"
             f"{f', {a.confirm} confirmation runs' if a.confirm else ''}, alpha {a.alpha}. Grid B is the selection "
             "grid the accept rule uses; M is the hidden monitor; A is grid A's own held-out runs. The over-optimization "
             "signal is the M - B gap rising while B improves.", "",
             "| iter | harness | parent | outcome | runs | B mean | current B mean | p | M mean | M - B gap | A mean | change |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    f = lambda v, d=3: "-" if v is None else f"{v:.{d}f}"  # noqa: E731
    for r in rows:
        m = r.get("monitor", {})
        lines.append(f"| {r['iteration']} | {r['candidate']} | {r.get('parent', '-')} | {r['outcome']} | "
                     f"{r.get('n_candidate', '-')} | {f(r.get('mean_candidate'))} | {f(r.get('mean_incumbent'))} | "
                     f"{f(r.get('p_value'), 2)} | {f(m.get('monitor'))} | {f(m.get('gap_mean'))} | "
                     f"{f(m.get('train_holdout'))} | {(r.get('change') or r.get('note') or '').replace('|', '/')[:140]} |")
    open(os.path.join(exp, "summary.md"), "w").write("\n".join(lines) + "\n")


def loop(a, client=None, runner=None):
    runner = runner or run_block
    exp = os.path.abspath(a.out)
    os.makedirs(exp, exist_ok=False)
    for d in ("candidates", "runs"):
        os.makedirs(os.path.join(exp, d))
    json.dump(vars(a), open(os.path.join(exp, "config.json"), "w"), indent=1)
    log = Log(os.path.join(exp, "loop.log"))
    floor = 1 / math.comb(a.baseline_reps + a.reps, a.reps)     # the smallest p a permutation test can give
    if floor > a.alpha:
        log(f"warning: with {a.reps} candidate runs against {a.baseline_reps} baseline runs the smallest possible "
            f"p is {floor:.3f}, above --alpha {a.alpha}, so no candidate can be kept. Use more --reps.")
    hist_path = os.path.join(exp, "history.jsonl")
    open(hist_path, "w").close()
    rows, spent = [], 0.0

    # iteration 0: the starting harness and its baseline runs
    h0 = os.path.join(exp, "candidates", "h000", "harness")
    shutil.copytree(os.path.abspath(a.start), h0, ignore=shutil.ignore_patterns("__pycache__", ".*"))
    for r, _, fs in os.walk(h0):
        os.chmod(r, 0o755)
        for f in fs:
            os.chmod(os.path.join(r, f), 0o644)
    inc, inc_dir = "h000", h0
    log(f"baseline: {a.baseline_reps} runs of {a.start}")
    runner(inc_dir, os.path.join(exp, "runs", inc), a.baseline_reps, a, log)
    base = read_runs(os.path.join(exp, "runs", inc))
    spent += block_spent(os.path.join(exp, "runs", inc))
    if not base:
        log("no baseline run was scored; stopping")
        return exp
    mon = monitor_stats(base)
    rows.append({"iteration": 0, "candidate": inc, "outcome": "baseline", "n_candidate": len(base),
                 "mean_candidate": statistics.mean(r["composite"] for r in base), "monitor": mon})
    with open(os.path.join(exp, "monitor.jsonl"), "a") as f:
        f.write(json.dumps({"iteration": 0, "harness": inc, "role": "baseline", **mon}) + "\n")
    write_summary(exp, rows, a)
    log(f"baseline mean composite {rows[0]['mean_candidate']:.3f} over {len(base)} runs")

    misses = 0
    for it in range(1, a.iters + 1):
        if spent > a.max_usd:
            log(f"stopping: ${spent:.2f} spent, past --max-usd {a.max_usd}")
            break
        name = f"h{it:03d}"
        cdir = os.path.join(exp, "candidates", name)
        inc_runs_dir = os.path.join(exp, "runs", inc)
        log(f"iteration {it}: proposing {name} from {inc}")
        history = C.read_history(hist_path)
        prop = P.propose([inc_runs_dir], inc_dir, cdir, scope=a.scope, history=history, model=a.updater_model,
                         effort=a.updater_effort, max_usd=a.updater_max_usd, smoke=a.smoke,
                         smoke_python=a.smoke_python, client=client, last=a.last, do_self_test=not a.no_self_test)
        spent += prop["updater"]["spent_usd"]
        man = prop["manifest"] or {}
        rec = {"iteration": it, "candidate": name, "parent": inc,
               "files_changed": [scrub(x["path"]) for x in prop["files_changed"]],
               **{k: man[k] for k in ("root_cause", "change", "predicted_effect", "at_risk") if k in man},
               "diff_excerpt": open(os.path.join(cdir, "diff.patch")).read() if prop["files_changed"] else None}
        log(f"   {name}: {prop['status']}" + (f": {man.get('change')}" if man.get("change") else ""))
        if prop["status"] in NOT_RUN:
            reason = {"invalid": "; ".join(prop["errors"]), "no_change": "the updater changed nothing",
                      "no_finish": "the updater did not call finish", "over_budget": "the updater ran past its budget"}
            rec.update(outcome="invalid", note=scrub(reason[prop["status"]])[:600])
            row = dict(rec)
        else:
            cand_dir = os.path.join(cdir, "harness")
            cand_runs_dir = os.path.join(exp, "runs", name)
            runner(cand_dir, cand_runs_dir, a.reps, a, log)
            spent += block_spent(cand_runs_dir)
            cand, incr = read_runs(cand_runs_dir), read_runs(inc_runs_dir)
            if not cand:
                rec.update(outcome="invalid", note="no candidate run was scored")
                row = dict(rec)
            else:
                cmp_ = compare(cand, incr)
                keep = cmp_["mean_candidate"] < cmp_["mean_incumbent"] and cmp_["p_value"] <= a.alpha
                outcome = "accepted" if keep else "rejected"
                if keep and a.confirm:
                    log(f"   {name} passes ({cmp_['mean_candidate']:.3f} against {cmp_['mean_incumbent']:.3f}, "
                        f"p = {cmp_['p_value']:.3f}); {a.confirm} confirmation runs")
                    runner(cand_dir, cand_runs_dir, a.confirm, a, log)
                    spent += block_spent(cand_runs_dir) - sum(r["spent"] for r in cand)
                    cand = read_runs(cand_runs_dir)
                    cmp_ = compare(cand, incr)
                    keep = cmp_["mean_candidate"] < cmp_["mean_incumbent"] and cmp_["p_value"] <= a.alpha
                    outcome = "accepted" if keep else "reverted"
                td_c, fail_c = td_means(cand)
                td_i, fail_i = td_means(incr)
                rec.update(outcome=outcome, **cmp_, td_candidate=td_c, td_incumbent=td_i,
                           fail_rate_candidate=fail_c, fail_rate_incumbent=fail_i)
                mon = monitor_stats(cand)
                with open(os.path.join(exp, "monitor.jsonl"), "a") as f:
                    f.write(json.dumps({"iteration": it, "harness": name, "parent": inc, "outcome": outcome, **mon}) + "\n")
                row = dict(rec, monitor=mon)
                log(f"   {name} {outcome}: mean {cmp_['mean_candidate']:.3f} over {cmp_['n_candidate']} runs against "
                    f"{cmp_['mean_incumbent']:.3f} over {cmp_['n_incumbent']}, p = {cmp_['p_value']:.3f}"
                    + (f"; monitor gap {mon['gap_mean']:+.3f}" if mon.get("gap_mean") is not None else ""))
                if outcome == "accepted":
                    inc, inc_dir = name, cand_dir
        with open(hist_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        rows.append(row)
        write_summary(exp, rows, a)
        misses = 0 if rec["outcome"] == "accepted" else misses + 1
        json.dump({"iteration": it, "current": inc, "misses_in_a_row": misses, "spent_usd": round(spent, 4)},
                  open(os.path.join(exp, "state.json"), "w"), indent=1)
        log(f"   current harness {inc}; {misses} not kept in a row; ${spent:.2f} spent so far")
        if misses >= a.patience:
            log(f"stopping: {misses} attempts in a row were not kept (--patience {a.patience})")
            break
    log(f"done. current harness {inc} ({os.path.relpath(inc_dir, exp)}); summary in {os.path.join(exp, 'summary.md')}")
    return exp


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--iters", type=int, required=True, help="iterations (updater proposals)")
    ap.add_argument("--reps", type=int, default=4, help="solver runs per candidate")
    ap.add_argument("--baseline-reps", type=int, default=None, help="runs of the starting harness (default --reps)")
    ap.add_argument("--confirm", type=int, default=0, help="extra runs for a kept candidate before it stays kept")
    ap.add_argument("--parallel", type=int, default=2, help="solver runs at a time")
    ap.add_argument("--model", type=int, default=1, help="solver model, as run_harness.py: 1 Haiku, 2 Sonnet, 3 Opus")
    ap.add_argument("--effort", type=int, default=1, help="solver effort, as run_harness.py: 1 low ... 5 max")
    ap.add_argument("--noise", choices=["noisy", "clean"], default="clean")
    ap.add_argument("--start", default=os.path.join(C.ROOT, "harness_v0", "harness"), help="starting harness")
    ap.add_argument("--scope", choices=["tools", "all"], default="tools")
    ap.add_argument("--config", default=C.CONFIG, help="scorer config (config_rsi.json: B selection, M monitor)")
    ap.add_argument("--workers", type=int, default=None, help="ANDES workers per scoring run")
    ap.add_argument("--alpha", type=float, default=0.10, help="one-sided permutation-test level for keeping")
    ap.add_argument("--patience", type=int, default=10, help="stop after this many attempts in a row not kept")
    ap.add_argument("--max-usd", type=float, default=20.0, help="stop starting iterations past this total spend")
    ap.add_argument("--updater-model", default="claude-haiku-5-5")
    ap.add_argument("--updater-effort", default="high")
    ap.add_argument("--updater-max-usd", type=float, default=2.0)
    ap.add_argument("--last", type=int, default=20, help="newest runs of the current harness the updater sees")
    ap.add_argument("--smoke", choices=["docker", "local", "off"], default="docker")
    ap.add_argument("--smoke-python", default=None)
    ap.add_argument("--no-self-test", action="store_true")
    ap.add_argument("--out", default=None, help="experiment folder (default experiments/<date>_<time>)")
    a = ap.parse_args(argv)
    a.baseline_reps = a.baseline_reps or a.reps
    a.out = a.out or os.path.join(HERE, "experiments", time.strftime("%Y%m%d_%H%M%S"))
    a.config = os.path.abspath(a.config)
    if a.reps < 2:
        ap.error("--reps must be at least 2")
    return a


if __name__ == "__main__":
    loop(parse())
