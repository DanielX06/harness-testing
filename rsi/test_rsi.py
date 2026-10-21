"""End-to-end check of run_rsi.py with a scripted fake updater and a fake solver (copies of real Oct 13 runs,
re-stamped with the harness that "made" them). No API call, no Docker, no ANDES.

    python test_rsi.py [--smoke-python PATH]
"""
import argparse
import json
import os
import random
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace as NS

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import context as C  # noqa: E402
import run_rsi as L  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--smoke-python", default=sys.executable)
args = ap.parse_args()
BATCH = os.path.join(C.ROOT, "harness_v0", "runs", "batch_20261013_095747_m1e1_clean")
tmp = tempfile.mkdtemp(prefix="rsi_loop_test_")
ok = 0


def check(cond, what):
    global ok
    if not cond:
        raise AssertionError(what)
    ok += 1
    print("ok:", what)


# the cloud copy has no grid A CSVs; stand one in for the validation file (as in test_propose.py)
_val = sorted(v["file"] for v in json.load(open(os.path.join(C.DATA_DIRS["clean"], "runs.json"))).values()
              if v["split"] == "val")[0]
if not os.path.exists(os.path.join(C.DATA_DIRS["clean"], _val)):
    stand = os.path.join(tmp, "data_clean")
    shutil.copytree(C.DATA_DIRS["clean"], stand)
    os.makedirs(os.path.join(stand, "val"), exist_ok=True)
    shutil.copy(os.path.join(C.ROOT, "test_cases", "grid_A", "holdout", "A_test_vref_op1_clean.csv"),
                os.path.join(stand, _val))
    C.DATA_DIRS["clean"] = stand

SOURCES = sorted(os.path.join(BATCH, d) for d in os.listdir(BATCH) if os.path.isdir(os.path.join(BATCH, d)))
rng = random.Random(1)
H = C._runner()["harness_hash"]
_tag = [0]


def fake_runner(harness, out, n, a, log):
    """n 'runs': real run folders re-stamped with this harness; halved scores if it has the new tool."""
    os.makedirs(out, exist_ok=True)
    better = os.path.exists(os.path.join(harness, "tools", "closed_loop_check.py"))
    made = []
    for _ in range(n):
        src = rng.choice(SOURCES)
        rng.getrandbits(16)                       # keeps the sampled sources as they were before the counter
        _tag[0] += 1                              # tags sort in run order, as real ones do (runs start 2 s apart)
        tag = time.strftime("%Y%m%d_%H%M%S") + f"_haiku_low_{_tag[0]:04x}"
        d = os.path.join(out, tag)
        shutil.copytree(src, d)
        meta = json.load(open(os.path.join(d, "meta.json")))
        pub = json.load(open(os.path.join(d, "score", "public.json")))
        s = pub["score"] * (0.5 if better else 1.0)
        pub["score"] = s
        meta.update(tag=tag, harness=harness, harness_sha=H(harness), spent_usd=0.02,
                    role_scores={"selection": s, "monitor": s + (0.2 if better else 0.05), "train_holdout": s + 0.1})
        json.dump(meta, open(os.path.join(d, "meta.json"), "w"))
        json.dump(pub, open(os.path.join(d, "score", "public.json"), "w"))
        made.append(d)
    log(f"   fake runner: {n} runs of {os.path.basename(os.path.dirname(harness))}")
    return made


class FakeClient:
    def __init__(self, script):
        self.script, self.requests, self.messages = list(script), [], self

    def stream(self, **kw):
        self.requests.append(kw)
        r = self.script.pop(0)

        class S:
            def __enter__(s):
                return s

            def __exit__(s, *e):
                return False

            def get_final_message(s):
                return r
        return S()


U = NS(input_tokens=20000, output_tokens=3000, cache_read_input_tokens=0, cache_creation_input_tokens=0)
_n = [0]


def use(name, **inp):
    _n[0] += 1
    return NS(type="tool_use", id=f"t{_n[0]}", name=name, input=inp)


def reply(*b, stop="tool_use"):
    return NS(content=list(b), stop_reason=stop, usage=U)


FIN = dict(evidence="B_line fails often.", root_cause="No closed-loop check.", change="Added a closed-loop check.",
           predicted_effect="Fewer B_line failures.", at_risk="Extra steps.")
TOOL = '"""Check.\n\n    python tools/closed_loop_check.py submission.json\n"""\nprint("ok")\n'
METHOD = open(os.path.join(C.ROOT, "harness_v0", "harness", "method.md")).read().rstrip() + \
    "\n8. Run python tools/closed_loop_check.py submission.json before submitting.\n"
