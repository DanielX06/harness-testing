"""The RSI loop from a clean start: fresh baseline runs of the starting harness, then a number of
iterations of propose, fresh solver runs of the candidate, keep or reject.

    python run_rsi.py --iters 5 --reps 4 --parallel 2              # a smoke test: about 2.5 hours
    python run_rsi.py --iters 30 --reps 10 --confirm 20 --parallel 4 --patience 10
    python run_rsi.py --resume experiments/20261020_210000         # carry on after a crash or a stop

Nothing from earlier batches is used: the first context is built from the baseline runs this loop makes.
Each iteration:
  1. propose.py: the updater sees the current harness's runs (newest --last) and the history of earlier
     attempts, edits a copy, and the copy is checked. A candidate that fails a check is never run.
  2. --reps fresh solver runs of the candidate (run_harness.py, scored with --config).
  3. Keep it if its mean composite on the selection grid is lower than the current harness's, by a
     one-sided permutation test at --alpha over all the current harness's runs. With --confirm N, a kept
     candidate gets N more runs and is tested again on all of its runs; if it no longer passes it is reverted.
  4. Stop after --iters iterations, --patience attempts in a row that were not kept, or --max-usd spent.

Resuming. history.jsonl is the record of finished iterations; everything else is rebuilt from it and from the
run folders on disk. An interrupted iteration carries on where it stopped: a saved proposal is reused, scored
runs are kept and only the missing ones are run, and the keep test uses the candidate's first --reps runs, so
it reaches the decision an uninterrupted loop would have. A proposal interrupted before proposal.json was
written is moved to candidates/hNNN.interrupted_<time> and made again (its updater cost is not counted).
Spend is always recomputed from the meta.json and proposal.json files, so nothing is counted twice.
--resume takes only --iters, --patience, --max-usd, --parallel, --workers and --updater-max-usd; the rest
comes from the experiment's config.json, which records each resume. loop.lock stops two loops sharing a folder.

Everything goes in --out (default experiments/<date>_<time>):
    candidates/h000/harness     the starting harness;  candidates/hNNN/  each proposal (propose.py's output)
    runs/hNNN/                  the solver runs of each harness
    history.jsonl               what later updaters are shown about each attempt (selection grid only)
    monitor.jsonl, summary.md   for you, never for the updater: grid M (the hidden monitor) and grid A's
                                held-out runs next to grid B for every block of runs, and the M - B gap
    cycles.jsonl                for you, never for the updater: earlier harnesses each candidate returns to,
                                whole (same harness hash) or file by file (same content, whitespace ignored)
    config.json, state.json, loop.log, loop.lock (while running)
"""
import argparse
import hashlib
import itertools
import json
import math
import os
import random
import shutil
import signal
import socket
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
RESUMABLE = ("iters", "patience", "max_usd", "parallel", "workers", "updater_max_usd")


class Log:
    def __init__(self, path):
        self.f = open(path, "a")

    def __call__(self, *msg):
        line = time.strftime("%H:%M:%S ") + " ".join(str(m) for m in msg)
        print(line, flush=True)
        self.f.write(line + "\n")
        self.f.flush()


