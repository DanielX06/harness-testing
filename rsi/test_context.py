"""Checks for context.py on copies of the Oct 13 clean batch, in a temporary folder.

    python test_context.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True          # no __pycache__ left next to context.py
RSI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RSI)
import context as C  # noqa: E402

BATCH = os.path.join(C.ROOT, "harness_v0", "runs", "batch_20261013_095747_m1e1_clean")
HARNESS = os.path.join(C.ROOT, "harness_v0", "harness")
tmp = tempfile.mkdtemp(prefix="rsi_context_test_")
ok = 0


def check(cond, what):
    global ok
    if not cond:
        raise AssertionError(what)
    ok += 1
    print("ok:", what)


def copy_batch(name):
    d = os.path.join(tmp, name)
    shutil.copytree(BATCH, d)
    return d


# 1. the edit-anything scope
ctx = C.build([BATCH], HARNESS, scope="all")
check("Everything you write must hold" not in ctx.system and "{{" not in ctx.system, "all scope drops the device rule")
check("system.md, method.md, and any file" in ctx.system, "all scope lists system.md as editable")
check("## system.md (editable in this run)" in ctx.content[1]["text"], "part 1 marks system.md editable")
ctx_t = C.build([BATCH], HARNESS, scope="tools")
check("read-only in this run" in ctx_t.system and "Everything you write must hold" in ctx_t.system,
      "tools scope keeps the device rule and marks system.md read-only")
check([b["type"] for b in ctx_t.content] == ["image", "text", "text", "text"], "image first, then parts 1 to 3")
check({t["name"] for t in ctx_t.tools} == {"write_file", "delete_file", "finish"}, "three updater tools")

# 2. history: rendering, scrubbing, and a loop field carrying a hidden name
base = {"iteration": 1, "candidate": "h001", "parent": "v0", "outcome": "rejected",
        "files_changed": ["method.md", "tools/stability_check.py"],
        "root_cause": "The solver never checks GFM-style damping before it submits.",
        "change": "Added tools/stability_check.py and a step in method.md that runs it.",
        "predicted_effect": "B_line failures from 6 of 10 runs to about 3; composite down 0.15.",
        "at_risk": "Runs that already pass may spend steps on the check.",
        "n_candidate": 20, "n_incumbent": 40, "mean_candidate": 0.85, "mean_incumbent": 0.884,
        "se_diff": 0.11, "p_value": 0.38,
        "td_candidate": {"B_vref": {"P": 0.3, "Q": 0.2}, "B_line": {"P": 1.4, "Q": 0.7}},
        "td_incumbent": {"B_vref": {"P": 0.32, "Q": 0.22}, "B_line": {"P": 1.25, "Q": 0.66}},
        "fail_rate_candidate": {"B_vref": 0.25, "B_line": 0.45}, "fail_rate_incumbent": {"B_vref": 0.3, "B_line": 0.6},
        "diff_excerpt": "--- method.md\n+++ method.md\n@@\n+8. Run python tools/stability_check.py submission.json"}
second = dict(base, iteration=2, candidate="h002", outcome="accepted", root_cause="x", change="Second change.")
ctx = C.build([BATCH], HARNESS, history=[base, second])
p3 = ctx.content[3]["text"]
check("### Attempt 1: h001 from v0, rejected: not better" in p3, "history heading with outcome text")
check("difference -0.034, standard error 0.110, one-sided p = 0.38" in p3, "measured effect line")
check("B_line 45%/60%" in p3, "failure-rate line")
check("[name removed]-style damping" in p3 and ctx.stats["names_removed"] == 1, "forbidden word scrubbed from updater text")
leaky = dict(base, td_candidate={"M_vref": {"P": 0.3, "Q": 0.2}}, td_incumbent={"M_vref": {"P": 0.3, "Q": 0.2}})
try:
    C.build([BATCH], HARNESS, history=[leaky])
    check(False, "a monitor-grid name in a loop field must stop the build")
except C.LeakError as e:
    check("M_vref" in str(e), f"monitor-grid name in a loop field stops the build ({e})")
leaky2 = dict(base, note='scored {"fr": 0.4}')
try:
    C.build([BATCH], HARNESS, history=[leaky2])
    check(False, "an fr field in a loop note must stop the build")
except C.LeakError:
    check(True, "an fr field in a loop note stops the build")
hist = [dict(base, iteration=k, candidate=f"h{k:03d}") for k in range(1, 13)]
part3 = C.render_history(hist, full_last=5)
check(part3.count("Root cause given") == 5 and part3.count("### Attempt") == 12, "only the last 5 attempts in full")

# 3. a forbidden word in a solver's final message is scrubbed and counted
d = copy_batch("scrub")
run = sorted(x for x in os.listdir(d) if os.path.isdir(os.path.join(d, x)))[0]
with open(os.path.join(d, run, "final.md"), "a") as f:
    f.write("\nThis looks like an ANDES REGF model, maybe grid-forming.\n")
ctx = C.build([d], HARNESS)
check(ctx.stats["names_removed"] == 3 and "ANDES" not in ctx.content[2]["text"], "solver text scrubbed (3 names)")

# 4. a hidden grid in public.json stops the build
d = copy_batch("public_leak")
pub = os.path.join(d, run, "score", "public.json")
p = json.load(open(pub))
p["grids"]["grid_M"] = {**p["grids"]["grid_B"],
                        "td_runs": {k.replace("B_", "M_"): v for k, v in p["grids"]["grid_B"]["td_runs"].items()}}
json.dump(p, open(pub, "w"))
try:
    C.build([d], HARNESS)
    check(False, "grid M in public.json must stop the build")
except C.LeakError as e:
    check(True, f"grid M in public.json stops the build ({e})")

# 5. an invalid submission: nothing ran, so the cells say so
d = copy_batch("invalid")
pub = os.path.join(d, run, "score", "public.json")
p = json.load(open(pub))
p["grids"]["grid_B"] = {"score": 2.0, "td": 2.0, "fr": 2.0, "par": 2.0, "failures": [
    {"task": "submission", "failure": "invalid_submission", "detail": "Traceback ...\nSubmissionError: unknown symbol 'w'"}]}
p["score"] = 2.0
json.dump(p, open(pub, "w"))
ctx = C.build([d], HARNESS)
txt = ctx.content[2]["text"]
check(f"| {run[-4:]} | 2.000 | 2.000 | not run | not run | not run |" in txt, "invalid submission shows not run")
check("the submission was rejected before scoring: SubmissionError: unknown symbol 'w'" in txt, "invalid submission note")

# 6. the runs must come from the harness shown
h2 = os.path.join(tmp, "harness2")
shutil.copytree(HARNESS, h2, ignore=shutil.ignore_patterns("__pycache__"))
os.chmod(os.path.join(h2, "method.md"), 0o644)
with open(os.path.join(h2, "method.md"), "a") as f:
    f.write("\n8. extra line\n")
try:
    C.build([BATCH], h2)
    check(False, "a harness mismatch must stop the build")
except ValueError as e:
    check("different harness" in str(e), "harness mismatch stops the build")
ctx = C.build([BATCH], h2, allow_mismatch=True)
check(any("different harness" in w for w in ctx.stats["warnings"]), "--allow-mismatch turns it into a warning")
os.makedirs(os.path.join(h2, "tools", "__pycache__"))
for junk in (os.path.join("__pycache__", "replay.cpython-313.pyc"), ".DS_Store"):
    with open(os.path.join(h2, "tools", junk), "wb") as f:
        f.write(b"\x00\xff junk")
p1 = C.build([BATCH], h2, allow_mismatch=True).content[1]["text"]
check("__pycache__" not in p1 and ".DS_Store" not in p1 and "binary file" not in p1,
      "part 1 skips __pycache__ and dotfiles in tools/")
h3 = os.path.join(tmp, "harness3")
shutil.copytree(HARNESS, h3, ignore=shutil.ignore_patterns("__pycache__"))
for junk in (".DS_Store", os.path.join("tools", ".DS_Store")):
    with open(os.path.join(h3, junk), "wb") as f:
        f.write(b"\x00\xff junk")
H = C._runner()["harness_hash"]
check(H(h3) == H(HARNESS), "a .DS_Store does not change the runner's harness hash")

# 7. budget reductions, in order
seen = []
for b in (60000, 45000, 40000, 35000, 20000):
    s = C.build([BATCH], HARNESS, budget=b).stats
    seen.append((b, s["tokens_est"]["total"], s["reductions"], s["warnings"]))
    print("   budget", b, "->", s["tokens_est"]["total"], s["reductions"], s["warnings"])
check(seen[0][2] == [], "no reductions when it fits")
check(all(t <= b for b, t, _, w in seen if not w), "every result without a warning fits its budget")
check(seen[-1][3] and "still about" in seen[-1][3][-1], "a warning when nothing fits")

# 8. one scored run only: best and worst are the same run, shown once
d = os.path.join(tmp, "single")
os.makedirs(d)
shutil.copytree(os.path.join(BATCH, run), os.path.join(d, run))
ctx = C.build([d], HARNESS)
check(ctx.content[2]["text"].count("run in the table:") == 1, "a single run's transcript appears once")

shutil.rmtree(tmp)
print(f"\nall {ok} checks passed")
