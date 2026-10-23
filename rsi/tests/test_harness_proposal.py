"""Checks for harness_proposal.py with a scripted fake updater, in a temporary folder. No API call, no Docker: the
candidate's checker runs with a local Python (it needs numpy, pandas and sympy).

    python rsi/tests/test_harness_proposal.py
    python rsi/tests/test_harness_proposal.py --smoke-python PATH      # the checker with another interpreter
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace as NS

sys.dont_write_bytecode = True
REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPOSITORY_ROOT)
from common.harness_files import harness_fingerprint, list_harness_files  # noqa: E402
from common.project_paths import STARTING_HARNESS_DIR  # noqa: E402
from rsi.harness_proposal import parse_proposal, proposal_refusal, propose_candidate  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--smoke-python", default=sys.executable)
smoke_python = parser.parse_args().smoke_python
HARNESS = str(STARTING_HARNESS_DIR)
work = tempfile.mkdtemp(prefix="harness_proposal_test_")
passed = 0


def check(condition, description):
    global passed
    if not condition:
        raise AssertionError(description)
    passed += 1
    print("ok:", description)


# The Oct 13 runs, re-stamped as runs of today's starting harness (the updater only reads runs of the harness it edits)
BATCH = os.path.join(work, "batch")
shutil.copytree(os.path.join(REPOSITORY_ROOT, "rsi", "tests", "fixtures", "oct13_clean_batch"), BATCH)
parent_fingerprint = harness_fingerprint(HARNESS)
for name in os.listdir(BATCH):
    meta_path = os.path.join(BATCH, name, "meta.json")
    if not os.path.exists(meta_path):
        continue
    with open(meta_path) as file:
        meta = json.load(file)
    meta.update(harness=HARNESS, harness_sha=parent_fingerprint)
    with open(meta_path, "w") as file:
        json.dump(meta, file)


class FakeClient:
    """Replays scripted responses; records every request."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.messages = self

    def stream(self, **request):
        self.requests.append({**request, "messages": list(request["messages"])})
        return _Stream(self.script.pop(0))


class _Stream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.response


USAGE = NS(input_tokens=60000, output_tokens=8000, cache_read_input_tokens=0, cache_creation_input_tokens=0)
_counter = [0]


def reply(*blocks, stop="tool_use"):
    return NS(content=list(blocks), stop_reason=stop, usage=USAGE)


def text(words):
    return NS(type="text", text=words)


def use(name, **tool_input):
    _counter[0] += 1
    return NS(type="tool_use", id=f"toolu_{_counter[0]:03d}", name=name, input=tool_input)


FIELDS = dict(evidence="B_line failed in 6 of 10 runs (6cc3, 9dfa, 79c9, ...).",
              root_cause="Nothing in the harness checks the model closed loop before submission.",
              change="Added tools/closed_loop_check.py and a step in method.md that runs it.",
              predicted_effect="B_line failures down from 6 of 10 to about 3; composite down about 0.1.",
              at_risk="Runs that pass already may use steps on the check.")


def report_text(fields):
    return "".join(f"## {key}\n{value}\n\n" for key, value in fields.items())


PROPOSAL = report_text(FIELDS)


def finish():
    """The report, then finish with no arguments (one reply's worth of blocks)."""
    return [use("write_proposal", content=PROPOSAL), use("finish")]
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
with open(os.path.join(HARNESS, "method.md")) as file:
    METHOD = file.read().rstrip() + \
        "\n8. Before submitting, run python tools/closed_loop_check.py submission.json and fix what it reports.\n"


def propose(name, script, **options):
    client = FakeClient(script)
    out = os.path.join(work, name)
    options.setdefault("smoke", "local")
    options.setdefault("self_test", False)
    proposal = propose_candidate([BATCH], HARNESS, out, client=client, smoke_python=smoke_python, **options)
    return proposal, client, out


