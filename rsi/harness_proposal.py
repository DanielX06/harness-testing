"""One updater call: show the updater how the current harness did, let it edit a copy of the harness, and check
the result before any solver run sees it.

    python rsi/harness_proposal.py --runs runs/batch_20261022_101500_haiku_low_clean --harness harness_v0/harness \\
                                   --out rsi/candidates/h002

Writes, under --out:
    harness/          the candidate harness (system.md, method.md, tools/), ready for solver_run.py --harness
    proposal.json     status, the updater's manifest (its finish call), files changed, checks, warnings,
                      parent and candidate fingerprints, turns, tokens and cost
    diff.patch        the candidate against its parent
    transcript.json   the updater's whole exchange (the diagram replaced by its file name)
    context.md, context_stats.json   what the updater was given

Before a finish is accepted, the updater sees its own checker run on the best and the worst runs' submissions
once (the self-test) and has to call finish again; --no-self-test skips that.

status is "ok" (ready for solver runs), "invalid" (failed a check; never run), "no_change", "no_finish" (it
stopped or ran out of turns without calling finish) or "over_budget". Only "ok" candidates go on.
"""
import argparse
import ast
import difflib
import json
import os
import re
import shutil
import sys
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the repository root
from common.api_pricing import price_for  # noqa: E402
from common.harness_files import copy_harness, harness_fingerprint, list_harness_files  # noqa: E402
from common.hidden_names import SIMULATOR_AND_DEVICE_NAMES  # noqa: E402
from common.project_paths import RSI_SCORER_CONFIG, SOLVER_DATA_DIRS, SUBMISSION_PARSER_FILE, TASK_PROMPT_FILE  # noqa: E402
from rsi.updater_context import UpdaterContextBuilder, find_run_folders, read_history  # noqa: E402
from solver.python_sandbox import DOCKER_EXECUTABLE, TIMEOUT_EXIT_CODE, DockerPythonSandbox, LocalPythonSandbox  # noqa: E402
from solver.solver_run import MAX_OUTPUT_TOKENS  # noqa: E402

TOOL_FILE_PATTERN = re.compile(r"^tools/[A-Za-z_][A-Za-z0-9_]*\.py$")
MAX_FILE_CHARS = 60000                  # one file; method.md is 1.5k today, the largest tool 4.8k
PARSER_TOOL = "tools/submission_parser.py"       # locked: copied over from scorer/ at run time
CHECKER_TOOL = "tools/check_submission.py"       # the prompt says it may be extended, not removed
MANIFEST_KEYS = ("evidence", "root_cause", "change", "predicted_effect", "at_risk")
# numbers that look fitted rather than chosen: a decimal with at least three significant digits (0.0396, 22.15)
FITTED_LOOKING_DECIMAL = re.compile(r"(?<![\w.])\d+\.\d+(?:[eE][-+]?\d+)?(?![\w.])")
# in method.md (as before): any decimal, or an integer of two digits or more
METHOD_NUMBER = re.compile(r"(?<![\w.])\d+\.\d+|(?<![\w.])\d{2,}(?![\w.])")


# ---- the candidate folder ---------------------------------------------------------------------------------
def check_editable_path(path, scope, deleting=False):
    """An error message if the scope does not let the updater write (or delete) this path, else None."""
    if not isinstance(path, str) or not path:
        return "path must be a non-empty string"
    if "\\" in path or path.startswith("/") or ".." in path.split("/"):
        return "path must be relative to the harness folder, with forward slashes and no '..'"
    if deleting:
        if path in ("method.md", "system.md"):
            return f"{path} cannot be removed"
        if path == PARSER_TOOL:
            return f"{PARSER_TOOL} is locked"
        if path == CHECKER_TOOL:
            return f"{CHECKER_TOOL} may be extended but not removed"
        return None if TOOL_FILE_PATTERN.match(path) else "only tools/<name>.py files can be removed"
    if path == "method.md":
        return None
    if path == "system.md":
        return None if scope == "all" else "system.md is read-only in this run"
    if path == PARSER_TOOL:
        return f"{PARSER_TOOL} is locked: it is the scorer's parser, copied in at run time"
    if TOOL_FILE_PATTERN.match(path):
        return None
    return ("you may write method.md" + (", system.md" if scope == "all" else "")
            + " or tools/<name>.py (one level, a Python identifier, ending in .py)")


