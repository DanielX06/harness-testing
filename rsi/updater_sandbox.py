"""The updater's Python sandbox (run_python): what the solver's sandbox holds, plus the current harness's
submissions and their public scores, so the updater can build a tool and test it before it proposes it.

The folder starts as a solver's would (the recordings, tools/, the scorer's parser as tools/submission_parser.py)
and gains submissions/: the submission.json of each run in the updater's run table, as <run id>.json, and
submissions/scores.json with what part 2 of the updater's context already shows about each run (the composite, the
TD per held-out disturbance and channel, and the failure notes). Nothing else about scoring reaches it: no FR, PAR,
monitor grid or held-out recordings, and scores.json goes through the same hidden-name check as the context.

Before every call, tools/ is rebuilt from the updater's working copy of the harness (the locked parser copied over
it again), so code always runs against the tools as the updater has written them so far. Anything the updater's
code writes into tools/ is lost at the next call: only write_file and delete_file change the harness, so every edit
still goes through harness_proposal.py's checks. Everything else its code writes stays until the proposal ends,
when the folder is removed.

Calls run in the solver's Docker image (no network, 2 GB, the solver's per-call time limit), or with a local Python
for tests. The folder sits under the candidate's folder, inside the repository, so Docker Desktop can mount it.
"""
import json
import os
import shutil
import uuid

from common.harness_files import IGNORE_NON_CONTENT
from common.hidden_names import remove_hidden_device_names
from common.project_paths import SOLVER_DATA_DIRS, SUBMISSION_PARSER_FILE
from rsi.updater_context import UPDATER_OUTPUT_CHARS, check_generated_text, find_run_folders, load_run_summary
from solver.python_sandbox import DOCKER_EXECUTABLE, DockerPythonSandbox, LocalPythonSandbox, fill_sandbox_folder

SUBMISSIONS_FOLDER = "submissions"
SANDBOX_PREFIX = ".updater_sandbox_"


def sandbox_unavailable(mode):
    """Why the updater gets no sandbox with this --smoke mode, or None."""
    if mode == "off":
        return "no Python sandbox for the updater (--smoke off)"
    if mode == "docker" and not os.path.exists(DOCKER_EXECUTABLE):
        return "no Python sandbox for the updater: docker not found"
    return None


def write_submissions(folder, run_ids, run_paths, hidden_pattern):
    """submissions/<run id>.json for each run in run_ids that has a submission, and submissions/scores.json.
    Returns the number of submissions written."""
    os.makedirs(folder)
    run_dirs = {os.path.basename(path).rsplit("_", 1)[-1]: path for path in find_run_folders(run_paths)}
    scores, written = {}, 0
    for run_id in run_ids:
        run_dir = run_dirs.get(run_id)
        summary = load_run_summary(run_dir) if run_dir else None
        if summary is None:
            continue
        submission = os.path.join(run_dir, "submission.json")
        if os.path.exists(submission):
            with open(submission, encoding="utf-8") as file:
                text, _ = remove_hidden_device_names(file.read())      # as the final messages in part 2 are
            with open(os.path.join(folder, f"{run_id}.json"), "w", encoding="utf-8") as file:
                file.write(text)
            written += 1
        if not summary["scored"]:
            scores[run_id] = {"scored": False}
            continue
        scores[run_id] = {"composite": summary["composite"], "td": summary["td"],
                          "td_by_disturbance": summary["td_runs"], "failures": summary["failures"],
                          "submission_file": f"{run_id}.json" if os.path.exists(submission) else None}
    text = json.dumps(scores, indent=1)
    check_generated_text("submissions/scores.json", text, hidden_pattern)
    with open(os.path.join(folder, "scores.json"), "w") as file:
        file.write(text + "\n")
    return written


class UpdaterSandbox:
    def __init__(self, folder, workspace_tools_dir, runner):
        self.folder, self.workspace_tools_dir, self.runner = folder, workspace_tools_dir, runner
        self.calls = self.timeouts = 0

    @classmethod
    def create(cls, scratch_parent, workspace_tools_dir, noise, run_ids, run_paths, hidden_pattern, mode="docker",
               python=None):
        """A new sandbox under scratch_parent. mode is "docker" or "local" (sandbox_unavailable says when neither)."""
        folder = os.path.join(os.path.abspath(scratch_parent), SANDBOX_PREFIX + uuid.uuid4().hex[:8])
        fill_sandbox_folder(folder, SOLVER_DATA_DIRS[noise], workspace_tools_dir, SUBMISSION_PARSER_FILE)
        try:
            write_submissions(os.path.join(folder, SUBMISSIONS_FOLDER), run_ids, run_paths, hidden_pattern)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        runner = DockerPythonSandbox(folder) if mode == "docker" else LocalPythonSandbox(folder, python)
        return cls(folder, workspace_tools_dir, runner)

    def refresh_tools(self):
        """tools/ as the updater's working copy has it, with the scorer's parser over submission_parser.py."""
        tools = os.path.join(self.folder, "tools")
        shutil.rmtree(tools, ignore_errors=True)
        shutil.copytree(self.workspace_tools_dir, tools, ignore=IGNORE_NON_CONTENT)
        shutil.copy(SUBMISSION_PARSER_FILE, os.path.join(tools, "submission_parser.py"))

    def run_python(self, code):
        """One run_python call: the text that goes back to the updater. Raises SandboxUnavailable if Docker fails."""
        self.refresh_tools()
        result = self.runner.run_python_code(code, UPDATER_OUTPUT_CHARS)
        self.calls += 1
        self.timeouts += int(result.timed_out)
        output = result.output if result.output.strip() else "(no output)"
        if not result.timed_out and result.exit_code != 0:
            output += f"\n(exit code {result.exit_code})"
        return output

    def remove(self):
        shutil.rmtree(self.folder, ignore_errors=True)