# 1. a good proposal, with every kind of refused call along the way
proposal, client, out = propose("good", [
    reply(text("Six of ten runs fail B_line."),
          use("write_file", path="tools/closed_loop_check.py", content=NEW_TOOL),
          use("write_file", path="method.md", content=METHOD),
          use("write_file", path="system.md", content="new facts"),
          use("write_file", path="../escape.py", content="x = 1"),
          use("write_file", path="tools/submission_parser.py", content="x = 1"),
          use("delete_file", path="tools/check_submission.py")),
    reply(*finish())])
check(proposal["status"] == "ok", f"a good proposal is ok ({proposal['errors']})")
check({changed["path"]: changed["kind"] for changed in proposal["files_changed"]}
      == {"method.md": "modified", "tools/closed_loop_check.py": "added"}, "two files changed, as written")
check({refused["path"] for refused in proposal["refused"]}
      == {"system.md", "../escape.py", "tools/submission_parser.py", "tools/check_submission.py"}, "four calls refused")
check(proposal["manifest"] == FIELDS, "the manifest is parsed from proposal.md")
check(os.path.exists(os.path.join(out, "proposal.md")) and "proposal.md" not in list_harness_files(os.path.join(out, "harness"))
      and "proposal.md" not in {changed["path"] for changed in proposal["files_changed"]},
      "proposal.md sits beside the harness, not in it, so it is not part of the candidate")
check(proposal["candidate_sha"] != parent_fingerprint and proposal["parent_sha"] == parent_fingerprint,
      "the candidate's fingerprint differs from its parent's")
check(harness_fingerprint(HARNESS) == parent_fingerprint, "the parent harness is untouched")
answers = client.requests[1]["messages"][-1]["content"]
check(sum(1 for answer in answers if answer.get("is_error")) == 4 and len(answers) == 6, "refusals go back to the updater as errors")
check(client.requests[0]["tools"] and client.requests[0]["output_config"] == {"effort": "low"} and client.requests[0]["system"],
      "the system prompt, the tools and the default effort (low) are sent")
check(proposal["smoke"][0]["exit"] == 0 and proposal["smoke"][1]["exit"] != 0,
      "smoke run: a valid submission passes the checker, an empty one is rejected")
with open(os.path.join(out, "diff.patch")) as file:
    diff = file.read()
check("+8. Before submitting, run python tools/closed_loop_check.py" in diff and "b/tools/closed_loop_check.py" in diff,
      "diff.patch has both changes")
check(os.path.exists(os.path.join(out, "harness", "tools", "check_submission.py")), "the candidate folder is a full harness")
check(abs(proposal["updater"]["spent_usd"] - 2 * (60000 * 0.10 + 8000 * 0.50) / 1e6) < 1e-9, "cost at Haiku's rates")
with open(os.path.join(out, "proposal.json")) as file:
    saved = json.load(file)
check(saved["status"] == "ok" and os.path.exists(os.path.join(out, "transcript.json")), "proposal.json and the transcript are saved")
with open(os.path.join(out, "transcript.json")) as file:
    transcript = json.load(file)
check(transcript["messages"][0]["content"][0] == {"type": "image", "source": "system_diagram.png"},
      "the transcript drops the image data")

# 2. a checker that no longer uses submission_parser.py
proposal, _, _ = propose("no_parser", [
    reply(use("write_file", path="tools/check_submission.py", content='"""x"""\nimport sys\nsys.exit(0)\n'),
          *finish())])
check(proposal["status"] == "invalid" and any("no longer imports submission_parser" in error for error in proposal["errors"])
      and not proposal["smoke"], "a checker without submission_parser.py is invalid, with no smoke run")

# 3. a checker that imports the parser but accepts anything
proposal, _, _ = propose("accepts_all", [
    reply(use("write_file", path="tools/check_submission.py",
              content='"""python tools/check_submission.py submission.json"""\nimport sys, os\n'
                      'sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\nimport submission_parser\nsys.exit(0)\n'),
          *finish())])
