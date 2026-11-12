"""What the RSI updater sees: its instructions (the system prompt) and one user message of evidence about the
current harness.

    python rsi/updater_context.py --runs rsi/tests/fixtures/oct13_clean_batch --harness rsi/tests/fixtures/harness_v0_oct13 \\
                                  --out rsi/previews/oct13_clean
    python rsi/updater_context.py ... --count-tokens      # exact input-token count from the free counting endpoint

From the loop:

    from rsi.updater_context import UpdaterContextBuilder
    context = UpdaterContextBuilder(run_dirs, harness_dir, scope="tools", history=records).build()
    client.messages.create(model=..., system=context.system_prompt, tools=context.tools,
                           messages=[{"role": "user", "content": context.user_content}], ...)

What goes in, and what never does, is set out in rsi/README.md. In short: the solver's own view; from each
finished run only the composite, the TD per held-out run and channel and a plain-language failure note
(score/public.json), the step, tool-call and cost counts (meta.json), the final message, and the transcripts
of the best and the worst run; then the history of earlier attempts. FR, PAR, grid M, grid A's held-out runs,
meta.json's score components and anything in private.json never go in, and the build stops if one of their
names shows up in text it generated itself.

With python_tool=True the updater also gets run_python, a sandbox to build and test its change in
(rsi/updater_sandbox.py), and the prompt says so.
"""
import argparse
import base64
import json
import math
import os
import re
import statistics
import struct
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the repository root
from common.harness_files import harness_fingerprint  # noqa: E402
from common.hidden_names import SIMULATOR_AND_DEVICE_NAMES, remove_hidden_device_names  # noqa: E402
from common.project_paths import (DEVICE_SOLVER_DATA_DIRS, REPOSITORY_ROOT, RSI_SCORER_CONFIG,  # noqa: E402
                                  SUBMISSION_PARSER_FILE, TASK_PROMPT_FILE, UNIT_LABELS, UPDATER_PROMPT_FILE)
from solver.python_sandbox import CALL_TIME_LIMIT_S  # noqa: E402
from solver.solver_run import API_BUDGET_USD, NOISE_SENTENCES, SOLVER_TOOLS, TOOL_OUTPUT_CHARS  # noqa: E402

# Field names that exist only in the hidden score components or in the scorer's private output.
# hidden_score_names_pattern() adds the names of the hidden grids and of their held-out runs.
HIDDEN_FIELD_NAMES = (r"fr_entries|par_entries|role_scores|train_holdout|private\.json|td_runs_full|fr_detail"
                      r"|par_detail|droop_truth|gains_truth|\"(?:fr|par)\"\s*:")
# the only meta.json fields read; never "components", "role_scores" or "score_selection"
META_FIELDS_READ = ("tag", "model", "effort", "harness_sha", "spent_usd", "steps", "tool_calls", "tool_timeouts",
                    "budget_stop", "submission_source", "final_message_differs", "submission_rejected", "noise")
# A deliberately high estimate of the token count. English prose runs near 3.5 characters a token on earlier
# Claude tokenizers, and code and tables of numbers run denser. Claude 4.7 and later models, Haiku 5.5 among
# them, use a tokenizer that can give up to about 35% more tokens for the same text. --count-tokens returns
# the exact count and the ratio to put here. Nov 12: Opus 5.5's first turn in the probe on the wecc_docs runs was
# 96,728 tokens against 78,674 estimated at 2.5, about 2.0 characters a token; at 2.5 the 80k budget let the
# context start near 97k and the updater hit the wrap-up after eight sandbox calls.
CHARS_PER_TOKEN = 2.0
OUTCOME_DESCRIPTIONS = {
    "accepted": "kept: it became the current harness",
    "rejected": "rejected: not better by more than run-to-run variation",
    "rejected_early": "rejected early: after the first pairs of runs it was not ahead at all",
    "reverted": "passed the first block of runs, then failed the confirmation block, so it was not kept",
    "invalid": "never run: it failed the checks made before any solver run",
    "duplicate": "never run: it was the same harness as an earlier one (the note names it)",
}
# History fields the RSI loop writes itself (the rest is the updater's own text and its diff). A hidden name in
# one of these means the loop put something there it should not have, so the build stops.
LOOP_WRITTEN_HISTORY_FIELDS = ("iteration", "candidate", "parent", "outcome", "files_changed", "n_candidate",
                               "n_current", "mean_candidate", "mean_current", "se_difference", "p_value",
                               "td_candidate", "td_current", "fail_rate_candidate", "fail_rate_current", "note",
                               "diff_summary", "report_mismatch", "by_unit", "fr_by_unit")
