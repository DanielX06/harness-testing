"""Checks for updater_context.py on copies of the Oct 13 clean batch (rsi/tests/fixtures), in a temporary folder.
No API call, no Docker, no ANDES.

    python rsi/tests/test_updater_context.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True
REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPOSITORY_ROOT)
from common.harness_files import harness_fingerprint  # noqa: E402
from rsi.updater_context import LeakError, UpdaterContextBuilder, history_text  # noqa: E402

FIXTURES = os.path.join(REPOSITORY_ROOT, "rsi", "tests", "fixtures")
BATCH = os.path.join(FIXTURES, "oct13_clean_batch")         # ten Haiku-low runs from Oct 13, with their scores
HARNESS = os.path.join(FIXTURES, "harness_v0_oct13")        # the harness those runs used
work = tempfile.mkdtemp(prefix="updater_context_test_")
passed = 0


def check(condition, description):
    global passed
    if not condition:
        raise AssertionError(description)
    passed += 1
    print("ok:", description)


def build(run_paths=(BATCH,), harness=HARNESS, **options):
    return UpdaterContextBuilder(list(run_paths), harness, **options).build()


def copy_batch(name):
    folder = os.path.join(work, name)
    shutil.copytree(BATCH, folder)
    return folder


def edit_json(path, change):
    with open(path) as file:
        content = json.load(file)
    change(content)
    with open(path, "w") as file:
        json.dump(content, file)


# 1. the two scopes
context = build(scope="all")
check("Everything you write must hold" not in context.system_prompt and "{{" not in context.system_prompt,
      "the edit-anything scope drops the device rule and leaves no placeholder")
check("system.md, method.md, and any file" in context.system_prompt, "the edit-anything scope lists system.md as editable")
check("## system.md (editable in this run)" in context.user_content[1]["text"], "part 1 marks system.md editable")
context = build(scope="tools")
check("read-only in this run" in context.system_prompt and "Everything you write must hold" in context.system_prompt,
      "the tools scope keeps the device rule and marks system.md read-only")
check([block["type"] for block in context.user_content] == ["image", "text", "text", "text"], "the image first, then parts 1 to 3")
check({tool["name"] for tool in context.tools} == {"write_file", "delete_file", "write_proposal", "finish"},
      "four updater tools")
check(next(tool for tool in context.tools if tool["name"] == "finish")["input_schema"]["properties"] == {},
      "finish takes no arguments")
check("tools/submission_parser.py (locked" in context.user_content[1]["text"] and "symbolic.py" not in context.system_prompt,
      "the parser is shown as tools/submission_parser.py, locked")

# 2. history: rendering, scrubbing, and a loop-written field carrying a hidden name
attempt = {"iteration": 1, "candidate": "h001", "parent": "h000", "outcome": "rejected",
           "files_changed": ["method.md", "tools/stability_check.py"],
           "root_cause": "The solver never checks GFM-style damping before it submits.",
           "change": "Added tools/stability_check.py and a step in method.md that runs it.",
           "predicted_effect": "B_line failures from 6 of 10 runs to about 3; composite down 0.15.",
           "at_risk": "Runs that already pass may spend steps on the check.",
           "n_candidate": 20, "n_current": 20, "mean_candidate": 0.85, "mean_current": 0.884, "se_difference": 0.11,
           "p_value": 0.38, "td_candidate": {"B_vref": {"P": 0.3, "Q": 0.2}, "B_line": {"P": 1.4, "Q": 0.7}},
           "td_current": {"B_vref": {"P": 0.32, "Q": 0.22}, "B_line": {"P": 1.25, "Q": 0.66}},
           "fail_rate_candidate": {"B_vref": 0.25, "B_line": 0.45}, "fail_rate_current": {"B_vref": 0.3, "B_line": 0.6},
           "diff_excerpt": "--- method.md\n+++ method.md\n@@\n+8. Run python tools/stability_check.py submission.json"}
second = dict(attempt, iteration=2, candidate="h002", outcome="rejected_early", root_cause="x", change="Second change.")
context = build(history=[attempt, second])
part3 = context.user_content[3]["text"]
check("### Attempt 1: h001 from h000, rejected: not better" in part3, "a history heading with its outcome")
check("### Attempt 2: h002 from h000, rejected early" in part3, "an early rejection is named as such")
check("20 runs of the harness it would have replaced, run alongside it (difference -0.034, standard error 0.110, "
      "one-sided p = 0.38)" in part3, "the measured effect, against the current harness's runs from the same block")
check("B_line 45%/60%" in part3, "the failure-rate line")
check("[name removed]-style damping" in part3 and context.stats["names_removed"] == 1,
      "a forbidden word in the updater's own text is removed")
for leaky, name in ((dict(attempt, td_candidate={"M_vref": {"P": 0.3, "Q": 0.2}}, td_current={"M_vref": {"P": 0.3, "Q": 0.2}}),
                     "a monitor-grid run name"),
                    (dict(attempt, note='scored {"fr": 0.4}'), "an fr score")):
    try:
        build(history=[leaky])
        stopped = False
    except LeakError:
        stopped = True
    check(stopped, f"{name} in a field the loop writes stops the build")
records = [dict(attempt, iteration=number, candidate=f"h{number:03d}") for number in range(1, 13)]
text = history_text(records, show_in_full=5)
check(text.count("Root cause given") == 5 and text.count("### Attempt") == 12, "only the last 5 attempts in full")

# 3. a forbidden word in a solver's final message is removed and counted
folder = copy_batch("scrub")
run = sorted(name for name in os.listdir(folder) if os.path.isdir(os.path.join(folder, name)))[0]
with open(os.path.join(folder, run, "final.md"), "a") as file:
    file.write("\nThis looks like an ANDES REGF model, maybe grid-forming.\n")
context = build([folder])
check(context.stats["names_removed"] == 3 and "ANDES" not in context.user_content[2]["text"], "solver text scrubbed (3 names)")

# 4. a hidden grid in public.json stops the build
folder = copy_batch("public_leak")


def add_grid_m(public):
    grid_b = public["grids"]["grid_B"]
    public["grids"]["grid_M"] = {**grid_b, "td_runs": {name.replace("B_", "M_"): value for name, value in grid_b["td_runs"].items()}}


edit_json(os.path.join(folder, run, "score", "public.json"), add_grid_m)
try:
    build([folder])
    stopped = False
except LeakError:
    stopped = True
check(stopped, "grid M in public.json stops the build")

# 5. an invalid submission: nothing ran, so the cells say so
folder = copy_batch("invalid")


def make_invalid(public):
    public["grids"]["grid_B"] = {"score": 2.0, "td": 2.0, "fr": 2.0, "par": 2.0, "failures": [
        {"task": "submission", "failure": "invalid_submission",
         "detail": "Traceback ...\nSubmissionError: unknown symbol 'w'"}]}
    public["score"] = 2.0


edit_json(os.path.join(folder, run, "score", "public.json"), make_invalid)
part2 = build([folder]).user_content[2]["text"]
check(f"| {run[-4:]} | 2.000 | 2.000 | not run | not run | not run |" in part2, "an invalid submission shows not run")
check("the submission was rejected before scoring: SubmissionError: unknown symbol 'w'" in part2, "the invalid submission's note")

# 6. a run that crashed or is still going says nothing about the harness, so it is left out
folder = copy_batch("unfinished")
edit_json(os.path.join(folder, run, "meta.json"), lambda meta: meta.update(status="crashed"))
context = build([folder])
check(run[-4:] not in context.stats["runs_in_table"] and len(context.stats["runs_in_table"]) == 9,
      "a crashed run is not in the table")

# 7. the runs must come from the harness shown
other_harness = os.path.join(work, "harness2")
shutil.copytree(HARNESS, other_harness, ignore=shutil.ignore_patterns("__pycache__"))
os.chmod(os.path.join(other_harness, "method.md"), 0o644)
with open(os.path.join(other_harness, "method.md"), "a") as file:
    file.write("\n8. extra line\n")
try:
    build(harness=other_harness)
    message = ""
except ValueError as error:
    message = str(error)
check("different harness" in message, "a harness mismatch stops the build")
context = build(harness=other_harness, allow_other_harness=True)
check(any("different harness" in warning for warning in context.stats["warnings"]), "allow_other_harness turns it into a warning")
os.makedirs(os.path.join(other_harness, "tools", "__pycache__"))
for junk in (os.path.join("__pycache__", "replay.cpython-313.pyc"), ".DS_Store"):
    with open(os.path.join(other_harness, "tools", junk), "wb") as file:
        file.write(b"\x00\xff junk")
part1 = build(harness=other_harness, allow_other_harness=True).user_content[1]["text"]
check("__pycache__" not in part1 and ".DS_Store" not in part1 and "binary file" not in part1,
      "part 1 skips __pycache__ and dotfiles in tools/")
junk_harness = os.path.join(work, "harness3")
shutil.copytree(HARNESS, junk_harness, ignore=shutil.ignore_patterns("__pycache__"))
for junk in (".DS_Store", os.path.join("tools", ".DS_Store")):
    with open(os.path.join(junk_harness, junk), "wb") as file:
        file.write(b"\x00\xff junk")
check(harness_fingerprint(junk_harness) == harness_fingerprint(HARNESS) == "f141be203a8a40f4",
      "a .DS_Store does not change the harness fingerprint, which is the one the Oct 13 runs recorded")

# 8. the token budget: reductions, in order
seen = []
for budget in (60000, 45000, 40000, 35000, 20000):
    stats = build(token_budget=budget).stats
    seen.append((budget, stats["tokens_est"]["total"], stats["reductions"], stats["warnings"]))
    print("   budget", budget, "->", stats["tokens_est"]["total"], stats["reductions"], stats["warnings"])
check(seen[0][2] == [], "no reductions when it fits")
check(all(total <= budget for budget, total, _, warnings in seen if not warnings), "every result without a warning fits its budget")
check(seen[-1][3] and "still about" in seen[-1][3][-1], "a warning when nothing fits")

# 9. one scored run only: best and worst are the same run, shown once
folder = os.path.join(work, "single")
os.makedirs(folder)
shutil.copytree(os.path.join(BATCH, run), os.path.join(folder, run))
check(build([folder]).user_content[2]["text"].count("run in the table:") == 1, "a single run's transcript appears once")

# 10. the context is what it was before the rewrite, apart from the parser's new name and source
golden = os.path.join(FIXTURES, "context_oct13_before_rewrite.md")
if os.path.exists(golden):
    import re
    with open(golden) as file:
        before = file.read()

    def without_parser(text):
        start = re.search(r"^### tools/(symbolic|submission_parser)\.py.*$", text, re.M).start()
        return text[:start] + text[text.index("## The solver's tool"):]
    instructions_end = before.index("# User message")
    before = before[:instructions_end].replace("symbolic.py", "submission_parser.py") + before[instructions_end:]
    # Oct 22: the report moved from finish's five parameters to write_proposal (rsi/harness_proposal.py says why)
    with open(os.path.join(REPOSITORY_ROOT, "rsi", "updater_prompt.md")) as file:
        output_now = file.read().split("\nOUTPUT\n", 1)[1].strip()
    output_then = before.split("\nOUTPUT\n", 1)[1].split("\n\n", 1)[0].strip()
    check(output_then.startswith("Call write_file") and "Then call finish with:" in output_then,
          "the golden context still has the old OUTPUT section to swap out")
    before = before.replace(output_then, output_now, 1)
    check(without_parser(build().readable_markdown) == without_parser(before),
          "the Oct 13 context is unchanged by the rewrite, apart from the parser and the report layout")

shutil.rmtree(work, ignore_errors=True)
print(f"\nall {passed} checks passed")