def _load(path):
    """JSON from path, or None if it is missing or torn (a crash mid-write)."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _jsonl(path, upto=None):
    """The records of a .jsonl file, skipping a torn last line. With upto, keep only iterations <= upto and
    rewrite the file, so a resumed iteration does not leave a second copy of its line."""
    rows = []
    if os.path.exists(path):
        for line in open(path):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    if upto is not None:
        rows = [r for r in rows if r.get("iteration", 0) <= upto]
        with open(path, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    return rows


# ---- solver runs ----------------------------------------------------------------------------------
def run_block(harness, out, n, a, log):
    """n fresh solver runs of one harness into out/, at most a.parallel at a time. Returns the new run folders.
    If the loop is stopped (an exception, Ctrl-C, SIGTERM or SIGHUP), the runs still going are stopped too, so a
    resumed loop never shares a folder with orphaned runs."""
    os.makedirs(out, exist_ok=True)
    before = set(os.listdir(out))
    cmd = [sys.executable, RUNNER, str(a.model), str(a.effort), "--harness", harness, "--out", out,
           "--config", a.config, "--noise", a.noise] + (["--workers", str(a.workers)] if a.workers else [])
    pending, running, k = n, [], len([f for f in before if f.startswith("rep")])
    try:
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
    finally:
        for p, f, kk in running:
            p.terminate()
        for p, f, kk in running:
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            f.close()
            log(f"   run {kk} of {os.path.basename(out)} stopped before it finished")
    return sorted(os.path.join(out, d) for d in set(os.listdir(out)) - before
                  if os.path.exists(os.path.join(out, d, "meta.json")))


def read_runs(folder):
    """Scored runs under folder, oldest first: composite (selection), td_runs, role scores (private, for the
    monitor only). A run with a missing or torn meta.json or public.json is skipped."""
    out = []
    for d in C._run_dirs([folder]) if os.path.isdir(folder) else []:
        p = _load(os.path.join(d, "score", "public.json"))
        meta = _load(os.path.join(d, "meta.json"))
        if p is None or meta is None:
            continue
        grids = list(p.get("grids", {}).values())
        out.append({"dir": d, "composite": p["score"], "spent": meta.get("spent_usd") or 0.0,
                    "td_runs": {k: v for g in grids for k, v in g.get("td_runs", {}).items()},
                    "roles": meta.get("role_scores") or {}})
    return sorted(out, key=lambda r: os.path.basename(r["dir"]))


def block_spent(folder):
    return sum((_load(os.path.join(d, "meta.json")) or {}).get("spent_usd") or 0.0
               for d in (C._run_dirs([folder]) if os.path.isdir(folder) else []))


def disk_spent(exp):
    """Everything this experiment has spent, from the files: every solver run's meta.json and every saved
    proposal's updater cost."""
    tot = 0.0
    rd, cd = os.path.join(exp, "runs"), os.path.join(exp, "candidates")
    for b in sorted(os.listdir(rd)) if os.path.isdir(rd) else []:
        tot += block_spent(os.path.join(rd, b))
    for c in sorted(os.listdir(cd)) if os.path.isdir(cd) else []:
        p = _load(os.path.join(cd, c, "proposal.json"))
        if p:
            tot += (p.get("updater") or {}).get("spent_usd") or 0.0
    return tot


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


# ---- cycling (for you only) -----------------------------------------------------------------------------
def _content_hash(path):
    """Hash of a file's text with trailing whitespace and blank lines ignored; 'absent' if there is no file."""
    if not os.path.exists(path):
        return "absent"
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return "unreadable"
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def repeats(exp, it, name, parent, prop):
    """Earlier harnesses (other than the parent) this candidate returns to: the whole harness by hash, and each
    file it changed by content. A match with a rejected candidate is a repeated proposal; a match with an older
    kept harness, h000 included, is a step back. Written to cycles.jsonl and summary.md, never to the updater."""
    H = C._runner()["harness_hash"]
    shas = {}
    for j in range(it):
        e = f"h{j:03d}"
        hd = os.path.join(exp, "candidates", e, "harness")
        if e != parent and os.path.isdir(hd):
            shas[e] = H(hd)
    cand = os.path.join(exp, "candidates", name, "harness")
    sha = prop.get("candidate_sha") or (H(cand) if os.path.isdir(cand) else None)
    files = {}
    if os.path.isdir(cand):
        for x in prop.get("files_changed") or []:
            h = _content_hash(os.path.join(cand, x["path"]))
            match = [e for e in shas if _content_hash(os.path.join(exp, "candidates", e, "harness", x["path"])) == h]
            if match:
                files[x["path"]] = match
    return {"iteration": it, "candidate": name, "parent": parent, "harness_sha": sha,
            "same_harness_as": [e for e, s in shas.items() if s == sha], "same_file_as": files}


