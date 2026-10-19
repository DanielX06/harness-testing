"""Checks for propose.py with a scripted fake updater, in a temporary folder. No API call.

    python test_propose.py                       # smoke runs with this interpreter (needs numpy, pandas, scipy, sympy)
    python test_propose.py --smoke-python PATH   # or with another one
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace as NS

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import context as C  # noqa: E402
import propose as P  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--smoke-python", default=sys.executable)
a = ap.parse_args()
BATCH = os.path.join(C.ROOT, "harness_v0", "runs", "batch_20261013_095747_m1e1_clean")
HARNESS = os.path.join(C.ROOT, "harness_v0", "harness")
tmp = tempfile.mkdtemp(prefix="rsi_propose_test_")
ok = 0


def check(cond, what):
    global ok
    if not cond:
        raise AssertionError(what)
    ok += 1
    print("ok:", what)


class FakeClient:
    """Replays scripted responses; records every request."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.messages = self

    def stream(self, **kw):
        self.requests.append({k: v for k, v in kw.items() if k != "messages"} | {"messages": list(kw["messages"])})
        r = self.script.pop(0)
        return _Stream(r)


class _Stream:
    def __init__(self, r):
        self.r = r

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.r


USAGE = NS(input_tokens=60000, output_tokens=8000, cache_read_input_tokens=0, cache_creation_input_tokens=0)


def reply(*blocks, stop="tool_use"):
    return NS(content=list(blocks), stop_reason=stop, usage=USAGE)


def text(t):
    return NS(type="text", text=t)


_n = [0]


def use(name, **inp):
    _n[0] += 1
    return NS(type="tool_use", id=f"toolu_{_n[0]:03d}", name=name, input=inp)


FINISH = dict(evidence="B_line failed in 6 of 10 runs (6cc3, 9dfa, 79c9, ...).",
              root_cause="Nothing in the harness checks the model closed loop before submission.",
              change="Added tools/closed_loop_check.py and a step in method.md that runs it.",
              predicted_effect="B_line failures down from 6 of 10 to about 3; composite down about 0.1.",
              at_risk="Runs that pass already may use steps on the check.")
NEW_TOOL = '''"""Closed-loop sanity check against a simple equivalent network.

    python tools/closed_loop_check.py submission.json
"""
import sys
import numpy as np


def main(path):
    print("checked", path, np.zeros(1).size)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
'''
METHOD = open(os.path.join(HARNESS, "method.md")).read().rstrip() + \
    "\n8. Before submitting, run python tools/closed_loop_check.py submission.json and fix what it reports.\n"


def run(name, script, **kw):
    client = FakeClient(script)
    out = os.path.join(tmp, name)
    kw.setdefault("smoke", "local")
    kw.setdefault("do_self_test", False)
    p = P.propose([BATCH], HARNESS, out, client=client, smoke_python=a.smoke_python, **kw)
    return p, client, out


# The cloud copy of the repo has no grid A CSVs; there, stand in a held-out recording (same columns) for the
# validation file. On a full checkout this does nothing.
_val = sorted(v["file"] for v in json.load(open(os.path.join(C.DATA_DIRS["clean"], "runs.json"))).values()
              if v["split"] == "val")[0]
if not os.path.exists(os.path.join(C.DATA_DIRS["clean"], _val)):
    stand = os.path.join(tmp, "data_clean")
    shutil.copytree(C.DATA_DIRS["clean"], stand)
    os.makedirs(os.path.join(stand, "val"), exist_ok=True)
    shutil.copy(os.path.join(C.ROOT, "test_cases", "grid_A", "holdout", "A_test_vref_op1_clean.csv"),
                os.path.join(stand, _val))
    C.DATA_DIRS["clean"] = stand
    print("note: no validation CSV in this checkout; using a stand-in for the smoke runs")

parent_sha = C._runner()["harness_hash"](HARNESS)

# 1. a good proposal, with every kind of refused call along the way
p, cl, out = run("good", [
    reply(text("Six of ten runs fail B_line."),
          use("write_file", path="tools/closed_loop_check.py", content=NEW_TOOL),
          use("write_file", path="method.md", content=METHOD),
          use("write_file", path="system.md", content="new facts"),
          use("write_file", path="../escape.py", content="x = 1"),
          use("write_file", path="tools/symbolic.py", content="x = 1"),
          use("delete_file", path="tools/check_submission.py")),
    reply(use("finish", **FINISH), stop="tool_use")])
check(p["status"] == "ok", f"good proposal is ok ({p['errors']})")
check({f["path"]: f["kind"] for f in p["files_changed"]} == {"method.md": "modified", "tools/closed_loop_check.py": "added"},
      "two files changed, as written")
check(len(p["refused"]) == 4 and {r["path"] for r in p["refused"]} ==
      {"system.md", "../escape.py", "tools/symbolic.py", "tools/check_submission.py"}, "four calls refused")
check(p["manifest"]["change"] == FINISH["change"], "manifest taken from finish")
check(p["candidate_sha"] != parent_sha and p["parent_sha"] == parent_sha, "candidate hash differs from the parent's")
check(C._runner()["harness_hash"](HARNESS) == parent_sha, "the parent harness is untouched")
second = cl.requests[1]["messages"][-1]["content"]
check(sum(1 for r in second if r.get("is_error")) == 4 and len(second) == 6, "refusals go back to the updater as errors")
check(cl.requests[0]["tools"] and cl.requests[0]["output_config"] == {"effort": "high"} and cl.requests[0]["system"],
      "system prompt, tools and effort sent")
check(all(s["exit"] == 0 for s in p["smoke"][:1]) and p["smoke"][1]["exit"] != 0, "smoke: valid passes, empty rejected")
diff = open(os.path.join(out, "diff.patch")).read()
check("+8. Before submitting, run python tools/closed_loop_check.py" in diff and "b/tools/closed_loop_check.py" in diff,
      "diff.patch has both changes")