check(proposal["status"] == "invalid" and any("accepts an empty submission" in error for error in proposal["errors"]),
      "a checker that accepts an empty submission is invalid")

# 4. a syntax error, a forbidden name, fitted-looking numbers
proposal, _, _ = propose("syntax", [reply(use("write_file", path="tools/bad.py", content="def f(:\n"), *finish())])
check(proposal["status"] == "invalid" and any("does not compile" in error for error in proposal["errors"]),
      "a syntax error is invalid")
proposal, _, _ = propose("forbidden", [reply(use("write_file", path="method.md", content=METHOD + "It is an REGF1 unit.\n"),
                                             *finish())], smoke="off")
check(proposal["status"] == "invalid" and any("REGF" in error for error in proposal["errors"]), "a forbidden name is invalid")
proposal, _, _ = propose("numbers", [reply(use("write_file", path="method.md",
                                               content=METHOD + "Expect a droop near 0.0616 and Tq 1.85 s.\n"),
                                           *finish())], smoke="off")
check(proposal["status"] == "ok" and any("0.0616" in warning and "1.85" in warning for warning in proposal["warnings"]),
      "fitted-looking numbers in method.md give a warning")
FITTED_TOOL = NEW_TOOL.replace('print("checked", path, np.zeros(1).size)',
                               'droop, time_constant, step = 0.03962, 22.15, 0.5\n    print("checked", path, droop, time_constant, step)')
proposal, _, _ = propose("tool_numbers", [reply(use("write_file", path="tools/closed_loop_check.py", content=FITTED_TOOL),
                                                use("write_file", path="method.md", content=METHOD), *finish())],
                         smoke="off")
tool_warnings = [warning for warning in proposal["warnings"] if warning.startswith("tools/closed_loop_check.py gains numbers")]
check(proposal["status"] == "ok" and tool_warnings and "0.03962" in tool_warnings[0] and "22.15" in tool_warnings[0]
      and "0.5" not in tool_warnings[0].split(":")[-1].split(", "),
      "numbers with three or more significant digits in a tool give a warning; 0.5 does not")
proposal, _, _ = propose("unnamed_tool", [reply(use("write_file", path="tools/helper.py", content='x = 1\n'),
                                                *finish())], smoke="off")
check(any("not named in method.md" in warning for warning in proposal["warnings"])
      and any("no docstring" in warning for warning in proposal["warnings"]), "an unnamed tool without a docstring gives warnings")

# 5. finishing too early, without a complete report, never finishing, and the budget
proposal, client, _ = propose("early_finish", [reply(*finish()),
                                               reply(use("write_file", path="method.md", content=METHOD), *finish())],
                              smoke="off")
check(proposal["status"] == "ok" and "unchanged" in client.requests[1]["messages"][-1]["content"][-1]["content"],
      "a finish before any write is refused, then accepted")
proposal, client, _ = propose("no_report", [reply(use("write_file", path="method.md", content=METHOD), use("finish")),
                                             reply(*finish())], smoke="off")
refusal = client.requests[1]["messages"][-1]["content"][-1]["content"]
check(proposal["status"] == "ok" and "no proposal.md yet" in refusal and "## root_cause" in refusal,
      "a finish before any report is refused with the layout to use, then accepted")
INCOMPLETE = PROPOSAL.split("## at_risk")[0] + "## change\nAgain.\n## evidence\n\n"
proposal, client, _ = propose("bad_report", [
    reply(use("write_file", path="method.md", content=METHOD), use("write_proposal", content=INCOMPLETE), use("finish")),
    reply(*finish())], smoke="off")
written, refusal = [block["content"] for block in client.requests[1]["messages"][-1]["content"][-2:]]
check("finish will refuse it" in written and "no heading for at_risk" in written,
      "write_proposal says straight away what finish will refuse")
check(proposal["status"] == "ok" and "no heading for at_risk" in refusal and "more than one heading for evidence, change" in refusal
      and "nothing under evidence" not in refusal, "an incomplete report is refused, naming each heading, then accepted")