def read_text(folder, relative_path):
    with open(os.path.join(folder, relative_path), encoding="utf-8") as file:
        return file.read()


class CandidateWorkspace:
    """A copy of the parent harness that the updater's tool calls edit."""

    def __init__(self, parent_dir, folder, scope):
        self.parent_dir, self.folder, self.scope = parent_dir, folder, scope
        copy_harness(parent_dir, folder)
        self.refused = []

    def apply_tool_call(self, name, tool_input):
        """Apply one write_file or delete_file call. Returns (message for the updater, is_error)."""
        if name == "write_file":
            path, content = tool_input.get("path"), tool_input.get("content")
            error = check_editable_path(path, self.scope)
            if error is None and not isinstance(content, str):
                error = "content must be a string"
            if error is None and len(content) > MAX_FILE_CHARS:
                error = f"content is {len(content)} characters; the limit is {MAX_FILE_CHARS}"
            if error is None and not content.strip():
                error = "content is empty; use delete_file to remove a tool"
            if error:
                self.refused.append({"tool": name, "path": path, "reason": error})
                return f"refused: {error}", True
            full_path = os.path.join(self.folder, path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            existed = os.path.exists(full_path)
            with open(full_path, "w", encoding="utf-8") as file:
                file.write(content)
            return f"{'replaced' if existed else 'created'} {path} ({len(content)} characters)", False
        if name == "delete_file":
            path = tool_input.get("path")
            error = check_editable_path(path, self.scope, deleting=True)
            if error is None and not os.path.exists(os.path.join(self.folder, path)):
                error = f"{path} does not exist"
            if error:
                self.refused.append({"tool": name, "path": path, "reason": error})
                return f"refused: {error}", True
            os.remove(os.path.join(self.folder, path))
            return f"removed {path}", False
        return f"unknown tool {name}", True

    def changes(self):
        """{path: (old text or None, new text or None)} for every file that differs from the parent."""
        before, after = set(list_harness_files(self.parent_dir)), set(list_harness_files(self.folder))
        changed = {}
        for path in sorted(before | after):
            old = read_text(self.parent_dir, path) if path in before else None
            new = read_text(self.folder, path) if path in after else None
            if old != new:
                changed[path] = (old, new)
        return changed


def unified_diff_text(changes):
    parts = []
    for path, (old, new) in changes.items():
        parts += difflib.unified_diff((old or "").splitlines(keepends=True), (new or "").splitlines(keepends=True),
                                      fromfile=f"a/{path}" if old is not None else "/dev/null",
                                      tofile=f"b/{path}" if new is not None else "/dev/null")
    return "".join(part if part.endswith("\n") else part + "\n" for part in parts)


# ---- checks before any solver run ---------------------------------------------------------------------------
def imported_module_names(source):
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def added_lines(old_text, new_text):
    return "\n".join(line[1:] for line in difflib.unified_diff((old_text or "").splitlines(), (new_text or "").splitlines(),
                                                               lineterm="") if line.startswith("+") and not line.startswith("+++"))


def significant_digits(number_text):
    mantissa = re.split(r"[eE]", number_text)[0].replace(".", "").lstrip("0").rstrip("0")
    return len(mantissa)


def static_problems(workspace, changes):
    """(errors, warnings). An error makes the candidate invalid; a warning is for a reviewer."""
    errors, warnings = [], []
    files = list_harness_files(workspace.folder)
    for path in files:
        if SIMULATOR_AND_DEVICE_NAMES.search(path):
            errors.append(f"the file name {path} contains a name the solver must never see")
        text = read_text(workspace.folder, path)
        match = SIMULATOR_AND_DEVICE_NAMES.search(text)
        if match:
            errors.append(f"{path} contains a name the solver must never see: {match.group(0)!r}")
        if path.endswith(".py"):
            try:
                compile(text, path, "exec")
            except SyntaxError as error:
                errors.append(f"{path} does not compile: line {error.lineno}: {error.msg}")
    if "method.md" not in files or not read_text(workspace.folder, "method.md").strip():
        errors.append("method.md is missing or empty")
    if workspace.scope == "tools" and "system.md" in changes:
        errors.append("system.md changed in the tools scope")
    # check_submission.py must keep parsing with submission_parser.py, directly or through a tool it imports
    parser_module = os.path.splitext(os.path.basename(PARSER_TOOL))[0]
    if CHECKER_TOOL not in files:
        errors.append(f"{CHECKER_TOOL} is missing")
    else:
        try:
            imports = imported_module_names(read_text(workspace.folder, CHECKER_TOOL))
            through_a_tool = {name for name in imports if f"tools/{name}.py" in files
                              and parser_module in imported_module_names(read_text(workspace.folder, f"tools/{name}.py"))}
            if parser_module not in imports and not through_a_tool:
                errors.append(f"{CHECKER_TOOL} no longer imports {parser_module}, directly or through another tool")
        except SyntaxError:
            pass                                        # already reported above

    method = read_text(workspace.folder, "method.md") if "method.md" in files else ""
    for path, (old, new) in changes.items():
        if old is None and new is not None and path.startswith("tools/"):
            if path[len("tools/"):] not in method:
                warnings.append(f"new tool {path} is not named in method.md, so the solver may never find it")
            try:
                if not ast.get_docstring(ast.parse(new)):
                    warnings.append(f"new tool {path} has no docstring with its command line")
            except SyntaxError:
                pass
    # numbers that may have been fitted from these recordings (the leak the tools scope forbids)
    with open(TASK_PROMPT_FILE, encoding="utf-8") as file:
        task_prompt = file.read()
    if "method.md" in changes:
        old, new = changes["method.md"]
        seen = set(re.findall(r"\d+(?:\.\d+)?", (old or "") + task_prompt))
        added = sorted(set(METHOD_NUMBER.findall(added_lines(old, new))) - seen)
        if added:
            warnings.append("method.md gains numbers that are not in the parent or the task prompt; check none was "
                            "fitted from these recordings: " + ", ".join(added[:12]))
    parent_text = "".join(read_text(workspace.parent_dir, path) for path in list_harness_files(workspace.parent_dir))
    seen_anywhere = set(re.findall(r"\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", parent_text + task_prompt))
    for path, (old, new) in changes.items():
        if path.startswith("tools/") and new is not None:
            added = sorted({number for number in FITTED_LOOKING_DECIMAL.findall(added_lines(old, new))
                            if significant_digits(number) >= 3} - seen_anywhere)
            if added:
                warnings.append(f"{path} gains numbers with three or more significant digits that are not in the parent "
                                f"harness or the task prompt; check none was fitted from these recordings: "
                                + ", ".join(added[:12]))
    return errors, warnings


def best_scored_submission(run_paths):
    """The submission.json of the best-scoring run among run_paths, for the smoke run."""
    best = None
    for run_dir in find_run_folders(run_paths):
        public, submission = os.path.join(run_dir, "score", "public.json"), os.path.join(run_dir, "submission.json")
        if os.path.exists(public) and os.path.exists(submission):
            with open(public) as file:
                score = json.load(file)["score"]
            if score is not None and (best is None or score < best[0]):
                best = (score, submission)
    return best[1] if best else None


def validation_files(noise):
    with open(os.path.join(SOLVER_DATA_DIRS[noise], "runs.json")) as file:
        runs = json.load(file)
    return sorted(run["file"] for run in runs.values() if run["split"] == "val")


def run_candidate_checker(workspace, noise, jobs, scratch_parent, mode="docker", python=None):
    """Run the candidate's tools/check_submission.py the way the solver would, once per job.
    jobs: (label, submission file or None for an empty submission, csv relative path or None).
    Returns [{label, cmd, exit, seconds, output}]."""
    data_dir = SOLVER_DATA_DIRS[noise]
    folder = os.path.join(scratch_parent, f".checker_{uuid.uuid4().hex[:8]}")   # under the repo, so Docker Desktop can mount it
    log = []
    try:
        os.makedirs(os.path.join(folder, "val"))
        for name in ("runs.json", "dataset.json"):
            shutil.copy(os.path.join(data_dir, name), os.path.join(folder, name))
        for _, _, csv in jobs:
            if csv and not os.path.exists(os.path.join(folder, csv)):
                shutil.copy(os.path.join(data_dir, csv), os.path.join(folder, csv))
        shutil.copytree(os.path.join(workspace.folder, "tools"), os.path.join(folder, "tools"))
        shutil.copy(SUBMISSION_PARSER_FILE, os.path.join(folder, PARSER_TOOL))
        sandbox = DockerPythonSandbox(folder) if mode == "docker" else LocalPythonSandbox(folder, python)
        for label, submission, csv in jobs:            # one at a time, each as submission.json, as the solver names it
            if submission:
                shutil.copy(submission, os.path.join(folder, "submission.json"))
            else:
                with open(os.path.join(folder, "submission.json"), "w") as file:
                    file.write("{}")
            command = ["python", CHECKER_TOOL, "submission.json"] + ([csv] if csv else [])
            started = time.monotonic()
            result = sandbox.run(*command)
            log.append({"label": label, "cmd": " ".join(command), "exit": result.exit_code,
                        "seconds": round(time.monotonic() - started, 1), "output": result.output[-4000:]})
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return log


def checker_unavailable(mode):
    if mode == "off":
        return "smoke run skipped (--smoke off)"
    if mode == "docker" and not os.path.exists(DOCKER_EXECUTABLE):
        return "smoke run skipped: docker not found"
    return None


def smoke_problems(workspace, run_paths, noise, scratch_parent, mode="docker", python=None):
    """A valid submission must pass the candidate's checker (exit 0) on a validation file in time, and an empty one
    must be rejected (non-zero exit). Returns (errors, warnings, log)."""
    skipped = checker_unavailable(mode)
    if skipped:
        return [], [skipped], []
    reference, validation = best_scored_submission(run_paths), validation_files(noise)
    if not reference or not validation:
        return [], ["smoke run skipped: no scored submission or no validation file"], []
    log = run_candidate_checker(workspace, noise, [("best submission", reference, validation[0]),
                                                   ("empty submission", None, None)], scratch_parent, mode, python)
    errors = []
    for entry, should_pass in zip(log, (True, False)):
        if entry["exit"] == TIMEOUT_EXIT_CODE:
            errors.append(f"{entry['cmd']} did not finish in 120 s")
        elif should_pass and entry["exit"] != 0:
            errors.append(f"the checker fails on a valid submission (exit {entry['exit']}): {entry['output'].strip()[-300:]}")
        elif not should_pass and entry["exit"] == 0:
            errors.append("the checker accepts an empty submission")
    return errors, [], log


def self_test_message(workspace, run_paths, context, scratch_parent, mode="docker", python=None):
    """The candidate's checker on the best and worst runs' submissions, as text for the updater, plus the log.
    (None, []) if it cannot run."""
    if checker_unavailable(mode):
        return None, []
    validation = validation_files(context.stats["noise"])
    jobs = []
    for which in ("best", "worst"):
        run_id = context.stats[which]
        run_dir = next((folder for folder in find_run_folders(run_paths) if os.path.basename(folder).endswith("_" + run_id)), None)
        if run_dir and os.path.exists(os.path.join(run_dir, "submission.json")) and validation:
            jobs.append((f"{which} run {run_id}", os.path.join(run_dir, "submission.json"), validation[0]))
    if not jobs:
        return None, []
    log = run_candidate_checker(workspace, context.stats["noise"], jobs, scratch_parent, mode, python)
    parts = ["Not submitted yet. Before you submit, here is your harness's checker on two real submissions from "
             "the runs above, run the way the solver will run it. Check that what your tools tell the solver is "
             "right for both: the best run's model is the best this harness has produced."]
    for entry in log:
        parts.append(f"{entry['label']}: {entry['cmd']} (exit {entry['exit']}, {entry['seconds']} s)\n{entry['output'].strip()}")
    parts.append("Then call finish again: as it is to submit this harness, or after more edits.")
    return "\n\n".join(parts), log


def finish_refusal(tool_input, missing):
    """The refusal for a finish call with missing or empty fields. It names the fields that arrived, so an updater
    that packed several fields into one string as <tag>...</tag> text is told what it did."""
    present = [key for key in tool_input if str(tool_input.get(key, "")).strip()]
    message = (f"refused: finish needs {', '.join(missing)} as separate parameters, each non-empty. "
               f"This call had only: {', '.join(present) if present else 'no non-empty parameters'}.")
    packed = sorted({key for key in missing for value in tool_input.values() if isinstance(value, str) and f"<{key}>" in value})
    if packed:
        message += (f" Your text holds <{'>, <'.join(packed)}> tags inside another parameter; tags inside a string "
                    f"are not parameters. Call finish again with each of {', '.join(MANIFEST_KEYS)} as its own "
                    f"parameter, holding plain text.")
    return message


def plain_block(block):
    """A content block as a plain dict for the saved transcript; the diagram is replaced by its file name."""
    if isinstance(block, dict):
        plain = dict(block)
    elif hasattr(block, "model_dump"):
        plain = block.model_dump()
    else:
        plain = dict(vars(block))
    return {"type": "image", "source": "system_diagram.png"} if plain.get("type") == "image" else plain


# ---- the updater conversation ---------------------------------------------------------------------------------
class HarnessUpdaterSession:
    """The conversation with the updater: requests, its edits to the workspace, the self-test, and its finish."""

    def __init__(self, context, workspace, client, model, effort, max_turns, max_usd, run_paths, scratch_parent,
                 smoke="docker", smoke_python=None, self_test=True):
        self.context, self.workspace, self.client = context, workspace, client
        self.model, self.effort, self.max_turns, self.max_usd = model, effort, max_turns, max_usd
        self.run_paths, self.scratch_parent = run_paths, scratch_parent
        self.smoke, self.smoke_python, self.self_test = smoke, smoke_python, self_test
        self.price = price_for(model)
        self.messages = [{"role": "user", "content": context.user_content}]
        self.turns, self.spent_usd, self.manifest, self.status = 0, 0.0, None, None
        self.usage = {key: 0 for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
        self.usage_per_turn = []                # the first turn's input is the exact size of the context
        self.self_test_done, self.self_test_log = False, []
        self.nudged = False

    def run(self):
        """Talk until the updater's finish is accepted, it gives up, or turns or budget run out. Sets status to
        None (submitted), "no_finish" or "over_budget"."""
        while self.turns < self.max_turns:
            response = self._request()
            self.messages.append({"role": "assistant", "content": response.content})
            tool_uses = [block for block in response.content if block.type == "tool_use"]
            if not tool_uses:
                note = self._note_after_reply_without_tools(response)
                if note is None:
                    self.status = "no_finish"
                    return
                self.messages.append({"role": "user", "content": [{"type": "text", "text": note}]})
                continue
            results, finish = [], None
            for block in tool_uses:                 # edits first, in order; finish last
                if block.name == "finish":
                    finish = block
                    continue
                message, is_error = self.workspace.apply_tool_call(block.name, block.input if isinstance(block.input, dict) else {})
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": message,
                                **({"is_error": True} if is_error else {})})
            if finish is not None:
                result, submitted = self._answer_finish(finish)
                results.append(result)
                if submitted:
                    self.messages.append({"role": "user", "content": results})
                    return
            self.messages.append({"role": "user", "content": results})
            if self.spent_usd > self.max_usd:
                self.status = "over_budget"
                return
        self.status = "no_finish"

    def _request(self):
        with self.client.messages.stream(model=self.model, max_tokens=MAX_OUTPUT_TOKENS, system=self.context.system_prompt,
                                         tools=self.context.tools, output_config={"effort": self.effort},
                                         cache_control={"type": "ephemeral"}, messages=self.messages) as stream:
            response = stream.get_final_message()
        self.turns += 1
        self.spent_usd += self.price.request_cost(response.usage)
        counts = {key: getattr(response.usage, key, 0) or 0 for key in self.usage}
        for key, value in counts.items():
            self.usage[key] += value
        self.usage_per_turn.append(counts)
        print(f"updater turn {self.turns}: ${self.spent_usd:.4f} spent, stop reason {response.stop_reason}", flush=True)
        return response

    def _note_after_reply_without_tools(self, response):
        """What to tell an updater that replied without a tool call; None means give up (it was already reminded)."""
        if response.stop_reason == "max_tokens":
            return "Your reply hit the output limit before any tool call. Write one file per write_file call."
        if self.nudged:
            return None
        self.nudged = True
        return "Make your change with write_file or delete_file, then call finish."

    def _answer_finish(self, finish):
        """(tool result for the finish call, whether the candidate is now submitted)."""
        tool_input = finish.input if isinstance(finish.input, dict) else {}
        missing = [key for key in MANIFEST_KEYS if not str(tool_input.get(key, "")).strip()]
        if not self.workspace.changes():
            return {"type": "tool_result", "tool_use_id": finish.id, "is_error": True,
                    "content": "refused: the harness is unchanged; write at least one file first"}, False
        if missing:
            return {"type": "tool_result", "tool_use_id": finish.id, "is_error": True,
                    "content": finish_refusal(tool_input, missing)}, False
        if self.self_test and not self.self_test_done:
            self.self_test_done = True
            text, log = self_test_message(self.workspace, self.run_paths, self.context, self.scratch_parent,
                                          self.smoke, self.smoke_python)
            self.self_test_log += log
            if text is not None:
                return {"type": "tool_result", "tool_use_id": finish.id, "content": text}, False
        self.manifest = {key: str(tool_input[key]).strip() for key in MANIFEST_KEYS}
        return {"type": "tool_result", "tool_use_id": finish.id, "content": "submitted"}, True