check(os.path.exists(os.path.join(out, "harness", "tools", "check_submission.py")) and
      not os.path.exists(os.path.join(out, "harness", "system.md.bak")), "candidate folder is a full harness")
check(abs(p["updater"]["spent_usd"] - 2 * (60000 * 0.10 + 8000 * 0.50) / 1e6) < 1e-9, "cost at the runner's Haiku rates")
saved = json.load(open(os.path.join(out, "proposal.json")))
check(saved["status"] == "ok" and os.path.exists(os.path.join(out, "transcript.json")), "proposal.json and transcript saved")
tr = json.load(open(os.path.join(out, "transcript.json")))
check(tr["messages"][0]["content"][0] == {"type": "image", "source": "system_diagram.png"}, "transcript drops the image data")

# 2. a checker that no longer uses symbolic.py
p, _, _ = run("no_symbolic", [
    reply(use("write_file", path="tools/check_submission.py", content='"""x"""\nimport sys\nsys.exit(0)\n'),
          use("finish", **FINISH))])
check(p["status"] == "invalid" and any("no longer imports symbolic" in e for e in p["errors"]) and not p["smoke"],
      "checker without symbolic.py is invalid, no smoke run")

# 3. a checker that imports symbolic but accepts anything
p, _, _ = run("accepts_all", [
    reply(use("write_file", path="tools/check_submission.py",
              content='"""python tools/check_submission.py submission.json"""\nimport sys, os\n'
                      'sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\nimport symbolic\nsys.exit(0)\n'),
          use("finish", **FINISH))])
check(p["status"] == "invalid" and any("accepts an empty submission" in e for e in p["errors"]),
      "checker that accepts an empty submission is invalid")

# 4. a syntax error, a forbidden name, and fitted-looking numbers
p, _, _ = run("syntax", [reply(use("write_file", path="tools/bad.py", content="def f(:\n"), use("finish", **FINISH))])
check(p["status"] == "invalid" and any("does not compile" in e for e in p["errors"]), "syntax error is invalid")
p, _, _ = run("forbidden", [reply(use("write_file", path="method.md", content=METHOD + "It is an REGF1 unit.\n"),
                                  use("finish", **FINISH))], smoke="off")
check(p["status"] == "invalid" and any("REGF" in e for e in p["errors"]), "forbidden name is invalid")
p, _, _ = run("numbers", [reply(use("write_file", path="method.md", content=METHOD + "Expect a droop near 0.0616 and Tq 1.85 s.\n"),
                                use("finish", **FINISH))], smoke="off")
check(p["status"] == "ok" and any("0.0616" in w and "1.85" in w for w in p["warnings"]), "fitted-looking numbers warn")
p, _, _ = run("unnamed_tool", [reply(use("write_file", path="tools/helper.py", content='x = 1\n'),
                                     use("finish", **FINISH))], smoke="off")
check(any("not named in method.md" in w for w in p["warnings"]) and any("no docstring" in w for w in p["warnings"]),
      "an unnamed tool without a docstring warns")

# 5. finishing too early, and never finishing
p, cl, _ = run("early_finish", [reply(use("finish", **FINISH)),
                                reply(use("write_file", path="method.md", content=METHOD), use("finish", **FINISH))],
               smoke="off")
check(p["status"] == "ok" and "unchanged" in cl.requests[1]["messages"][-1]["content"][0]["content"],
      "finish before any write is refused, then accepted")
p, _, _ = run("missing_field", [reply(use("write_file", path="method.md", content=METHOD), use("finish", evidence="x")),
                                reply(use("finish", **FINISH))], smoke="off")
check(p["status"] == "ok", "finish missing fields is refused, then accepted")
p, _, _ = run("no_finish", [reply(text("I think the harness is fine."), stop="end_turn"),
                            reply(text("Still fine."), stop="end_turn")], smoke="off")
check(p["status"] == "no_finish" and p["manifest"] is None, "no finish after one nudge")
p, _, _ = run("over_budget", [reply(use("write_file", path="method.md", content=METHOD))], smoke="off", max_usd=0.001)
check(p["status"] == "over_budget", "stops past --max-usd")

# 6. the edit-anything scope allows system.md
p, _, _ = run("scope_all", [reply(use("write_file", path="system.md", content="WHAT IS KNOWN\n- more facts\n"),
                                  use("finish", **FINISH))], smoke="off", scope="all")
check(p["status"] == "ok" and p["files_changed"] == [{"path": "system.md", "kind": "modified"}], "all scope edits system.md")

# 7. the self-test: the first valid finish shows the updater its checker on the best and worst submissions
p, cl, _ = run("self_test", [
    reply(use("write_file", path="tools/closed_loop_check.py", content=NEW_TOOL),
          use("write_file", path="method.md", content=METHOD), use("finish", **FINISH)),
    reply(use("finish", **FINISH))], do_self_test=True)
shown = cl.requests[1]["messages"][-1]["content"][-1]["content"]
check(p["status"] == "ok" and len(cl.requests) == 2, "self-test round, then submitted")
check("Not submitted yet" in shown and "best run e1c7" in shown and "worst run 63e2" in shown
      and "open-loop replay RMSE" in shown, "the updater sees its checker's output on the best and worst runs")
check(len(p["self_test"]) == 2 and all(e["exit"] == 0 for e in p["self_test"]), "self-test log saved")

# 8. an existing --out is never overwritten
try:
    run("good", [])
    check(False, "existing out folder must be refused")
except FileExistsError:
    check(True, "existing out folder is refused")

shutil.rmtree(tmp)
print(f"\nall {ok} checks passed")