def repeat_text(c):
    if not c:
        return ""
    parts = ["whole harness = " + ", ".join(c["same_harness_as"])] if c.get("same_harness_as") else []
    parts += [f"{f} = " + ", ".join(hs[-3:]) for f, hs in (c.get("same_file_as") or {}).items()]
    return "; ".join(parts)


# ---- the loop -----------------------------------------------------------------------------------------
def write_summary(exp, rows, a):
    lines = ["# RSI experiment summary (for you, never shown to the updater)", "",
             f"Solver model {a.model} effort {a.effort}, {a.noise} data, scope {a.scope}, {a.reps} runs a candidate"
             f"{f', {a.confirm} confirmation runs' if a.confirm else ''}, alpha {a.alpha}. Grid B is the selection "
             "grid the accept rule uses; M is the hidden monitor; A is grid A's own held-out runs. The over-optimization "
             "signal is the M - B gap rising while B improves. 'Repeats' lists earlier harnesses a candidate returns to "
             "(cycles.jsonl has the full lists).", "",
             "| iter | harness | parent | outcome | runs | B mean | current B mean | p | M mean | M - B gap | A mean | repeats | change |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    f = lambda v, d=3: "-" if v is None else f"{v:.{d}f}"  # noqa: E731
    for r in rows:
        m = r.get("monitor", {})
        lines.append(f"| {r['iteration']} | {r['candidate']} | {r.get('parent', '-')} | {r['outcome']} | "
                     f"{r.get('n_candidate', '-')} | {f(r.get('mean_candidate'))} | {f(r.get('mean_incumbent'))} | "
                     f"{f(r.get('p_value'), 2)} | {f(m.get('monitor'))} | {f(m.get('gap_mean'))} | "
                     f"{f(m.get('train_holdout'))} | {repeat_text(r.get('cycle')).replace('|', '/') or '-'} | "
                     f"{(r.get('change') or r.get('note') or '').replace('|', '/')[:140]} |")
    open(os.path.join(exp, "summary.md"), "w").write("\n".join(lines) + "\n")


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def take_lock(exp):
    """loop.lock holds this process's pid. A live loop on this machine holding it stops a second one."""
    path = os.path.join(exp, "loop.lock")
    old = _load(path)
    if (old and old.get("host") == socket.gethostname() and isinstance(old.get("pid"), int)
            and old["pid"] != os.getpid() and _pid_alive(old["pid"])):
        raise SystemExit(f"{exp} is in use by process {old['pid']} (loop.lock). Stop that loop first; if no loop is "
                         "running (say, after a reboot reused the pid), delete loop.lock.")
    json.dump({"pid": os.getpid(), "host": socket.gethostname(), "since": time.strftime("%Y-%m-%d %H:%M:%S")},
              open(path, "w"))
    return path


def _saved_proposal(cdir, log):
    """The proposal saved for this candidate, or None. A candidate folder without a readable proposal.json was
    interrupted mid-proposal; it is moved aside so propose.py can make the candidate again."""
    if not os.path.exists(cdir):
        return None
    prop = _load(os.path.join(cdir, "proposal.json"))
    if prop and "status" in prop:
        return prop
    aside = cdir + time.strftime(".interrupted_%Y%m%d_%H%M%S")
    os.rename(cdir, aside)
    log(f"   {os.path.basename(cdir)} was interrupted before its proposal was saved; moved to "
        f"{os.path.basename(aside)} (its updater cost is not counted) and proposing again")
    return None


def loop(a, client=None, runner=None):
    runner = runner or run_block
    exp = os.path.abspath(a.out)
    resuming = bool(getattr(a, "resume", False))
    cfg_path = os.path.join(exp, "config.json")
    if resuming:
        old = _load(cfg_path)
        if old is None:
            raise SystemExit(f"nothing to resume in {exp}: no readable config.json")
        changed = {k: getattr(a, k) for k in RESUMABLE if old.get(k) != getattr(a, k)}
        old.update({k: getattr(a, k) for k in RESUMABLE})
        old.setdefault("resumes", []).append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "changed": changed})
    else:
        os.makedirs(exp, exist_ok=False)
        for d in ("candidates", "runs"):
            os.makedirs(os.path.join(exp, d))
    lock = take_lock(exp)
    try:
        if resuming:
            json.dump(old, open(cfg_path, "w"), indent=1)
        else:
            json.dump({k: v for k, v in vars(a).items() if k != "resume"}, open(cfg_path, "w"), indent=1)
        log = Log(os.path.join(exp, "loop.log"))
        if resuming:
            log("resuming" + (f" with {changed}" if changed else ""))
        return _loop(a, exp, log, client, runner, resuming)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def _loop(a, exp, log, client, runner, resuming):
    floor = 1 / math.comb(a.baseline_reps + a.reps, a.reps)     # the smallest p a permutation test can give
    if floor > a.alpha:
        log(f"warning: with {a.reps} candidate runs against {a.baseline_reps} baseline runs the smallest possible "
            f"p is {floor:.3f}, above --alpha {a.alpha}, so no candidate can be kept. Use more --reps.")
    hist_path = os.path.join(exp, "history.jsonl")
    mon_path, cyc_path = os.path.join(exp, "monitor.jsonl"), os.path.join(exp, "cycles.jsonl")
    if resuming:
        hist = _jsonl(hist_path, upto=10 ** 9)                 # drops a torn last line
        if [h.get("iteration") for h in hist] != list(range(1, len(hist) + 1)):
            raise SystemExit(f"history.jsonl in {exp} does not run 1, 2, 3 ...; fix it by hand before resuming")
        _jsonl(mon_path, upto=len(hist))
        _jsonl(cyc_path, upto=len(hist))
    else:
        open(hist_path, "w").close()
        hist = []

    # iteration 0: the starting harness and its baseline runs
    h0 = os.path.join(exp, "candidates", "h000", "harness")
    if not os.path.isdir(h0):
        shutil.copytree(os.path.abspath(a.start), h0, ignore=shutil.ignore_patterns("__pycache__", ".*"))
        for r, _, fs in os.walk(h0):
            os.chmod(r, 0o755)
            for f in fs:
                os.chmod(os.path.join(r, f), 0o644)
    base_dir = os.path.join(exp, "runs", "h000")
    have = len(read_runs(base_dir))
    if have < a.baseline_reps:
        log(f"baseline: {a.baseline_reps - have} runs of {a.start}" + (f" ({have} already scored)" if have else ""))
        runner(h0, base_dir, a.baseline_reps - have, a, log)
    base = read_runs(base_dir)
    if not base:
        log("no baseline run was scored; stopping")
        return exp
    rows = [{"iteration": 0, "candidate": "h000", "outcome": "baseline", "n_candidate": len(base),
             "mean_candidate": statistics.mean(r["composite"] for r in base), "monitor": monitor_stats(base)}]
    if not any(m.get("iteration") == 0 for m in _jsonl(mon_path)):
        with open(mon_path, "a") as f:
            f.write(json.dumps({"iteration": 0, "harness": "h000", "role": "baseline", **rows[0]["monitor"]}) + "\n")
        log(f"baseline mean composite {rows[0]['mean_candidate']:.3f} over {len(base)} runs")

    # the iterations already finished, from history.jsonl
    mons = {m["iteration"]: m for m in _jsonl(mon_path)}
    cycs = {c["iteration"]: c for c in _jsonl(cyc_path)}
    inc, inc_dir, misses = "h000", h0, 0
    for rec in hist:
        row = dict(rec)
        if rec["iteration"] in mons:
            row["monitor"] = {k: v for k, v in mons[rec["iteration"]].items()
                              if k not in ("iteration", "harness", "parent", "outcome")}
        if rec["iteration"] in cycs:
            row["cycle"] = cycs[rec["iteration"]]
        rows.append(row)
        if rec["outcome"] == "accepted":
            inc, inc_dir = rec["candidate"], os.path.join(exp, "candidates", rec["candidate"], "harness")
        misses = 0 if rec["outcome"] == "accepted" else misses + 1
    write_summary(exp, rows, a)
    if resuming:
        log(f"{len(hist)} iterations done; current harness {inc}; {misses} not kept in a row; "
            f"${disk_spent(exp):.2f} spent so far")
    if misses >= a.patience:
        log(f"stopping: {misses} attempts in a row were not kept (--patience {a.patience})")
        return exp

    for it in range(len(hist) + 1, a.iters + 1):
        spent = disk_spent(exp)
        if spent > a.max_usd:
            log(f"stopping: ${spent:.2f} spent, past --max-usd {a.max_usd}")
            break
        name = f"h{it:03d}"
        cdir = os.path.join(exp, "candidates", name)
        inc_runs_dir = os.path.join(exp, "runs", inc)
        prop = _saved_proposal(cdir, log)
        if prop is None:
            log(f"iteration {it}: proposing {name} from {inc}")
            history = C.read_history(hist_path)
            prop = P.propose([inc_runs_dir], inc_dir, cdir, scope=a.scope, history=history, model=a.updater_model,
                             effort=a.updater_effort, max_usd=a.updater_max_usd, smoke=a.smoke,
                             smoke_python=a.smoke_python, client=client, last=a.last, do_self_test=not a.no_self_test)
        else:
            log(f"iteration {it}: resuming {name} from its saved proposal")
        man = prop["manifest"] or {}
        rec = {"iteration": it, "candidate": name, "parent": inc,
               "files_changed": [scrub(x["path"]) for x in prop["files_changed"]],
               **{k: man[k] for k in ("root_cause", "change", "predicted_effect", "at_risk") if k in man},
               "diff_excerpt": open(os.path.join(cdir, "diff.patch")).read() if prop["files_changed"] else None}
        log(f"   {name}: {prop['status']}" + (f": {man.get('change')}" if man.get("change") else ""))
        cyc = repeats(exp, it, name, inc, prop)
        if repeat_text(cyc):
            log(f"   {name} returns to earlier harnesses: {repeat_text(cyc)}")
        if prop["status"] in NOT_RUN:
            reason = {"invalid": "; ".join(prop["errors"]), "no_change": "the updater changed nothing",
                      "no_finish": "the updater did not call finish", "over_budget": "the updater ran past its budget"}
            rec.update(outcome="invalid", note=scrub(reason[prop["status"]])[:600])
            row = dict(rec)
        else:
            cand_dir = os.path.join(cdir, "harness")
            cand_runs_dir = os.path.join(exp, "runs", name)
            have = len(read_runs(cand_runs_dir))
            if have:
                log(f"   {have} runs of {name} already scored")
            if have < a.reps:
                runner(cand_dir, cand_runs_dir, a.reps - have, a, log)
            cand, incr = read_runs(cand_runs_dir)[:a.reps], read_runs(inc_runs_dir)
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
                    need = a.reps + a.confirm - len(read_runs(cand_runs_dir))
                    if need > 0:
                        runner(cand_dir, cand_runs_dir, need, a, log)
                    cand = read_runs(cand_runs_dir)
                    cmp_ = compare(cand, incr)
                    keep = cmp_["mean_candidate"] < cmp_["mean_incumbent"] and cmp_["p_value"] <= a.alpha
                    outcome = "accepted" if keep else "reverted"
                td_c, fail_c = td_means(cand)
                td_i, fail_i = td_means(incr)
                rec.update(outcome=outcome, **cmp_, td_candidate=td_c, td_incumbent=td_i,
                           fail_rate_candidate=fail_c, fail_rate_incumbent=fail_i)
                mon = monitor_stats(cand)
                with open(mon_path, "a") as f:
                    f.write(json.dumps({"iteration": it, "harness": name, "parent": inc, "outcome": outcome, **mon}) + "\n")
                row = dict(rec, monitor=mon)
                log(f"   {name} {outcome}: mean {cmp_['mean_candidate']:.3f} over {cmp_['n_candidate']} runs against "
                    f"{cmp_['mean_incumbent']:.3f} over {cmp_['n_incumbent']}, p = {cmp_['p_value']:.3f}"
                    + (f"; monitor gap {mon['gap_mean']:+.3f}" if mon.get("gap_mean") is not None else ""))
                if outcome == "accepted":
                    inc, inc_dir = name, cand_dir
        with open(cyc_path, "a") as f:
            f.write(json.dumps(dict(cyc, outcome=rec["outcome"])) + "\n")
        with open(hist_path, "a") as f:                       # last: a line here means the iteration is done
            f.write(json.dumps(rec) + "\n")
        rows.append(dict(row, cycle=cyc))
        write_summary(exp, rows, a)
        misses = 0 if rec["outcome"] == "accepted" else misses + 1
        spent = disk_spent(exp)
        json.dump({"iteration": it, "current": inc, "misses_in_a_row": misses, "spent_usd": round(spent, 4)},
                  open(os.path.join(exp, "state.json"), "w"), indent=1)
        log(f"   current harness {inc}; {misses} not kept in a row; ${spent:.2f} spent so far")
        if misses >= a.patience:
            log(f"stopping: {misses} attempts in a row were not kept (--patience {a.patience})")
            break
    log(f"done. current harness {inc} ({os.path.relpath(inc_dir, exp)}); summary in {os.path.join(exp, 'summary.md')}")
    return exp