script = [
    # iteration 1: a good change; the self-test shows its checker, then it submits
    reply(use("write_file", path="tools/closed_loop_check.py", content=TOOL),
          use("write_file", path="method.md", content=METHOD), use("finish", **FIN)),
    reply(use("finish", **FIN)),
    # iteration 2: a forbidden name, so never run
    reply(use("write_file", path="method.md", content=METHOD + "It is a GFM unit.\n"), use("finish", **FIN)),
    reply(use("finish", **FIN)),
    # iteration 3: a change that does nothing for the score (no new tool), so rejected
    reply(use("write_file", path="method.md", content=METHOD + "9. Be careful.\n"), use("finish", **FIN)),
    reply(use("finish", **FIN)),
]
client = FakeClient(script)
exp = os.path.join(tmp, "exp")
a = L.parse(["--iters", "3", "--reps", "4", "--smoke", "local", "--smoke-python", args.smoke_python, "--out", exp])
L.loop(a, client=client, runner=fake_runner)

hist = [json.loads(l) for l in open(os.path.join(exp, "history.jsonl"))]
check([h["outcome"] for h in hist] == ["accepted", "invalid", "rejected"], f"outcomes {[h['outcome'] for h in hist]}")
check(hist[0]["mean_candidate"] < hist[0]["mean_incumbent"] and hist[0]["p_value"] <= 0.10, "h001 kept on the evidence")
ctx3 = open(os.path.join(exp, "candidates", "h003", "context.md")).read()
check("[name removed]" in hist[1]["note"] and "GFM" not in hist[1]["note"] and "GFM" not in ctx3 and
      "Attempt 2: h002 from h001, never run" in ctx3, "invalid note is scrubbed, and the next updater never sees the name")
check(hist[2]["parent"] == "h001" and hist[1]["parent"] == "h001", "later attempts build on the kept harness")
state = json.load(open(os.path.join(exp, "state.json")))
check(state["current"] == "h001" and state["misses_in_a_row"] == 2, "state: current h001, two misses in a row")
ctx2 = open(os.path.join(exp, "candidates", "h002", "context.md")).read()
check(f"Current harness {H(os.path.join(exp, 'candidates', 'h001', 'harness'))}" in ctx2 and
      "Attempt 1: h001 from h000, kept" in ctx2, "iteration 2's updater sees h001's runs and attempt 1 in its history")
ctx1 = open(os.path.join(exp, "candidates", "h001", "context.md")).read()
check("No earlier attempts" in ctx1 and "4 most recent of its 4 runs" in ctx1, "iteration 1 starts from the baseline only")
text = open(os.path.join(exp, "history.jsonl")).read() + ctx2
check(C.hidden_pattern().search(text) is None and "gap_mean" not in text and "monitor" not in ctx2.lower().split("part 2")[1][:5000],
      "no monitor numbers reach the history or the context")
mon = [json.loads(l) for l in open(os.path.join(exp, "monitor.jsonl"))]
check([m["harness"] for m in mon] == ["h000", "h001", "h003"] and mon[1]["gap_mean"] > mon[0]["gap_mean"],
      "monitor.jsonl tracks the M - B gap for every block")
summ = open(os.path.join(exp, "summary.md")).read()
check(summ.count("\n| ") == 5 and "| 1 | h001 | h000 | accepted |" in summ, "summary.md has the baseline and three iterations")
check(not client.script, "every scripted updater reply was used (self-test rounds included)")

# patience stops the loop
client = FakeClient([reply(use("write_file", path="method.md", content=METHOD + "x\n"), use("finish", **FIN)),
                     reply(use("finish", **FIN))] * 2)
exp2 = os.path.join(tmp, "exp2")
L.loop(L.parse(["--iters", "5", "--reps", "2", "--patience", "2", "--smoke", "local", "--smoke-python",
                args.smoke_python, "--out", exp2]), client=client, runner=fake_runner)
check(len(open(os.path.join(exp2, "history.jsonl")).readlines()) == 2, "--patience 2 stops after two misses")

# crash and resume: a crash in the middle of h001's confirmation runs, then one in the middle of h002's proposal
class Crash(Exception):
    pass


calls = {}


def crashing_runner(harness, out, n, a, log):
    """Crashes on the second block into runs/h001 (its confirmation runs) after making 2 of them."""
    b = os.path.basename(out)
    calls[b] = calls.get(b, 0) + 1
    if b == "h001" and calls[b] == 2:
        fake_runner(harness, out, 2, a, log)
        raise Crash("simulated crash during confirmation runs")
    return fake_runner(harness, out, n, a, log)


GOOD = [reply(use("write_file", path="tools/closed_loop_check.py", content=TOOL),
              use("write_file", path="method.md", content=METHOD), use("finish", **FIN)), reply(use("finish", **FIN))]
CAREFUL = [reply(use("write_file", path="method.md", content=METHOD + "9. Be careful.\n"), use("finish", **FIN)),
           reply(use("finish", **FIN))]
