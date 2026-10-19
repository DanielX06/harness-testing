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


def fake_runner(harness, out, n, a, log):
    """n 'runs': real run folders re-stamped with this harness; halved scores if it has the new tool."""
    os.makedirs(out, exist_ok=True)
    better = os.path.exists(os.path.join(harness, "tools", "closed_loop_check.py"))
    made = []
    for _ in range(n):
        src = rng.choice(SOURCES)
        tag = time.strftime("%Y%m%d_%H%M%S") + f"_haiku_low_{rng.getrandbits(16):04x}"
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

# the permutation test
check(abs(L.perm_p([1, 2], [3, 4]) - 1 / 6) < 1e-12 and L.perm_p([3, 4], [1, 2]) == 1.0, "permutation p-values exact")
shutil.rmtree(tmp)
print(f"\nall {ok} checks passed")