def parse(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(x == "--resume" or x.startswith("--resume=") for x in argv):
        rp = argparse.ArgumentParser(description="Resume an RSI experiment. Only the settings below can change; "
                                                 "the rest come from the experiment's config.json.")
        rp.add_argument("--resume", required=True, metavar="EXPERIMENT", help="the experiment folder")
        rp.add_argument("--iters", type=int, help="new total number of iterations (to extend a finished run)")
        rp.add_argument("--patience", type=int)
        rp.add_argument("--max-usd", type=float)
        rp.add_argument("--parallel", type=int)
        rp.add_argument("--workers", type=int)
        rp.add_argument("--updater-max-usd", type=float)
        r = rp.parse_args(argv)
        cfg = _load(os.path.join(r.resume, "config.json"))
        if cfg is None:
            rp.error(f"no readable config.json in {r.resume}")
        a = argparse.Namespace(**{k: v for k, v in cfg.items() if k != "resumes"})
        for k in RESUMABLE:
            if getattr(r, k) is not None:
                setattr(a, k, getattr(r, k))
        a.out, a.resume = os.path.abspath(r.resume), True
        return a
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
    ap.add_argument("--resume", metavar="EXPERIMENT", help="carry on an interrupted or finished experiment "
                    "(see the module docstring; takes only --iters, --patience, --max-usd, --parallel, --workers, "
                    "--updater-max-usd)")
    a = ap.parse_args(argv)
    a.baseline_reps = a.baseline_reps or a.reps
    a.out = a.out or os.path.join(HERE, "experiments", time.strftime("%Y%m%d_%H%M%S"))
    a.config = os.path.abspath(a.config)
    a.resume = False
    if a.reps < 2:
        ap.error("--reps must be at least 2")
    return a


def _stop_on_signal(sig, frame):
    raise SystemExit(128 + sig)                                 # so run_block's finally stops its solver runs


if __name__ == "__main__":
    for s in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, _stop_on_signal)
    loop(parse())