exp3 = os.path.join(tmp, "exp3")
argv3 = ["--iters", "3", "--reps", "4", "--confirm", "4", "--patience", "5", "--smoke", "local",
         "--smoke-python", args.smoke_python, "--out", exp3]
try:
    L.loop(L.parse(argv3), client=FakeClient(GOOD), runner=crashing_runner)
    crashed = False
except Crash:
    crashed = True
runs_h001 = L.read_runs(os.path.join(exp3, "runs", "h001"))
check(crashed and not os.path.exists(os.path.join(exp3, "loop.lock")) and len(runs_h001) == 6 and
      open(os.path.join(exp3, "history.jsonl")).read() == "",
      "crash 1: lock released, h001 has 4 + 2 runs, no iteration recorded")
first4 = [r["dir"] for r in runs_h001[:4]]

# a live loop on this machine holding the lock stops a resume
json.dump({"pid": os.getppid(), "host": L.socket.gethostname()}, open(os.path.join(exp3, "loop.lock"), "w"))
try:
    L.loop(L.parse(["--resume", exp3]), client=FakeClient([]), runner=fake_runner)
    refused = False
except SystemExit as e:
    refused = "loop.lock" in str(e)
check(refused, "a resume refuses a folder another live loop holds")
os.remove(os.path.join(exp3, "loop.lock"))

# resume 1: finishes h001 from its saved proposal (2 more confirmation runs), then crashes inside h002's proposal
try:
    L.loop(L.parse(["--resume", exp3]), client=FakeClient(CAREFUL[:1]), runner=fake_runner)
    crashed = False
except IndexError:                                             # the scripted updater runs out mid-proposal
    crashed = True
hist = [json.loads(l) for l in open(os.path.join(exp3, "history.jsonl"))]
h1 = L.read_runs(os.path.join(exp3, "runs", "h001"))
fresh_mean = sum(r["composite"] for r in h1[4:8]) / 4
check(crashed and [h["outcome"] for h in hist] == ["accepted"] and hist[0]["n_candidate"] == 4 and len(h1) == 8
      and hist[0]["first_pass"]["n_candidate"] == 4 and abs(hist[0]["mean_candidate"] - fresh_mean) < 1e-12
      and [r["dir"] for r in h1[:4]] == first4,
      "resume 1: h001 kept on 4 runs, then confirmed on its 4 new runs alone; first 4 runs unchanged, no proposal remade")
check(os.path.isdir(os.path.join(exp3, "candidates", "h002")) and
      not os.path.exists(os.path.join(exp3, "candidates", "h002", "proposal.json")),
      "crash 2: h002 left without a proposal.json")

# resume 2: h002 is remade, then h003 proposes exactly what h002 did
L.loop(L.parse(["--resume", exp3, "--iters", "3"]), client=FakeClient(CAREFUL + CAREFUL), runner=fake_runner)
hist = [json.loads(l) for l in open(os.path.join(exp3, "history.jsonl"))]
check([h["outcome"] for h in hist] == ["accepted", "rejected", "rejected"] and [h["iteration"] for h in hist] == [1, 2, 3],
      f"resume 2: outcomes {[h['outcome'] for h in hist]}, iterations 1 to 3 once each")
check(any(d.startswith("h002.interrupted_") for d in os.listdir(os.path.join(exp3, "candidates"))),
      "the interrupted h002 was moved aside and made again")
mon = [json.loads(l) for l in open(os.path.join(exp3, "monitor.jsonl"))]
check([m["harness"] for m in mon] == ["h000", "h001", "h002", "h003"], "monitor.jsonl has one line per block, no repeats")
cyc = [json.loads(l) for l in open(os.path.join(exp3, "cycles.jsonl"))]
check([c["candidate"] for c in cyc] == ["h001", "h002", "h003"] and cyc[2]["same_harness_as"] == ["h002"] and
      cyc[2]["same_file_as"] == {"method.md": ["h002"]} and not cyc[1]["same_harness_as"] and not cyc[0]["same_file_as"],
      "cycles.jsonl: h003 is the same harness as the rejected h002")
summ = open(os.path.join(exp3, "summary.md")).read()
ctx3 = open(os.path.join(exp3, "candidates", "h003", "context.md")).read()
check("whole harness = h002" in summ and "same_harness_as" not in ctx3 and "cycles" not in ctx3,
      "the repeat shows in summary.md and never in the updater's context")
state = json.load(open(os.path.join(exp3, "state.json")))
n_runs = sum(len(L.read_runs(os.path.join(exp3, "runs", h))) for h in ("h000", "h001", "h002", "h003"))
upd = sum(json.load(open(os.path.join(exp3, "candidates", h, "proposal.json")))["updater"]["spent_usd"]
          for h in ("h001", "h002", "h003"))