fields, problems = parse_proposal("# Evidence\nruns a, b\n### details\nmore\n## Root cause:\nx\n## CHANGE\ny\n"
                                  "## predicted effect\nz\n##at_risk\nw\n")
check(not problems and fields["evidence"] == "runs a, b\n### details\nmore" and fields["root_cause"] == "x"
      and fields["predicted_effect"] == "z" and fields["at_risk"] == "w",
      "headings match in any case, level, with spaces or a colon; other headings stay in their section")
_, problems = parse_proposal("## evidence\n\n## root_cause\nx\n")
check(problems == ["no heading for change, predicted_effect, at_risk", "nothing under evidence"], "missing and empty sections are named")
check(proposal_refusal(PROPOSAL) is None and proposal_refusal(None).startswith("refused: there is no proposal.md"),
      "a complete report has no refusal")
# the Oct 22 failure, now harmless: finish called with the old fields (packed tags and all) uses proposal.md instead
proposal, _, _ = propose("old_style_finish", [
    reply(use("write_file", path="method.md", content=METHOD), use("write_proposal", content=PROPOSAL),
          use("finish", evidence="x</evidence>\n<root_cause>y</root_cause>"))], smoke="off")
check(proposal["status"] == "ok" and proposal["manifest"] == FIELDS, "arguments given to finish are ignored")
proposal, _, _ = propose("no_finish", [reply(text("I think the harness is fine."), stop="end_turn"),
                                       reply(text("Still fine."), stop="end_turn")], smoke="off")
check(proposal["status"] == "no_finish" and proposal["manifest"] is None, "no finish after one reminder")
proposal, _, _ = propose("over_budget", [reply(use("write_file", path="method.md", content=METHOD))], smoke="off", max_usd=0.001)
check(proposal["status"] == "over_budget", "it stops past its budget")

# 6. the edit-anything scope allows system.md
proposal, _, _ = propose("scope_all", [reply(use("write_file", path="system.md", content="WHAT IS KNOWN\n- more facts\n"),
                                             *finish())], smoke="off", scope="all")
check(proposal["status"] == "ok" and proposal["files_changed"] == [{"path": "system.md", "kind": "modified"}],
      "the edit-anything scope edits system.md")

# 7. the self-test: the first valid finish shows the updater its checker on the best and the worst submissions
proposal, client, _ = propose("self_test", [
    reply(use("write_file", path="tools/closed_loop_check.py", content=NEW_TOOL),
          use("write_file", path="method.md", content=METHOD), *finish()),
    reply(use("write_proposal", content=report_text({**FIELDS, "change": "Edited after the self-test."})), use("finish"))],
    self_test=True)
shown = client.requests[1]["messages"][-1]["content"][-1]["content"]
check(proposal["status"] == "ok" and len(client.requests) == 2, "a self-test round, then submitted")
check("Not submitted yet" in shown and "best run e1c7" in shown and "worst run 63e2" in shown
      and "open-loop replay RMSE" in shown and "python tools/check_submission.py submission.json val/" in shown,
      "the updater sees its checker's output on the best and the worst runs, run as the solver runs it")
check(proposal["manifest"]["change"] == "Edited after the self-test." and "no arguments" in shown,
      "the second finish takes no arguments and submits the report as it stands then")
check(len(proposal["self_test"]) == 2 and all(entry["exit"] == 0 for entry in proposal["self_test"]), "the self-test log is saved")

# 8. an existing folder is never overwritten
try:
    propose("good", [])
    refused = False
except FileExistsError:
    refused = True
check(refused, "an existing candidate folder is refused")
check(not [name for name in os.listdir(work) for inner in [os.path.join(work, name)] if os.path.isdir(inner)
           and any(entry.startswith(".checker_") for entry in os.listdir(inner))],
      "no scratch folder is left behind by the checker runs")

shutil.rmtree(work, ignore_errors=True)
print(f"\nall {passed} checks passed")