def propose_candidate(run_paths, harness_dir, out_dir, scope="tools", history=None, model="claude-haiku-5-5",
                      effort="low", max_turns=20, max_usd=2.0, smoke="docker", smoke_python=None, client=None,
                      newest_runs=20, token_budget=80000, self_test=True, scorer_config=RSI_SCORER_CONFIG):
    """One proposal from the runs in run_paths of the harness in harness_dir, written to out_dir.
    scorer_config names the grids whose names the updater must never see. Returns the proposal dict (also saved
    as proposal.json)."""
    price_for(model)                                # an unknown model fails here, before anything is written
    if os.path.exists(out_dir):
        raise FileExistsError(f"{out_dir} already exists")
    harness_dir = os.path.abspath(harness_dir)
    context = UpdaterContextBuilder(run_paths, harness_dir, scope=scope, history=history, newest_runs=newest_runs,
                                    token_budget=token_budget, scorer_config=scorer_config).build()
    os.makedirs(out_dir)
    with open(os.path.join(out_dir, "context.md"), "w") as file:
        file.write(context.readable_markdown + "\n")
    with open(os.path.join(out_dir, "context_stats.json"), "w") as file:
        json.dump(context.stats, file, indent=1)
    workspace = CandidateWorkspace(harness_dir, os.path.join(out_dir, "harness"), scope)
    if client is None:
        import anthropic
        client = anthropic.Anthropic(max_retries=6)     # rides out short overloads in an unattended loop
    session = HarnessUpdaterSession(context, workspace, client, model, effort, max_turns, max_usd, run_paths, out_dir,
                                    smoke, smoke_python, self_test)
    started = time.monotonic()
    try:
        session.run()
    finally:
        with open(os.path.join(out_dir, "transcript.json"), "w") as file:
            json.dump({"model": model, "effort": effort, "spent_usd": round(session.spent_usd, 4),
                       "messages": [{"role": message["role"], "content": [plain_block(block) for block in message["content"]]}
                                    for message in session.messages]}, file, indent=1, default=str)

    changes = workspace.changes()
    with open(os.path.join(out_dir, "diff.patch"), "w") as file:
        file.write(unified_diff_text(changes))
    status, errors, warnings, smoke_log = session.status, [], [], []
    if session.manifest is not None:
        if not changes:
            status = "no_change"
        else:
            errors, warnings = static_problems(workspace, changes)
            if not errors:
                smoke_errors, smoke_warnings, smoke_log = smoke_problems(workspace, run_paths, context.stats["noise"],
                                                                         out_dir, smoke, smoke_python)
                errors, warnings = errors + smoke_errors, warnings + smoke_warnings
            status = "invalid" if errors else "ok"
    first_turn = session.usage_per_turn[0] if session.usage_per_turn else None
    proposal = {
        "status": status, "candidate": os.path.basename(os.path.normpath(out_dir)),
        "parent": harness_dir, "parent_sha": context.stats["harness_sha"],
        "candidate_sha": harness_fingerprint(workspace.folder), "scope": scope, "manifest": session.manifest,
        "files_changed": [{"path": path, "kind": "added" if old is None else "removed" if new is None else "modified"}
                          for path, (old, new) in changes.items()],
        "errors": errors, "warnings": warnings, "refused": workspace.refused, "smoke": smoke_log,
        "self_test": session.self_test_log,
        "updater": {"model": model, "effort": effort, "turns": session.turns, "seconds": round(time.monotonic() - started, 1),
                    "spent_usd": round(session.spent_usd, 4), "usage": session.usage, "usage_per_turn": session.usage_per_turn,
                    "context_tokens": (sum(first_turn[key] for key in ("input_tokens", "cache_read_input_tokens",
                                                                       "cache_creation_input_tokens")) if first_turn else None)},
        "context": {key: context.stats[key] for key in ("runs_in_table", "best", "worst", "tokens_est", "reductions",
                                                        "history_records")},
    }
    with open(os.path.join(out_dir, "proposal.json"), "w") as file:
        json.dump(proposal, file, indent=1)
    return proposal


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", nargs="+", required=True, help="the current harness's run or batch folders")
    parser.add_argument("--harness", required=True, help="the current harness folder")
    parser.add_argument("--out", required=True, help="new folder for the candidate, e.g. rsi/candidates/h001")
    parser.add_argument("--scope", choices=["tools", "all"], default="tools")
    parser.add_argument("--history", default=None, help="history.jsonl from the loop")
    parser.add_argument("--model", default="claude-haiku-5-5")
    parser.add_argument("--effort", default="low", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--max-usd", type=float, default=2.0, help="stop the updater past this cost (USD)")
    parser.add_argument("--smoke", choices=["docker", "local", "off"], default="docker",
                        help="run the candidate's checker in the solver's Docker image (default), with --smoke-python, or not")
    parser.add_argument("--no-self-test", action="store_true",
                        help="skip showing the updater its checker on the best and worst submissions before it submits")
    parser.add_argument("--smoke-python", default=None, help="interpreter for --smoke local (needs numpy, pandas, scipy, sympy)")
    options = parser.parse_args()
    proposal = propose_candidate(options.runs, options.harness, options.out, options.scope, read_history(options.history),
                                 options.model, options.effort, options.max_turns, options.max_usd, options.smoke,
                                 options.smoke_python, self_test=not options.no_self_test)
    updater = proposal["updater"]
    print(f"\n{proposal['candidate']}: {proposal['status']}  ({updater['turns']} turns, ${updater['spent_usd']:.4f}, "
          f"{updater['seconds']} s)")
    for changed in proposal["files_changed"]:
        print(f"  {changed['kind']:8s} {changed['path']}")
    if proposal["manifest"]:
        print("  change:", proposal["manifest"]["change"])
    for error in proposal["errors"]:
        print("  error:", error)
    for warning in proposal["warnings"]:
        print("  warning:", warning)
    for refused in proposal["refused"]:
        print(f"  refused {refused['tool']} {refused['path']}: {refused['reason']}")
    if updater["context_tokens"]:
        print(f"  context: {updater['context_tokens']} tokens on the first turn "
              f"(estimated {proposal['context']['tokens_est']['total']})")
    print(f"  candidate fingerprint {proposal['candidate_sha']} (parent {proposal['parent_sha']}); "
          f"details in {os.path.join(options.out, 'proposal.json')}")
    return 0 if proposal["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