check(abs(state["spent_usd"] - (0.02 * n_runs + upd)) < 1e-3 and n_runs == 4 + 8 + 4 + 4,
      f"spend is counted once from the files (${state['spent_usd']:.3f}, {n_runs} runs)")
cfg = json.load(open(os.path.join(exp3, "config.json")))
check(len(cfg["resumes"]) == 2 and cfg["resumes"][1]["changed"] == {} and cfg["reps"] == 4 and cfg["confirm"] == 4
      and not os.path.exists(os.path.join(exp3, "loop.lock")),
      "config.json records both resumes and keeps the original settings")

# resuming a finished experiment does nothing; --iters extends it
n_before = len(open(os.path.join(exp3, "history.jsonl")).readlines())
L.loop(L.parse(["--resume", exp3]), client=FakeClient([]), runner=fake_runner)
check(len(open(os.path.join(exp3, "history.jsonl")).readlines()) == n_before, "resuming a finished run changes nothing")
L.loop(L.parse(["--resume", exp3, "--iters", "4"]), client=FakeClient(CAREFUL), runner=fake_runner)
cyc = [json.loads(l) for l in open(os.path.join(exp3, "cycles.jsonl"))]
check(len(open(os.path.join(exp3, "history.jsonl")).readlines()) == 4 and cyc[3]["same_harness_as"] == ["h002", "h003"],
      "--iters 4 adds one iteration, and a third identical proposal matches both earlier ones")
try:
    L.parse(["--resume", exp3, "--reps", "10"])
    took = True
except SystemExit:
    took = False
check(not took, "--resume refuses settings that would change the experiment (--reps)")

# the confirmation test sees only the new runs: a candidate whose first runs are good and whose
# confirmation runs are bad is reverted, and the record holds the confirmation runs' numbers
seen = {}


def fading_runner(harness, out, n, a, log):
    """The candidate's first block is the good harness's; every confirmation run scores exactly the
    baseline's mean, so it is no better."""
    b = os.path.basename(out)
    seen[b] = seen.get(b, 0) + 1
    made = fake_runner(harness, out, n, a, log)
    if b != "h000" and seen[b] > 1:
        base = [r["composite"] for r in L.read_runs(os.path.join(os.path.dirname(out), "h000"))]
        for d in made:
            f = os.path.join(d, "score", "public.json")
            pub = json.load(open(f))
            pub["score"] = sum(base) / len(base)
            json.dump(pub, open(f, "w"))
    return made


exp4 = os.path.join(tmp, "exp4")
L.loop(L.parse(["--iters", "1", "--reps", "6", "--baseline-reps", "4", "--confirm", "2", "--smoke", "local", "--smoke-python",
                args.smoke_python, "--out", exp4]), client=FakeClient(GOOD), runner=fading_runner)
hist = [json.loads(l) for l in open(os.path.join(exp4, "history.jsonl"))]
h1 = L.read_runs(os.path.join(exp4, "runs", "h001"))
pooled = L.compare(h1, L.read_runs(os.path.join(exp4, "runs", "h000")))
check(pooled["mean_candidate"] < pooled["mean_incumbent"] and pooled["p_value"] <= 0.10,
      f"the old rule (all 8 runs pooled) would have kept this candidate (p = {pooled['p_value']:.3f})")
check(hist[0]["outcome"] == "reverted" and hist[0]["first_pass"]["p_value"] <= 0.10 and hist[0]["n_candidate"] == 2
      and abs(hist[0]["mean_candidate"] - sum(r["composite"] for r in h1[6:]) / 2) < 1e-12,
      "a candidate that passes on its first runs and not on its confirmation runs alone is reverted")
ctx_fields = set(C.LOOP_FIELDS)
check("first_pass" not in ctx_fields, "the first-pass numbers stay out of what the updater is shown")

# the budget flags are in CAD; the old USD names still work and mean the same setting
a = L.parse(["--iters", "1", "--max-cad", "40", "--updater-max-cad", "4"])
b = L.parse(["--iters", "1", "--max-usd", "40", "--updater-max-usd", "4"])
r = L.parse(["--resume", exp3, "--max-cad", "55", "--updater-max-cad", "3"])
check(a.max_usd == b.max_usd == 40 and a.updater_max_usd == b.updater_max_usd == 4
      and r.max_usd == 55 and r.updater_max_usd == 3,
      "--max-cad and --updater-max-cad set the budgets, on a new run and on --resume; the old names still work")

# the permutation test
check(abs(L.perm_p([1, 2], [3, 4]) - 1 / 6) < 1e-12 and L.perm_p([3, 4], [1, 2]) == 1.0, "permutation p-values exact")
shutil.rmtree(tmp)
print(f"\nall {ok} checks passed")