UPDATER_TOOLS = [
    {"name": "write_file",
     "description": "Write one file of the new harness with its complete content. path is relative to the "
                    "harness folder: method.md, system.md when it is editable, or tools/<name>.py. Files you "
                    "do not write stay as they are; writing a path again replaces that file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "delete_file",
     "description": "Remove one file from tools/ in the new harness. method.md, system.md and "
                    "tools/submission_parser.py cannot be removed.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_proposal",
     "description": "Write your report on the change, as markdown with five headings, each with plain text under "
                    "it: ## evidence, ## root_cause, ## change, ## predicted_effect, ## at_risk. It is not part "
                    "of the harness and the solver never sees it. Calling it again replaces the report.",
     "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}},
    {"name": "finish",
     "description": "Submit the new harness and the report you wrote with write_proposal. It takes no arguments. "
                    "Call it after all your write_file, delete_file and write_proposal calls. It refuses a harness "
                    "that is unchanged, or that differs from the current one only in whitespace or blank lines.",
     "input_schema": {"type": "object", "properties": {}}},
]

# the updater's run_python output is cut to its last this-many characters: smaller than the solver's, since the
# updater's conversation already starts with the whole context
UPDATER_OUTPUT_CHARS = 8000
RUN_PYTHON_TOOL = {
    "name": "run_python",
    "description": "Run Python code in your sandbox: train/, val/, runs.json, dataset.json, tools/ as you have "
                   "edited it so far, and submissions/ (the part 2 runs' submissions and scores.json). Returns "
                   f"stdout and stderr, cut to the last {UPDATER_OUTPUT_CHARS} characters. It never changes the "
                   "harness: only write_file and delete_file do.",
    "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}
SANDBOX_TEXT = (
    "You also have run_python, a sandbox to build and test your change in. It holds what the solver's working "
    "directory holds (train/, val/, runs.json, dataset.json, and tools/ with your write_file and delete_file edits "
    "applied before every call) plus submissions/: the submission.json of each run in the part 2 table, as "
    "<run id>.json, and submissions/scores.json with the composite, TD and failures part 2 shows for each. Each call "
    "is a fresh Python process with numpy, pandas, scipy and sympy, no network, a {{CALL_TIME_LIMIT_S}} s limit, and "
    "output cut to its last {{UPDATER_OUTPUT_CHARS}} characters. Files your code writes stay for your later calls, "
    "except in tools/, which is rebuilt from your edits before each call. Only write_file and delete_file change "
    "the harness.")
SANDBOX_UNITS_TEXT = (
    " The runs take turns between units: the top of the sandbox holds {{FIRST_UNIT}}'s recordings, and {{OTHER_UNITS}} "
    "(train/, val/, runs.json, dataset.json, as that unit's solver gets them). submissions/scores.json says which unit "
    "each run was on.")
UNITS_NOTE = (
    "The solver's runs take turns between {{UNIT_COUNT}} different units ({{UNIT_LIST}}), each identified from its own "
    "recordings and scored on its own grids. Part 2 says which unit each run was on. Your change is compared with the "
    "current harness on all of them together, and it is kept only if it helps on average across them, so a change "
    "that suits one unit's structure or numbers and hurts another's is rejected here as well as later.")
LABEL_TO_DEVICE = {label: device for device, label in UNIT_LABELS.items()}


def unit_data_dir(unit, noise):
    """The recordings the solver gets for a unit."""
    return DEVICE_SOLVER_DATA_DIRS[LABEL_TO_DEVICE[unit]][noise]


def unit_folder(unit):
    """Where a unit other than the first sits in the updater's sandbox: unit2/ for "unit 2"."""
    return unit.replace(" ", "")
TEST_STEP_WITH_SANDBOX = (
    "4. Run what you build before you submit it; a tool you have not run is a guess. Use run_python to run it the way "
    "the solver would, on the full recordings and on the submissions in submissions/. Check that it finishes well "
    "inside {{CALL_TIME_LIMIT_S}} s, that its output is right, and that what it tells the solver separates the "
    "better-scoring submissions from the worse ones.")
TEST_STEP_WITHOUT_SANDBOX = (
    "4. You cannot run code here, so read every tool you write line by line, as the solver will run it, before you "
    "submit.")


@dataclass
class UpdaterContext:
    system_prompt: str      # the updater's instructions, filled in
    user_content: list      # the user message: the diagram, then parts 1 to 3 as text blocks
    readable_markdown: str  # the same as one readable document, with the image as a placeholder line
    stats: dict
    tools: list             # write_file, delete_file, write_proposal, finish, and run_python with the sandbox


class LeakError(RuntimeError):
    """Text the context builder generated itself contains a name the updater must never see."""


# ---- small helpers -----------------------------------------------------------------------------------------
def read_text(path):
    with open(path, encoding="utf-8") as file:
        return file.read()


def read_json(path):
    with open(path) as file:
        return json.load(file)


def hidden_score_names_pattern(scorer_config=RSI_SCORER_CONFIG):
    """HIDDEN_FIELD_NAMES plus every grid that is not a selection grid and its held-out runs. A training grid's
    training and validation recordings are the solver's own data, so only its held-out runs count. scorer_config:
    one config, or a list of them (one per device in a loop that takes turns between devices)."""
    configs = [scorer_config] if isinstance(scorer_config, (str, os.PathLike)) else list(scorer_config)
    visible_runs = set()
    for data_dirs in DEVICE_SOLVER_DATA_DIRS.values():
        if os.path.exists(os.path.join(data_dirs["clean"], "runs.json")):
            visible_runs |= set(read_json(os.path.join(data_dirs["clean"], "runs.json")))
    names = set()
    for config in configs:
        for grid in read_json(config)["grids"]:
            if grid["role"] == "selection":
                continue
            names.add(grid["name"])
            case = read_json(os.path.join(os.path.dirname(config), grid["path"], "holdout", "case.json"))
            names |= set(case["runs"]) - visible_runs
    words = "|".join(rf"\b{re.escape(name)}\b" for name in sorted(names))
    return re.compile(HIDDEN_FIELD_NAMES + (f"|{words}" if words else ""))


def estimate_tokens(text):
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def png_size(path):
    with open(path, "rb") as file:
        header = file.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    return struct.unpack(">II", header[16:24])


def image_tokens(width, height, long_edge=2576, cap=4784):
    """Visual tokens for one image on Claude 4.7 and later models: ceil(w/28) x ceil(h/28) patches, after scaling
    down anything beyond a 2576 px long edge or 4784 tokens (vision docs)."""
    scale = min(1.0, long_edge / max(width, height))
    width, height = width * scale, height * scale
    tokens = math.ceil(width / 28) * math.ceil(height / 28)
    if tokens > cap:
        scale = math.sqrt(cap / tokens)
        tokens = math.ceil(width * scale / 28) * math.ceil(height * scale / 28)
    return tokens


def fence(text, language=""):
    marker = "~~~~" if "```" in text else "```"
    return f"{marker}{language}\n{text.rstrip()}\n{marker}"


def cut_middle(text, keep):
    """Keep the first and last keep/2 characters of a long tool output. Returns (text, characters cut)."""
    if keep is None or len(text) <= keep:
        return text, 0
    half = keep // 2
    removed = len(text) - 2 * half
    return f"{text[:half]}\n[... {removed} characters cut ...]\n{text[-half:]}", removed


def model_display_name(model_id):
    """claude-haiku-5-5 -> Claude Haiku 5.5"""
    parts = model_id.split("-")
    return f"Claude {parts[1].capitalize()} {'.'.join(parts[2:])}" if len(parts) > 2 else model_id


def failure_note(failure):
    """A failure from score/public.json in plain words. Tracebacks and simulator messages are dropped."""
    task, kind, detail = failure.get("task", "?"), failure.get("failure", "?"), str(failure.get("detail", ""))
    if kind == "tds_failed":
        match = re.search(r"failed at t=([0-9.]+) s", detail)
        return f"{task}: the grid simulation failed" + (f" at t = {float(match.group(1)):.2f} s" if match else "")
    if kind == "timeout":
        return f"{task}: the grid simulation did not finish in time"
    if kind == "nan":
        return f"{task}: the grid simulation produced non-finite values"
    if kind == "unstable":
        return f"{task}: P or Q grew past the scorer's bound"
    if kind == "crash":
        return "the model could not be linearized" if task == "linearize" else f"{task}: the simulation crashed"
    if kind == "invalid_submission":
        last_line = detail.strip().splitlines()[-1][:300] if detail.strip() else ""
        last_line = remove_hidden_device_names(last_line)[0]
        return "the submission was rejected before scoring" + (f": {last_line}" if last_line else "")
    if kind == "codegen":
        return "the submission parsed but could not be built into the grid simulation"
    if kind == "scoring_timeout":
        return "the scorer did not finish with this model (too large or too slow to simulate)"
    if kind == "no_steady_gain":
        which = "frequency" if task.endswith("freq") else "voltage"
        return f"the model has no steady-state {which} droop (its low-frequency gain does not settle)"
    return f"{task}: {kind}"


def find_run_folders(paths):
    """Run folders among paths: each path is a run folder (it has meta.json) or a folder of run folders."""
    folders = []
    for path in paths:
        path = os.path.abspath(path)
        if os.path.exists(os.path.join(path, "meta.json")):
            folders.append(path)
        elif os.path.isdir(path):
            folders += sorted(os.path.join(path, name) for name in os.listdir(path)
                              if os.path.exists(os.path.join(path, name, "meta.json")))
    return folders


def _timeouts_from_transcript(path):
    if not os.path.exists(path):
        return None
    return sum(1 for message in read_json(path)["messages"] for block in message["content"]
               if block.get("type") == "tool_result" and str(block.get("content", "")).startswith("ERROR: timed out"))


def load_run_summary(run_dir):
    """What the updater may know about one finished run, or None if the run has not finished (in progress,
    crashed or stopped: it says nothing about the harness)."""
    meta = read_json(os.path.join(run_dir, "meta.json"))
    if meta.get("status", "finished") != "finished":
        return None
    run = {key: meta.get(key) for key in META_FIELDS_READ}
    run["id"] = str(meta["tag"]).rsplit("_", 1)[-1]
    device = (meta.get("labels") or {}).get("device") or meta.get("device") or "REGF1"
    run["unit"] = UNIT_LABELS.get(device, "another unit")       # never the device's own name
    run["transcript"] = os.path.join(run_dir, "transcript.json")
    run["dir"] = run_dir
    if run["tool_timeouts"] is None:                     # runs from before Oct 17 don't record it
        run["tool_timeouts"] = _timeouts_from_transcript(run["transcript"])
    public_path = os.path.join(run_dir, "score", "public.json")
    run["scored"] = os.path.exists(public_path)
    if run["scored"]:
        public = read_json(public_path)
        grids = list(public.get("grids", {}).values())
        run["composite"] = public["score"]
        run["td"] = statistics.mean(grid["td"] for grid in grids) if grids else None
        run["td_runs"] = {name: {"P": values["P"], "Q": values["Q"], "failed": "failure" in values}
                          for grid in grids for name, values in grid.get("td_runs", {}).items()}
        run["failures"] = [failure_note(failure) for grid in grids for failure in grid.get("failures", [])]
    final_path = os.path.join(run_dir, "final.md")
    final_message = read_text(final_path).strip() if os.path.exists(final_path) else ""
    source = run.get("submission_source")
    differs = run.get("final_message_differs")        # missing for runs made before Nov 10: read as None
    submission_path = os.path.join(run_dir, "submission.json")
    if source == "sandbox_file" and os.path.exists(submission_path):
        scored_copy = fence(read_text(submission_path), "json")
        if differs:
            final_message += ("\n\nThe json block in this final message differs from submission.json in the sandbox, "
                              "and the file is what was scored:\n" + scored_copy)
        elif differs is None:
            final_message += ("\n\nThe final message had no usable json block, so the submission was taken from "
                              "submission.json in the sandbox:\n" + scored_copy)
    elif source == "final_message" and (run.get("submission_rejected") or {}).get("sandbox_file"):
        final_message += (f"\n\nsubmission.json in the sandbox was not scored ({run['submission_rejected']['sandbox_file']}), "
                          "so the json block of the final message was.")
    elif source == "final_message" and run.get("budget_stop") and differs:
        final_message += ("\n\nAfter the budget stop the json block of the final message was scored; it differs from "
                          "the submission.json the solver had saved.")
    elif source == "none":
        final_message += "\n\nNo usable submission was found in the final message or the sandbox, so this run scored 2."
    run["final"] = final_message or "(no final message)"
    return run


def read_history(path):
    """history.jsonl: one record per attempt, oldest first."""
    if not path or not os.path.exists(path):
        return []
    with open(path) as file:
        return [json.loads(line) for line in file if line.strip()]


# The frequency-response check (FR) is shown only as averages over many runs: per unit and per channel, over at least
# this many runs, so no single run's error (which would let the updater solve for the true unit's response) is shown.
FR_CHANNELS = ("P/V", "P/theta", "Q/V", "Q/theta")
FR_MIN_RUNS_TABLE = 5
FR_MIN_RUNS_HISTORY = 4


def selection_fr_channels(run_dir):
    """{channel: error} of the run's selection grid, from score/private.json, or None. The one thing read from
    private.json, and only ever passed on averaged (frequency_response_by_unit)."""
    path = os.path.join(run_dir, "score", "private.json")
    if not os.path.exists(path):
        return None
    for grid in read_json(path).get("grids", {}).values():
        if grid.get("role") == "selection" and isinstance(grid.get("fr_entries"), dict):
            return {channel: float(grid["fr_entries"][channel]) for channel in FR_CHANNELS if channel in grid["fr_entries"]}
    return None


def frequency_response_by_unit(units_and_dirs, min_runs):
    """{unit: {"n": runs, channel: mean error}} over (unit, run folder) pairs, for units with at least min_runs runs
    that have the numbers. Never one run's numbers."""
    by_unit = {}
    for unit, run_dir in units_and_dirs:
        channels = selection_fr_channels(run_dir)
        if channels and len(channels) == len(FR_CHANNELS):
            by_unit.setdefault(unit, []).append(channels)
    return {unit: {"n": len(rows), **{channel: statistics.mean(row[channel] for row in rows) for channel in FR_CHANNELS}}
            for unit, rows in sorted(by_unit.items()) if len(rows) >= min_runs}


def frequency_response_text(averages, show_units):
    """'unit 1 (10 runs): P/V 1.43, P/theta 1.71, Q/V 1.45, Q/theta 0.96' for each unit."""
    return "; ".join((f"{unit}, {values['n']} runs: " if show_units else f"{values['n']} runs: ")
                     + ", ".join(f"{channel} {values[channel]:.2f}" for channel in FR_CHANNELS)
                     for unit, values in averages.items())


def flatten_for_scan(value):
    """Keys and values as plain text, so a dict pasted into a note reads like the dict itself."""
    if isinstance(value, dict):
        return " ".join(f'"{key}": {flatten_for_scan(item)}' for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return " ".join(flatten_for_scan(item) for item in value)
    return str(value)


def check_generated_text(name, text, hidden_pattern):
    match = hidden_pattern.search(text)
    if match:
        raise LeakError(f"{name} contains a hidden name: {match.group(0)!r}")
    match = SIMULATOR_AND_DEVICE_NAMES.search(text)
    if match:
        raise LeakError(f"{name} contains a name the solver must never see: {match.group(0)!r}")


# ---- the three parts of the user message, and the instructions ---------------------------------------------
def solver_view_text(harness_dir, noise, scope, units=("unit 1",)):
    """Part 1: the files the next solver run will get. units: the units the runs take turns on; each has its own
    runs.json and dataset.json."""
    prompt = read_text(TASK_PROMPT_FILE).replace("{{NOISE}}", NOISE_SENTENCES[noise])
    system_md_state = "editable in this run" if scope == "all" else "read-only in this run"
    parts = ["# Part 1. What the solver is given",
             "The image above is the system diagram, the first thing in the solver's first message.",
             "## The task prompt (locked)", fence(prompt, "text"),
             f"## system.md ({system_md_state})", fence(read_text(os.path.join(harness_dir, "system.md")), "text"),
             "## method.md (editable)", fence(read_text(os.path.join(harness_dir, "method.md")), "text"),
             "## tools/",
             "These files are copied into the solver's working directory before each run. Its code can run "
             "them or import them."]
    tools_dir = os.path.join(harness_dir, "tools")
    for folder, sub_folders, file_names in os.walk(tools_dir):
        # caches and dotfiles (.DS_Store) are not harness content
        sub_folders[:] = sorted(name for name in sub_folders if name != "__pycache__" and not name.startswith("."))
        for file_name in sorted(name for name in file_names if not name.startswith(".")):
            path = os.path.join(folder, file_name)
            relative = os.path.relpath(path, harness_dir)
            if relative == os.path.join("tools", "submission_parser.py"):   # the runner copies the locked one over it
                continue
            try:
                text = read_text(path)
            except UnicodeDecodeError:
                text = None
            language = "python" if file_name.endswith(".py") else ""
            parts += [f"### {relative} (editable)", fence(text, language) if text is not None else "(binary file, not shown)"]
    parts += ["### tools/submission_parser.py (locked: the scorer's own parser, copied in at run time)",
              fence(read_text(SUBMISSION_PARSER_FILE), "python")]
    tool = SOLVER_TOOLS[0]
    parts += ["## The solver's tool",
              f"{tool['name']}: \"{tool['description']}\" Each call starts a fresh Python process with no network, "
              f"is stopped after {CALL_TIME_LIMIT_S} s, and returns at most the last {TOOL_OUTPUT_CHARS} characters of "
              f"output. The run stops at ${API_BUDGET_USD:.0f} of API cost."]
    for unit in sorted(units):
        data_dir, which = unit_data_dir(unit, noise), (f", {unit}'s runs" if len(units) > 1 else "")
        parts += [f"## runs.json (the operator's log of each recording{which}, locked)",
                  fence(read_text(os.path.join(data_dir, "runs.json")), "json"),
                  f"## dataset.json ({unit + ', ' if len(units) > 1 else ''}locked)",
                  fence(read_text(os.path.join(data_dir, "dataset.json")), "json")]
    return "\n\n".join(parts)


def _td_cell(values):
    return "failed" if values["failed"] else f"{values['P']:.2f} / {values['Q']:.2f}"


def run_table_text(runs, runs_available, harness_sha, frequency_response=None):
    """Part 2's numbers, generated here from public.json and meta.json fields, plus frequency_response: the
    frequency-response error averaged per unit and channel (frequency_response_by_unit), never per run."""
    scored = [run for run in runs if run["scored"]]
    composites = [run["composite"] for run in scored]
    disturbance_names = []
    for run in scored:
        for name in run["td_runs"]:
            if name not in disturbance_names:
                disturbance_names.append(name)
    first = runs[0]
    units = sorted({run.get("unit", "unit 1") for run in runs})
    several = len(units) > 1
    lines = ["# Part 2. How the current harness did",
             f"Current harness {harness_sha}. The table has the {len(runs)} most recent of its {runs_available} runs, "
             f"all by {model_display_name(first['model'])} at {first['effort']} effort on the "
             f"{'noise-free' if first['noise'] == 'clean' else 'noisy'} recordings"
             + (f", taking turns between {' and '.join(units)}: different units, each identified from its own "
                "recordings and scored on its own grids (the unit column says which)." if several else ".")]
    if len(composites) > 1:
        lines.append(f"Composite over the {len(composites)} scored runs: mean {statistics.mean(composites):.3f}, median "
                     f"{statistics.median(composites):.3f}, standard deviation {statistics.stdev(composites):.3f}, lowest "
                     f"{min(composites):.3f}, highest {max(composites):.3f}.")
    if several:
        lines.append("By unit: " + "; ".join(
            f"{unit} mean {statistics.mean(run['composite'] for run in scored if run.get('unit', 'unit 1') == unit):.3f} "
            f"over {sum(1 for run in scored if run.get('unit', 'unit 1') == unit)} runs"
            for unit in units if any(run.get("unit", "unit 1") == unit for run in scored)) + ".")
    failure_counts = {name: sum(1 for run in scored if run["td_runs"].get(name, {}).get("failed"))
                      for name in disturbance_names}
    runs_with_a_failure = sum(1 for run in scored
                              if any(values["failed"] for values in run["td_runs"].values()) or not run["td_runs"])
    lines.append(f"{runs_with_a_failure} of {len(scored)} runs failed on at least one held-out disturbance. By disturbance: "
                 + ", ".join(f"{name} {failure_counts[name]}" for name in disturbance_names) + ".")
    tool_calls = sum(run["tool_calls"] or 0 for run in runs)
    timeouts = [run["tool_timeouts"] for run in runs if run["tool_timeouts"] is not None]
    if timeouts:
        lines.append(f"Tool calls stopped at {CALL_TIME_LIMIT_S} s: {sum(timeouts)} of {tool_calls}. Runs stopped by "
                     f"the budget: {sum(1 for run in runs if run['budget_stop'])}.")
    if frequency_response:
        lines.append("Frequency-response error by channel, from the task prompt's check of the model's linearization "
                     "between 0.1 and 10 Hz (0 is the real unit, 1 a model whose P and Q never move, capped at 2), "
                     "averaged over this harness's runs in the table (never shown for a single run). "
                     + ("By unit: " if several else "Over ") + frequency_response_text(frequency_response, several) + ".")
    unscored = [run["id"] for run in runs if not run["scored"]]
    if unscored:
        lines.append(f"Not scored (the scorer itself failed): {', '.join(unscored)}.")
    header = ("| run |" + (" unit |" if several else "") + " composite | TD | "
              + " | ".join(f"{name} P / Q" for name in disturbance_names) + " | steps | tool calls | timeouts | cost | budget stop |")
    rows = [header, "|" + "---|" * (len(disturbance_names) + 8 + several)]
    for run in runs:
        unit_cell = [run.get("unit", "unit 1")] if several else []
        if run["scored"]:
            cells = [run["id"], *unit_cell, f"{run['composite']:.3f}", f"{run['td']:.3f}" if run["td"] is not None else "-"]
            # no td_runs at all: the submission was rejected, or could not be built, so nothing ran
            cells += [_td_cell(run["td_runs"][name]) if name in run["td_runs"] else ("not run" if not run["td_runs"] else "-")
                      for name in disturbance_names]
        else:
            cells = [run["id"], *unit_cell, "not scored", "-"] + ["-"] * len(disturbance_names)
        cells += [str(run["steps"]), str(run["tool_calls"]),
                  "-" if run["tool_timeouts"] is None else str(run["tool_timeouts"]),
                  "-" if run["spent_usd"] is None else f"${run['spent_usd']:.3f}", "yes" if run["budget_stop"] else "no"]
        rows.append("| " + " | ".join(cells) + " |")
    lines += ["## Runs", "TD cells are P / Q for each held-out disturbance. Cost is the run's API cost, against "
              f"its budget of ${API_BUDGET_USD:.0f}.", "\n".join(rows)]
    notes = [f"- {run['id']}: " + "; ".join(run["failures"]) for run in scored if run["failures"]]
    if notes:
        lines += ["Failures:", "\n".join(notes)]
    means = []
    for name in disturbance_names:
        survived = [run["td_runs"][name] for run in scored if name in run["td_runs"] and not run["td_runs"][name]["failed"]]
        if survived:
            means.append(f"{name} P {statistics.mean(values['P'] for values in survived):.2f}, "
                         f"Q {statistics.mean(values['Q'] for values in survived):.2f} ({len(survived)} runs)")
    if means:
        lines.append("Mean TD where the disturbance did not fail: " + "; ".join(means) + ".")
    return "\n\n".join(lines)


def transcript_text(path, keep):
    """A run's transcript as text: the solver's words and code in full, tool outputs cut to keep characters.
    Returns (text, characters cut)."""
    messages = read_json(path)["messages"]
    last_assistant = max(index for index, message in enumerate(messages) if message["role"] == "assistant")
    parts = ["The solver's first message held the diagram, the task prompt, system.md and method.md shown in part 1."]
    calls = characters_cut = 0
    pointed_to_final = False
    for index, message in enumerate(messages[1:], start=1):
        for block in message["content"]:
            kind = block.get("type")
            if message["role"] == "assistant":
                if kind == "text" and block.get("text", "").strip():
                    if index != last_assistant:
                        parts.append(f"**solver:** {block['text'].strip()}")
                    elif not pointed_to_final:
                        parts.append("**solver, final message:** shown above under this run's id.")
                        pointed_to_final = True
                elif kind == "tool_use":
                    calls += 1
                    parts.append(f"**run_python call {calls}:**\n" + fence(str(block.get("input", {}).get("code", "")), "python"))
                elif kind == "thinking" and (block.get("thinking") or "").strip():
                    parts.append(f"**solver (thinking):** {block['thinking'].strip()}")
            elif kind == "tool_result":
                content = block.get("content", "")
                content = content if isinstance(content, str) else "\n".join(
                    item.get("text", "") for item in content if isinstance(item, dict))
                shown, removed = cut_middle(content, keep)
                characters_cut += removed
                parts.append(f"**output** ({len(content)} characters{f', {removed} cut from the middle' if removed else ''}):\n"
                             + fence(shown))
            elif kind == "text" and block.get("text", "").strip():
                parts.append(f"**harness:** {block['text'].strip()}")
    return "\n\n".join(parts), characters_cut


def history_text(records, show_in_full=None):
    """Part 3. records are the loop's history.jsonl lines, oldest first (rsi/README.md has the fields).
    show_in_full: only the last this-many attempts in full, the older ones as one line each."""
    parts = ["# Part 3. Earlier attempts"]
    if not records:
        parts.append("No earlier attempts: this is the first change to the starting harness.")
        return "\n\n".join(parts)
    for position, record in enumerate(records):
        heading = (f"### Attempt {record.get('iteration', position + 1)}: {record.get('candidate', '?')} from "
                   f"{record.get('parent', '?')}, {OUTCOME_DESCRIPTIONS.get(record.get('outcome'), record.get('outcome', '?'))}")
        if show_in_full is not None and position < len(records) - show_in_full:
            parts.append(heading + (f". Change: {record['change']}" if record.get("change") else ""))
            continue
        lines = [heading]
        if record.get("files_changed"):
            lines.append("Files changed: " + (record["diff_summary"] + " (lines added and removed, from the diff)"
                                              if record.get("diff_summary") else ", ".join(record["files_changed"])))
        if record.get("report_mismatch"):
            lines.append(f"The report and the diff disagree: {record['report_mismatch']}.")
        for key, label in (("root_cause", "Root cause given"), ("change", "Change"),
                           ("predicted_effect", "Predicted"), ("at_risk", "At risk")):
            if record.get(key):
                lines.append(f"{label}: {record[key]}")
        if record.get("n_candidate"):
            measured = (f"Measured: mean composite {record['mean_candidate']:.3f} over {record['n_candidate']} runs against "
                        f"{record['mean_current']:.3f} over {record['n_current']} runs of the harness it would have "
                        f"replaced, run alongside it (difference {record['mean_candidate'] - record['mean_current']:+.3f}")
            if record.get("se_difference") is not None:
                measured += f", standard error {record['se_difference']:.3f}"
            if record.get("p_value") is not None:
                measured += f", one-sided p = {record['p_value']:.2f}"
            lines.append(measured + ").")
            if record.get("by_unit"):
                lines.append("By unit, this attempt / the harness it would have replaced: " + "; ".join(
                    f"{unit} {values['mean_candidate']:.3f} / {values['mean_current']:.3f} ({values['n_candidate']} and "
                    f"{values['n_current']} runs)" for unit, values in record["by_unit"].items()) + ".")
        td_candidate, td_current = record.get("td_candidate") or {}, record.get("td_current") or {}
        if td_candidate and td_current:
            lines.append("Mean TD, this attempt / the harness it would have replaced: " + "; ".join(
                f"{name} P {td_candidate[name]['P']:.2f}/{td_current[name]['P']:.2f}, "
                f"Q {td_candidate[name]['Q']:.2f}/{td_current[name]['Q']:.2f}"
                for name in td_candidate if name in td_current) + ".")
        fr = record.get("fr_by_unit") or {}
        if fr.get("candidate") and fr.get("current"):
            show_units = len(set(fr["candidate"]) | set(fr["current"])) > 1
            lines.append("Frequency-response error by channel, averaged over each arm's runs in the block, this attempt: "
                         + frequency_response_text(fr["candidate"], show_units) + ". The harness it would have replaced: "
                         + frequency_response_text(fr["current"], show_units) + ".")
        failed_candidate, failed_current = record.get("fail_rate_candidate") or {}, record.get("fail_rate_current") or {}
        if failed_candidate and failed_current:
            lines.append("Share of runs where each disturbance failed, this attempt / the harness it would have "
                         "replaced: " + "; ".join(f"{name} {failed_candidate[name]:.0%}/{failed_current[name]:.0%}"
                                                  for name in failed_candidate if name in failed_current) + ".")
        if record.get("note"):
            lines.append(f"Note: {record['note']}")
        if record.get("diff_excerpt"):
            diff = record["diff_excerpt"]
            lines.append(("Diff:\n" if len(diff) <= 1500 else "Diff (its first 1500 characters):\n") + fence(diff[:1500], "diff"))
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def updater_instructions(model, effort, scope, lowest_score, highest_score, python_tool=False, units=("unit 1",)):
    """updater_prompt.md with its placeholders filled in. python_tool: the updater has run_python. units: the units
    the solver's runs take turns on."""
    template = read_text(UPDATER_PROMPT_FILE)
    units = sorted(units)
    if len(units) > 1:
        unit_list = ", ".join(units[:-1]) + " and " + units[-1]
        template = template.replace("{{UNITS_NOTE}}", UNITS_NOTE.replace("{{UNIT_COUNT}}", "two" if len(units) == 2 else str(len(units)))
                                    .replace("{{UNIT_LIST}}", unit_list))
    else:
        template = template.replace("\n\n{{UNITS_NOTE}}", "")
    if python_tool:
        sandbox_text = SANDBOX_TEXT
        if len(units) > 1:
            others = "; ".join(f"{unit_folder(unit)}/ holds {unit}'s" for unit in units[1:])
            sandbox_text += SANDBOX_UNITS_TEXT.replace("{{FIRST_UNIT}}", units[0]).replace("{{OTHER_UNITS}}", others)
        template = template.replace("{{SANDBOX}}", sandbox_text).replace("{{TEST_STEP}}", TEST_STEP_WITH_SANDBOX)
    else:
        template = template.replace("{{SANDBOX}}\n\n", "").replace("{{TEST_STEP}}", TEST_STEP_WITHOUT_SANDBOX)
    note = ("It is a small, fast model, so short and concrete instructions work better than long ones, and a "
            "tool that does a job reliably works better than an instruction asking the solver to do that job."
            if "haiku" in model else
            "Short and concrete instructions work better than long ones, and a tool that does a job reliably "
            "works better than an instruction asking the solver to do that job.")
    if scope == "all":
        editable = ("system.md, method.md, and any file in tools/ other than submission_parser.py. You may add new "
                    ".py files to tools/.")
        template = template.replace("{{DEVICE_RULE}}\n", "")
    else:
        editable = ("method.md, and any file in tools/ other than submission_parser.py. You may add new .py files to "
                    "tools/. system.md is shown for reference and is read-only in this run.")
        template = template.replace("{{DEVICE_RULE}}",
                                    "- Everything you write must hold for any inverter-based unit. Do not put this device's "
                                    "structure, gains, time constants, droop values, or any number fitted from these "
                                    "recordings into method.md or tools/.")
    for key, value in {"SOLVER_MODEL": model_display_name(model), "SOLVER_EFFORT": effort, "SOLVER_NOTE": note,
                       "EDITABLE": editable, "SCORE_MIN": f"{lowest_score:.2f}", "SCORE_MAX": f"{highest_score:.2f}",
                       "CALL_TIME_LIMIT_S": str(CALL_TIME_LIMIT_S), "TOOL_OUTPUT_CHARS": str(TOOL_OUTPUT_CHARS),
                       "UPDATER_OUTPUT_CHARS": str(UPDATER_OUTPUT_CHARS),
                       "SOLVER_BUDGET_USD": f"{API_BUDGET_USD:.0f}"}.items():
        template = template.replace("{{" + key + "}}", value)
    unfilled = re.findall(r"\{\{[A-Z_]+\}\}", template)
    if unfilled:
        raise ValueError(f"unfilled placeholders in {UPDATER_PROMPT_FILE}: {unfilled}")
    return template


# ---- assembly ------------------------------------------------------------------------------------------------
class UpdaterContextBuilder:
    """Everything the updater gets for one iteration.

    run_paths: run folders and/or folders of run folders, all made with harness_dir. The newest `newest_runs`
    finished runs go in the table. If the whole context is estimated above `token_budget` tokens, it is cut
    down in steps, cheapest first (see REDUCTION_PLANS). python_tool: the updater gets run_python (the caller
    provides the sandbox), and its instructions describe it."""

    # cheapest reductions first; the first plan that fits the budget is used
    REDUCTION_PLANS = (
        {"output_chars": None, "transcripts": ("best", "worst"), "history_in_full": None, "final_messages": None},
        {"output_chars": 1000, "transcripts": ("best", "worst"), "history_in_full": None, "final_messages": None},
        {"output_chars": 500, "transcripts": ("best", "worst"), "history_in_full": None, "final_messages": None},
        {"output_chars": 500, "transcripts": ("worst",), "history_in_full": None, "final_messages": None},
        {"output_chars": 500, "transcripts": ("worst",), "history_in_full": 10, "final_messages": None},
        {"output_chars": 500, "transcripts": ("worst",), "history_in_full": 5, "final_messages": 10},
    )

    def __init__(self, run_paths, harness_dir, scope="tools", history=None, newest_runs=20, tool_output_chars=2000,
                 token_budget=80000, allow_other_harness=False, scorer_config=RSI_SCORER_CONFIG, python_tool=False):
        if scope not in ("tools", "all"):
            raise ValueError("scope must be tools or all")
        self.run_paths, self.harness_dir, self.scope = run_paths, os.path.abspath(harness_dir), scope
        self.history = history or []
        self.newest_runs, self.tool_output_chars, self.token_budget = newest_runs, tool_output_chars, token_budget
        self.allow_other_harness, self.python_tool = allow_other_harness, python_tool
        self.hidden_pattern = hidden_score_names_pattern(scorer_config)
        self.warnings = []
        self.names_removed = 0

    def build(self):
        runs, runs_available = self._load_runs()
        model, effort, noise = runs[0]["model"], runs[0]["effort"], runs[0]["noise"]
        harness_sha = harness_fingerprint(self.harness_dir)
        self._check_runs_match(runs, harness_sha, noise)
        scored = [run for run in runs if run["scored"]]
        if not scored:
            raise ValueError("none of the runs has score/public.json")

        units = sorted({run["unit"] for run in runs})
        system_prompt = updater_instructions(model, effort, self.scope, min(run["composite"] for run in scored),
                                             max(run["composite"] for run in scored), self.python_tool, units)
        check_generated_text("the updater prompt", system_prompt, self.hidden_pattern)
        part1 = solver_view_text(self.harness_dir, noise, self.scope, units)
        check_generated_text("part 1 (the solver's files)", part1, self.hidden_pattern)
        frequency_response = frequency_response_by_unit([(run["unit"], run["dir"]) for run in runs if run["scored"]],
                                                        FR_MIN_RUNS_TABLE)
        table = run_table_text(runs, runs_available, harness_sha, frequency_response)
        check_generated_text("part 2 (run table)", table, self.hidden_pattern)
        for number, record in enumerate(self.history, start=1):
            check_generated_text(f"history record {number} (fields the loop writes)",
                                 flatten_for_scan({key: record.get(key) for key in LOOP_WRITTEN_HISTORY_FIELDS}),
                                 self.hidden_pattern)

        best = min(scored, key=lambda run: (run["composite"], run["tag"]))
        worst = max(scored, key=lambda run: (run["composite"], run["tag"]))
        diagram = os.path.join(unit_data_dir(units[0], noise), "system_diagram.png")   # the units share a network
        width, height = png_size(diagram)
        diagram_tokens = image_tokens(width, height)
        for plan in self.REDUCTION_PLANS:
            part2, part3, final_messages_shown, characters_cut = self._parts_2_and_3(plan, runs, table, best, worst)
            sizes = {"system": len(system_prompt), "part1": len(part1), "part2": len(part2), "part3": len(part3)}
            total_tokens = sum(estimate_tokens(text) for text in (system_prompt, part1, part2, part3)) + diagram_tokens
            if total_tokens <= self.token_budget:
                break
        reductions = self._describe_reductions(plan, best, worst, final_messages_shown, len(runs))
        if total_tokens > self.token_budget:
            self.warnings.append(f"still about {total_tokens} tokens after every reduction (budget {self.token_budget})")

        with open(diagram, "rb") as file:
            diagram_data = base64.b64encode(file.read()).decode()
        user_content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": diagram_data}},
                        {"type": "text", "text": part1}, {"type": "text", "text": part2}, {"type": "text", "text": part3}]
        markdown = "\n\n".join(["# System prompt (the updater's instructions)", system_prompt, "# User message",
                                f"[image: system_diagram.png, {width} x {height} px, about {diagram_tokens} tokens]",
                                part1, part2, part3])
        root = str(REPOSITORY_ROOT)
        shown_harness = os.path.relpath(self.harness_dir, root) if self.harness_dir.startswith(root + os.sep) else self.harness_dir
        stats = {"harness": shown_harness, "harness_sha": harness_sha, "scope": self.scope, "model": model, "effort": effort,
                 "noise": noise, "runs_in_table": [run["id"] for run in runs], "runs_available": runs_available,
                 "best": best["id"], "worst": worst["id"], "chars": sizes,
                 "tokens_est": {**{key: math.ceil(value / CHARS_PER_TOKEN) for key, value in sizes.items()},
                                "image": diagram_tokens, "total": total_tokens, "chars_per_token_assumed": CHARS_PER_TOKEN},
                 "budget": self.token_budget, "reductions": reductions, "tool_output_chars_cut": characters_cut,
                 "names_removed": self.names_removed, "history_records": len(self.history), "warnings": self.warnings,
                 "python_tool": self.python_tool, "units": units}
        tools = UPDATER_TOOLS + ([RUN_PYTHON_TOOL] if self.python_tool else [])
        return UpdaterContext(system_prompt, user_content, markdown, stats, tools)

    def _load_runs(self):
        summaries = [load_run_summary(folder) for folder in find_run_folders(self.run_paths)]
        runs = sorted((run for run in summaries if run is not None), key=lambda run: run["tag"])
        if not runs:
            raise ValueError(f"no finished runs with meta.json under {self.run_paths}")
        return runs[-self.newest_runs:], len(runs)

    def _check_runs_match(self, runs, harness_sha, noise):
        for key in ("model", "effort", "noise"):
            if len({run[key] for run in runs}) != 1:
                raise ValueError(f"the runs mix {key} values: {sorted({str(run[key]) for run in runs})}")
        others = [run["id"] for run in runs if run["harness_sha"] != harness_sha]
        if others:
            message = (f"{len(others)} of {len(runs)} runs were made with a different harness than {self.harness_dir} "
                       f"({harness_sha}): {others}")
            if not self.allow_other_harness:
                raise ValueError(message)
            self.warnings.append(message)
        today = read_text(TASK_PROMPT_FILE).replace("{{NOISE}}", NOISE_SENTENCES[noise])
        for run in runs:                                    # part 1 shows today's prompt; check the runs got it
            if os.path.exists(run["transcript"]):
                first_message = read_json(run["transcript"])["messages"][0]["content"]
                texts = [block.get("text") for block in first_message if block.get("type") == "text"]
                if texts and texts[0] != today:
                    self.warnings.append(f"run {run['id']} was given a different task prompt than today's task_prompt.md")

    def _scrub(self, text):
        cleaned, count = remove_hidden_device_names(text)
        self.names_removed += count
        return cleaned

    def _parts_2_and_3(self, plan, runs, table, best, worst):
        self.names_removed = 0
        shown = runs if plan["final_messages"] is None else runs[-plan["final_messages"]:]
        finals = ["## Final messages",
                  *(f"### {run['id']}: composite {run['composite']:.3f}\n\n{self._scrub(run['final'])}" if run["scored"]
                    else f"### {run['id']}: not scored\n\n{self._scrub(run['final'])}" for run in shown)]
        if len(shown) < len(runs):
            finals.insert(1, f"Only the {len(shown)} most recent runs' final messages fit; the table above has all {len(runs)}.")
        transcripts = ["## Transcripts"]
        characters_cut = 0
        keep = min(self.tool_output_chars, plan["output_chars"]) if plan["output_chars"] else self.tool_output_chars
        which_runs = plan["transcripts"] if best is not worst else ("worst",)
        for which in which_runs:
            run = best if which == "best" else worst
            label = "Best" if which == "best" else ("Worst" if best is not worst else "Only scored")
            if not os.path.exists(run["transcript"]):
                transcripts.append(f"### {label} run in the table: {run['id']} (transcript missing)")
                continue
            text, removed = transcript_text(run["transcript"], keep)
            characters_cut += removed
            transcripts.append(f"### {label} run in the table: {run['id']}, composite {run['composite']:.3f}\n\n{self._scrub(text)}")
        if best is not worst and "best" not in which_runs:
            transcripts.insert(1, f"Only the worst run's transcript fits. The best run, {best['id']}, has its final message above.")
        part2 = "\n\n".join([table, "\n\n".join(finals), "\n\n".join(transcripts)])
        part3 = self._scrub(history_text(self.history, plan["history_in_full"]))
        return part2, part3, len(shown), characters_cut

    def _describe_reductions(self, plan, best, worst, final_messages_shown, run_count):
        reductions = []
        if plan["output_chars"] and plan["output_chars"] < self.tool_output_chars:
            reductions.append(f"tool outputs cut to {plan['output_chars']} characters")
        if best is not worst and "best" not in plan["transcripts"]:
            reductions.append("only the worst run's transcript")
        if plan["history_in_full"] and len(self.history) > plan["history_in_full"]:
            reductions.append(f"only the last {plan['history_in_full']} attempts in full")
        if final_messages_shown < run_count:
            reductions.append(f"final messages of the last {final_messages_shown} runs only")
        return reductions


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", nargs="+", required=True, help="run folders and/or batch folders")
    parser.add_argument("--harness", required=True, help="the harness those runs used (system.md, method.md, tools/)")
    parser.add_argument("--scope", choices=["tools", "all"], default="tools")
    parser.add_argument("--history", default=None, help="history.jsonl from the RSI loop")
    parser.add_argument("--last", type=int, default=20, help="most recent runs to show")
    parser.add_argument("--cut", type=int, default=2000, help="characters kept from each tool output")
    parser.add_argument("--budget", type=int, default=80000, help="estimated input tokens to stay under")
    parser.add_argument("--out", default=None, help="folder for context.md and stats.json")
    parser.add_argument("--allow-mismatch", action="store_true", help="runs from another harness only warn")
    parser.add_argument("--config", default=str(RSI_SCORER_CONFIG), help="scorer config whose hidden grids the leak check guards")
    parser.add_argument("--count-tokens", action="store_true", help="exact count from the API (free; needs ANTHROPIC_API_KEY)")
    parser.add_argument("--model", default="claude-haiku-5-5", help="updater model, for --count-tokens")
    parser.add_argument("--python", action="store_true", help="the context as it is when the updater has run_python")
    options = parser.parse_args()
    context = UpdaterContextBuilder(options.runs, options.harness, options.scope, read_history(options.history),
                                    options.last, options.cut, options.budget, options.allow_mismatch, options.config,
                                    options.python).build()
    stats = context.stats
    if options.count_tokens:
        import anthropic
        counted = anthropic.Anthropic().messages.count_tokens(
            model=options.model, system=context.system_prompt, tools=context.tools,
            messages=[{"role": "user", "content": context.user_content}]).input_tokens
        characters = sum(stats["chars"].values())
        stats["tokens_counted"] = {"model": options.model, "input_tokens": counted,
                                   "chars_per_token": round(characters / max(1, counted - stats["tokens_est"]["image"]), 2),
                                   "note": "includes the updater's tool definitions; chars_per_token takes the image estimate off first"}
    if options.out:
        os.makedirs(options.out, exist_ok=True)
        with open(os.path.join(options.out, "context.md"), "w") as file:
            file.write(context.readable_markdown + "\n")
        with open(os.path.join(options.out, "stats.json"), "w") as file:
            json.dump(stats, file, indent=1)
    print(f"{len(stats['runs_in_table'])} runs (best {stats['best']}, worst {stats['worst']}), scope {stats['scope']}")
    print("estimated tokens: " + ", ".join(f"{key} {value}" for key, value in stats["tokens_est"].items()
                                           if key != "chars_per_token_assumed"))
    if "tokens_counted" in stats:
        print(f"counted by the API: {stats['tokens_counted']['input_tokens']} "
              f"({stats['tokens_counted']['chars_per_token']} characters a token)")
    for line in stats["reductions"] + stats["warnings"]:
        print("note:", line)
    if stats["names_removed"]:
        print(f"note: {stats['names_removed']} forbidden names replaced in solver or updater text")
    if options.out:
        print("wrote", os.path.join(options.out, "context.md"), "and stats.json")


if __name__ == "__main__":
    main()
