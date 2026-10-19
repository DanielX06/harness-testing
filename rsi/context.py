"""Assemble what the RSI updater sees: its instructions (the system prompt) and one user message of
evidence about the current harness.

    python context.py --runs ../harness_v0/runs/batch_20261013_095747_m1e1_clean \
                      --harness ../harness_v0/harness --out previews/oct13_clean
    python context.py ... --count-tokens       # exact input-token count from the free counting endpoint

From the RSI loop:

    from context import build
    ctx = build(run_dirs, harness_dir, scope="tools", history=records)
    client.messages.create(model=..., system=ctx.system, tools=ctx.tools,
                           messages=[{"role": "user", "content": ctx.content}], ...)

What goes in, and what never does, is set out in README.md. In short: the solver's own view; from
each run only the composite, the TD per held-out run and channel and a plain-language failure note
(score/public.json), the step, tool-call and cost counts (meta.json), the final message, and the
transcripts of the best and the worst run; then the history of earlier attempts. FR, PAR, grid M, grid A's held-out runs, meta.json's score
components and anything in private.json never go in, and the build stops if one of their field
names shows up in the text it generates.
"""
import argparse
import ast
import base64
import hashlib
import json
import math
import os
import re
import statistics
import struct
import sys
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                                         # Harness_testing
RUNNER = os.path.join(ROOT, "harness_v0", "run_harness.py")
PROMPT_MD = os.path.join(ROOT, "harness_v0", "prompt.md")
SYMBOLIC = os.path.join(ROOT, "scorer", "symbolic.py")
CONFIG = os.path.join(ROOT, "scorer", "config_rsi.json")             # which grids are hidden, for the leak check
BUILD_CASES = os.path.join(ROOT, "test_cases", "build_cases.py")     # its FORBIDDEN list
TEMPLATE = os.path.join(HERE, "updater_prompt.md")
DATA_DIRS = {"noisy": os.path.join(ROOT, "test_cases", "grid_A", "sandbox_data"),
             "clean": os.path.join(ROOT, "test_cases", "grid_A", "sandbox_data_clean")}


def _forbidden():
    """FORBIDDEN from build_cases.py, the names it keeps out of the solver's data, so there is one list."""
    src = open(BUILD_CASES).read()
    for node in ast.parse(src).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "FORBIDDEN" and isinstance(node.value, ast.Call)):
            flags = re.I if "re.I" in ast.get_source_segment(src, node) else 0
            return re.compile(ast.literal_eval(node.value.args[0]), flags)
    raise RuntimeError(f"{BUILD_CASES} no longer defines FORBIDDEN; update rsi/context.py")


# Text this module writes, and the files the solver is given, must never contain these names (the
# build stops). In text the solver or an earlier updater wrote, they are replaced and counted in
# stats["names_removed"].
FORBIDDEN = _forbidden()
# Field names that exist only in the hidden components or the scorer's private output. hidden_pattern()
# adds the names of the hidden grids and of their held-out runs, read from CONFIG.
HIDDEN_FIELDS = (r"fr_entries|par_entries|role_scores|train_holdout|private\.json|td_runs_full|fr_detail"
                 r"|par_detail|droop_truth|gains_truth|\"(?:fr|par)\"\s*:")
# The only meta.json fields read. Never "components", "role_scores" or "score_selection".
META_KEYS = ("tag", "model", "effort", "harness_sha", "spent_usd", "steps", "tool_calls", "tool_timeouts",
             "budget_stop", "submission_source", "noise")
# A deliberately high estimate of the token count. English prose runs near 3.5 characters a token on
# earlier Claude tokenizers, and code and tables of numbers run denser. Claude 4.7 and later models,
# Haiku 5.5 among them, use a tokenizer that can give up to about 35% more tokens for the same text.
# --count-tokens returns the exact count and the ratio to put here.
CHARS_PER_TOKEN = 2.5
OUTCOME = {
    "accepted": "kept: it became the current harness",
    "rejected": "rejected: not better by more than run-to-run variation",
    "rejected_early": "rejected early: after the first block of runs it was not better at all",
    "reverted": "accepted, then reverted because fresh runs did not confirm it",
    "invalid": "never run: it failed the checks made before any solver run",
    "repeat": "never run: too close to an earlier rejected attempt",
}


@dataclass
class Context:
    system: str          # the updater's instructions, filled in
    content: list        # the user message: the diagram, then parts 1 to 3 as text blocks
    markdown: str        # the same as one readable document, with the image as a placeholder line
    stats: dict
    tools: list          # write_file, delete_file, finish


class LeakError(RuntimeError):
    pass


# ---- small helpers ------------------------------------------------------------------------------
RUNNER_NAMES = ("NOISE_SENTENCE", "TOOLS", "TOOL_OUT_CHARS", "CAP", "MODELS", "CACHE_WRITE", "MAX_TOKENS", "IMAGE")


def _runner():
    """NOISE_SENTENCE, TOOLS, TOOL_OUT_CHARS, CAP, MODELS, CACHE_WRITE, MAX_TOKENS, IMAGE and harness_hash(),
    read from run_harness.py itself, so the updater is told exactly what the runner does, harness hashes
    match meta.json, and propose.py prices the updater the way the runner prices the solver."""
    src = open(RUNNER).read()
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in RUNNER_NAMES:
                out[node.targets[0].id] = ast.literal_eval(node.value)
        elif isinstance(node, ast.FunctionDef) and node.name == "harness_hash":
            ns = {"hashlib": hashlib, "os": os}
            exec(compile(ast.Module([node], type_ignores=[]), RUNNER, "exec"), ns)
            out["harness_hash"] = ns["harness_hash"]
    missing = (set(RUNNER_NAMES) | {"harness_hash"}) - set(out)
    if missing:
        raise RuntimeError(f"run_harness.py no longer defines {sorted(missing)}; update rsi/context.py")
    return out


def hidden_pattern(config=CONFIG):
    """HIDDEN_FIELDS plus every grid that isn't a selection grid and its held-out runs. Grid A's
    training and validation recordings are the solver's own data, so only its test runs count."""
    visible = set(json.load(open(os.path.join(DATA_DIRS["clean"], "runs.json"))))
    names = set()
    for g in json.load(open(config))["grids"]:
        if g["role"] == "selection":
            continue
        names.add(g["name"])
        case = json.load(open(os.path.join(os.path.dirname(config), g["path"], "holdout", "case.json")))
        names |= set(case["runs"]) - visible
    words = "|".join(rf"\b{re.escape(n)}\b" for n in sorted(names))
    return re.compile(HIDDEN_FIELDS + (f"|{words}" if words else ""))


def est_tokens(text):
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    return struct.unpack(">II", head[16:24])


def image_tokens(w, h, long_edge=2576, cap=4784):
    """Visual tokens for one image on Claude 4.7 and later models: ceil(w/28) x ceil(h/28) patches, after
    scaling down anything beyond a 2576 px long edge or 4784 tokens (vision docs)."""
    s = min(1.0, long_edge / max(w, h))
    w, h = w * s, h * s
    t = math.ceil(w / 28) * math.ceil(h / 28)
    if t > cap:
        s = math.sqrt(cap / t)
        t = math.ceil(w * s / 28) * math.ceil(h * s / 28)
    return t


def fence(text, lang=""):
    f = "~~~~" if "```" in text else "```"
    return f"{f}{lang}\n{text.rstrip()}\n{f}"


def cut_middle(text, keep):
    """Keep the first and last keep/2 characters of a long tool output."""
    if keep is None or len(text) <= keep:
        return text, 0
    half = keep // 2
    n = len(text) - 2 * half
    return f"{text[:half]}\n[... {n} characters cut ...]\n{text[-half:]}", n


def model_name(model_id):
    """claude-haiku-5-5 -> Claude Haiku 5.5"""
    parts = model_id.split("-")
    return f"Claude {parts[1].capitalize()} {'.'.join(parts[2:])}" if len(parts) > 2 else model_id


def failure_note(f):
    """A failure from score/public.json in plain words. Tracebacks and simulator messages are dropped."""
    task, kind, detail = f.get("task", "?"), f.get("failure", "?"), str(f.get("detail", ""))
    if kind == "tds_failed":
        m = re.search(r"failed at t=([0-9.]+) s", detail)
        return f"{task}: the grid simulation failed" + (f" at t = {float(m.group(1)):.2f} s" if m else "")
    if kind == "timeout":
        return f"{task}: the grid simulation did not finish in time"
    if kind == "nan":
        return f"{task}: the grid simulation produced non-finite values"
    if kind == "unstable":
        return f"{task}: P or Q grew past the scorer's bound"
    if kind == "crash":
        return "the model could not be linearized" if task == "linearize" else f"{task}: the simulation crashed"
    if kind == "invalid_submission":
        last = detail.strip().splitlines()[-1][:300] if detail.strip() else ""
        last = FORBIDDEN.sub("[name removed]", last)
        return "the submission was rejected before scoring" + (f": {last}" if last else "")
    if kind == "codegen":
        return "the submission parsed but could not be built into the grid simulation"
    if kind == "no_steady_gain":
        which = "frequency" if task.endswith("freq") else "voltage"
        return f"the model has no steady-state {which} droop (its low-frequency gain does not settle)"
    return f"{task}: {kind}"


def _run_dirs(paths):
    out = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.exists(os.path.join(p, "meta.json")):
            out.append(p)
        else:
            out += sorted(os.path.join(p, d) for d in os.listdir(p)
                          if os.path.exists(os.path.join(p, d, "meta.json")))
    return out


def _timeouts_from_transcript(path):
    if not os.path.exists(path):
        return None
    msgs = json.load(open(path))["messages"]
    return sum(1 for m in msgs for b in m["content"]
               if b.get("type") == "tool_result" and str(b.get("content", "")).startswith("ERROR: timed out"))


def load_run(d):
    meta = json.load(open(os.path.join(d, "meta.json")))
    r = {k: meta.get(k) for k in META_KEYS}
    r["id"] = str(meta["tag"]).rsplit("_", 1)[-1]
    r["transcript"] = os.path.join(d, "transcript.json")
    if r["tool_timeouts"] is None:                       # runs from before Oct 17 don't record it
        r["tool_timeouts"] = _timeouts_from_transcript(r["transcript"])
    pub_path = os.path.join(d, "score", "public.json")
    r["scored"] = os.path.exists(pub_path)
    if r["scored"]:
        pub = json.load(open(pub_path))
        grids = list(pub.get("grids", {}).values())
        r["composite"] = pub["score"]
        r["td"] = statistics.mean(g["td"] for g in grids) if grids else None
        r["td_runs"] = {name: {"P": v["P"], "Q": v["Q"], "failed": "failure" in v}
                        for g in grids for name, v in g.get("td_runs", {}).items()}
        r["failures"] = [failure_note(f) for g in grids for f in g.get("failures", [])]
    final_path = os.path.join(d, "final.md")
    final = open(final_path).read().strip() if os.path.exists(final_path) else ""
    source = r.get("submission_source")
    if source == "sandbox_file" and os.path.exists(os.path.join(d, "submission.json")):
        final += ("\n\nThe final message had no usable json block, so the submission was taken from "
                  "submission.json in the sandbox:\n" + fence(open(os.path.join(d, "submission.json")).read(), "json"))
    elif source == "none":
        final += "\n\nNo usable submission was found in the final message or the sandbox, so this run scored 2."
    r["final"] = final or "(no final message)"
    return r


# ---- the three parts of the user message --------------------------------------------------------
def _read_text(path):
    try:
        return open(path, encoding="utf-8").read()
    except UnicodeDecodeError:
        return None


def solver_view(R, harness_dir, noise, scope):
    """Part 1, from the files the next solver run will get."""
    prompt = open(PROMPT_MD).read().replace("{{NOISE}}", R["NOISE_SENTENCE"][noise])
    data = DATA_DIRS[noise]
    sys_state = "editable in this run" if scope == "all" else "read-only in this run"
    out = ["# Part 1. What the solver is given",
           "The image above is the system diagram, the first thing in the solver's first message.",
           "## The task prompt (locked)", fence(prompt, "text"),
           f"## system.md ({sys_state})", fence(open(os.path.join(harness_dir, "system.md")).read(), "text"),
           "## method.md (editable)", fence(open(os.path.join(harness_dir, "method.md")).read(), "text"),
           "## tools/",
           "These files are copied into the solver's working directory before each run. Its code can run "
           "them or import them."]
    tools_dir = os.path.join(harness_dir, "tools")
    # top-down walk, pruned and sorted in place: caches and dotfiles (.DS_Store) are not harness content
    for base, dirs, files in os.walk(tools_dir):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__" and not x.startswith("."))
        for f in sorted(x for x in files if not x.startswith(".")):
            p = os.path.join(base, f)
            rel = os.path.relpath(p, harness_dir)
            if rel == os.path.join("tools", "symbolic.py"):      # the runner copies the locked one over it
                continue
            text = _read_text(p)
            lang = "python" if f.endswith(".py") else ""
            out += [f"### {rel} (editable)", fence(text, lang) if text is not None else "(binary file, not shown)"]
    out += ["### tools/symbolic.py (locked: the scorer's own parser, copied in at run time)",
            fence(open(SYMBOLIC).read(), "python")]
    tool = R["TOOLS"][0]
    out += ["## The solver's tool",
            f"{tool['name']}: \"{tool['description']}\" Each call starts a fresh Python process with no network, "
            f"is stopped after 120 s, and returns at most the last {R['TOOL_OUT_CHARS']} characters of output. "
            f"The run stops at ${R['CAP']:.0f} of API cost.",
            "## runs.json (the operator's log of each recording, locked)", fence(open(os.path.join(data, "runs.json")).read(), "json"),
            "## dataset.json (locked)", fence(open(os.path.join(data, "dataset.json")).read(), "json")]
    return "\n\n".join(out)


def _fmt_td(v):
    return "failed" if v["failed"] else f"{v['P']:.2f} / {v['Q']:.2f}"


def runs_summary(runs, n_available, harness_sha, cap):
    """Part 2's numbers: generated here from public.json and meta.json fields only."""
    scored = [r for r in runs if r["scored"]]
    comp = [r["composite"] for r in scored]
    names = []
    for r in scored:
        for k in r["td_runs"]:
            if k not in names:
                names.append(k)
    first = runs[0]
    lines = ["# Part 2. How the current harness did",
             f"Current harness {harness_sha}. The table has the {len(runs)} most recent of its {n_available} runs, "
             f"all by {model_name(first['model'])} at {first['effort']} effort on the "
             f"{'noise-free' if first['noise'] == 'clean' else 'noisy'} recordings."]
    if len(comp) > 1:
        lines.append(f"Composite over the {len(comp)} scored runs: mean {statistics.mean(comp):.3f}, median "
                     f"{statistics.median(comp):.3f}, standard deviation {statistics.stdev(comp):.3f}, lowest "
                     f"{min(comp):.3f}, highest {max(comp):.3f}.")
    fails = {k: sum(1 for r in scored if r["td_runs"].get(k, {}).get("failed")) for k in names}
    any_fail = sum(1 for r in scored if any(v["failed"] for v in r["td_runs"].values()) or not r["td_runs"])
    lines.append(f"{any_fail} of {len(scored)} runs failed on at least one held-out disturbance. By disturbance: "
                 + ", ".join(f"{k} {fails[k]}" for k in names) + ".")
    calls = sum(r["tool_calls"] or 0 for r in runs)
    tos = [r["tool_timeouts"] for r in runs if r["tool_timeouts"] is not None]
    if tos:
        lines.append(f"Tool calls stopped at 120 s: {sum(tos)} of {calls}. Runs stopped by the budget: "
                     f"{sum(1 for r in runs if r['budget_stop'])}.")
    unscored = [r["id"] for r in runs if not r["scored"]]
    if unscored:
        lines.append(f"Not scored (the scorer itself failed): {', '.join(unscored)}.")
    head = "| run | composite | TD | " + " | ".join(f"{k} P / Q" for k in names) + \
           " | steps | tool calls | timeouts | cost | budget stop |"
    rows = [head, "|" + "---|" * (len(names) + 8)]
    for r in runs:
        if r["scored"]:
            cells = [r["id"], f"{r['composite']:.3f}", f"{r['td']:.3f}" if r["td"] is not None else "-"]
            # no td_runs at all: the submission was rejected, or could not be built, so nothing ran
            cells += [_fmt_td(r["td_runs"][k]) if k in r["td_runs"] else ("not run" if not r["td_runs"] else "-")
                      for k in names]
        else:
            cells = [r["id"], "not scored", "-"] + ["-"] * len(names)
        cells += [str(r["steps"]), str(r["tool_calls"]),
                  "-" if r["tool_timeouts"] is None else str(r["tool_timeouts"]),
                  "-" if r["spent_usd"] is None else f"${r['spent_usd']:.3f}", "yes" if r["budget_stop"] else "no"]
        rows.append("| " + " | ".join(cells) + " |")
    lines += ["## Runs", "TD cells are P / Q for each held-out disturbance. Cost is the run's API cost, against "
              f"its budget of ${cap:.0f}.", "\n".join(rows)]
    notes = [f"- {r['id']}: " + "; ".join(r["failures"]) for r in scored if r["failures"]]
    if notes:
        lines += ["Failures:", "\n".join(notes)]
    means = []
    for k in names:
        ok = [r["td_runs"][k] for r in scored if k in r["td_runs"] and not r["td_runs"][k]["failed"]]
        if ok:
            means.append(f"{k} P {statistics.mean(v['P'] for v in ok):.2f}, Q {statistics.mean(v['Q'] for v in ok):.2f} "
                         f"({len(ok)} runs)")
    if means:
        lines.append("Mean TD where the disturbance did not fail: " + "; ".join(means) + ".")
    return "\n\n".join(lines)


def render_transcript(path, keep):
    """A run's transcript as text: the solver's words and code in full, tool outputs cut to keep characters."""
    msgs = json.load(open(path))["messages"]
    last = max(i for i, m in enumerate(msgs) if m["role"] == "assistant")
    out = ["The solver's first message held the diagram, the task prompt, system.md and method.md shown in part 1."]
    calls = cut_total = 0
    pointer = False
    for i, m in enumerate(msgs[1:], start=1):
        for b in m["content"]:
            t = b.get("type")
            if m["role"] == "assistant":
                if t == "text" and b.get("text", "").strip():
                    if i != last:
                        out.append(f"**solver:** {b['text'].strip()}")
                    elif not pointer:
                        out.append("**solver, final message:** shown above under this run's id.")
                        pointer = True
                elif t == "tool_use":
                    calls += 1
                    out.append(f"**run_python call {calls}:**\n" + fence(str(b.get("input", {}).get("code", "")), "python"))
                elif t == "thinking" and (b.get("thinking") or "").strip():
                    out.append(f"**solver (thinking):** {b['thinking'].strip()}")
            elif t == "tool_result":
                c = b.get("content", "")
                c = c if isinstance(c, str) else "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
                shown, n = cut_middle(c, keep)
                cut_total += n
                out.append(f"**output** ({len(c)} characters{f', {n} cut from the middle' if n else ''}):\n" + fence(shown))
            elif t == "text" and b.get("text", "").strip():
                out.append(f"**harness:** {b['text'].strip()}")
    return "\n\n".join(out), cut_total


def render_history(records, full_last=None):
    """Part 3. records are dicts written by the RSI loop, oldest first (README.md has the fields)."""
    out = ["# Part 3. Earlier attempts"]
    if not records:
        out.append("No earlier attempts: this is the first change to the starting harness.")
        return "\n\n".join(out)
    n = len(records)
    for j, r in enumerate(records):
        head = (f"### Attempt {r.get('iteration', j + 1)}: {r.get('candidate', '?')} from {r.get('parent', '?')}, "
                f"{OUTCOME.get(r.get('outcome'), r.get('outcome', '?'))}")
        if full_last is not None and j < n - full_last:
            out.append(head + (f". Change: {r['change']}" if r.get("change") else ""))
            continue
        lines = [head]
        if r.get("files_changed"):
            lines.append("Files changed: " + ", ".join(r["files_changed"]))
        for key, label in (("root_cause", "Root cause given"), ("change", "Change"),
                           ("predicted_effect", "Predicted"), ("at_risk", "At risk")):
            if r.get(key):
                lines.append(f"{label}: {r[key]}")
        if r.get("n_candidate"):
            m = (f"Measured: mean composite {r['mean_candidate']:.3f} over {r['n_candidate']} runs against "
                 f"{r['mean_incumbent']:.3f} over {r['n_incumbent']} runs of the harness it would have replaced "
                 f"(difference {r['mean_candidate'] - r['mean_incumbent']:+.3f}")
            if r.get("se_diff") is not None:
                m += f", standard error {r['se_diff']:.3f}"
            if r.get("p_value") is not None:
                m += f", one-sided p = {r['p_value']:.2f}"
            lines.append(m + ").")
        tdc, tdi = r.get("td_candidate") or {}, r.get("td_incumbent") or {}
        if tdc and tdi:
            lines.append("Mean TD, this attempt / the harness it would have replaced: " + "; ".join(
                f"{k} P {tdc[k]['P']:.2f}/{tdi[k]['P']:.2f}, Q {tdc[k]['Q']:.2f}/{tdi[k]['Q']:.2f}"
                for k in tdc if k in tdi) + ".")
        fc, fi = r.get("fail_rate_candidate") or {}, r.get("fail_rate_incumbent") or {}
        if fc and fi:
            lines.append("Share of runs where each disturbance failed, this attempt / the harness it would have "
                         "replaced: " + "; ".join(f"{k} {fc[k]:.0%}/{fi[k]:.0%}" for k in fc if k in fi) + ".")
        if r.get("note"):
            lines.append(f"Note: {r['note']}")
        if r.get("diff_excerpt"):
            d = r["diff_excerpt"]
            lines.append(("Diff:\n" if len(d) <= 1500 else "Diff (its first 1500 characters):\n")
                         + fence(d[:1500], "diff"))
        out.append("\n".join(lines))
    return "\n\n".join(out)


def fill_prompt(R, model, effort, scope, score_min, score_max):
    t = open(TEMPLATE).read()
    note = ("It is a small, fast model, so short and concrete instructions work better than long ones, and a "
            "tool that does a job reliably works better than an instruction asking the solver to do that job."
            if "haiku" in model else
            "Short and concrete instructions work better than long ones, and a tool that does a job reliably "
            "works better than an instruction asking the solver to do that job.")
    if scope == "all":
        editable = ("system.md, method.md, and any file in tools/ other than symbolic.py. You may add new .py "
                    "files to tools/.")
        t = t.replace("{{DEVICE_RULE}}\n", "")
    else:
        editable = ("method.md, and any file in tools/ other than symbolic.py. You may add new .py files to "
                    "tools/. system.md is shown for reference and is read-only in this run.")
        t = t.replace("{{DEVICE_RULE}}",
                      "- Everything you write must hold for any inverter-based unit. Do not put this device's "
                      "structure, gains, time constants, droop values, or any number fitted from these recordings "
                      "into method.md or tools/.")
    for k, v in {"SOLVER_MODEL": model_name(model), "SOLVER_EFFORT": effort, "SOLVER_NOTE": note,
                 "EDITABLE": editable, "SCORE_MIN": f"{score_min:.2f}", "SCORE_MAX": f"{score_max:.2f}"}.items():
        t = t.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", t)
    if left:
        raise ValueError(f"unfilled placeholders in {TEMPLATE}: {left}")
    return t


# ---- assembly -------------------------------------------------------------------------------------
# The updater's tools. The loop applies the writes to a copy of the current harness, refuses paths
# outside the editable files for the scope, and stops at finish.
UPDATER_TOOLS = [
    {"name": "write_file",
     "description": "Write one file of the new harness with its complete content. path is relative to the "
                    "harness folder: method.md, system.md when it is editable, or tools/<name>.py. Files you "
                    "do not write stay as they are.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "delete_file",
     "description": "Remove one file from tools/ in the new harness. method.md, system.md and tools/symbolic.py "
                    "cannot be removed.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "finish",
     "description": "Submit the new harness. Call it once, after all your write_file and delete_file calls.",
     "input_schema": {"type": "object", "properties": {
         "evidence": {"type": "string", "description": "the run ids and what happened in them"},
         "root_cause": {"type": "string", "description": "what in the harness causes it"},
         "change": {"type": "string", "description": "what you changed, in one or two sentences"},
         "predicted_effect": {"type": "string", "description": "which numbers should move, and roughly how far"},
         "at_risk": {"type": "string", "description": "what could get worse"}},
         "required": ["evidence", "root_cause", "change", "predicted_effect", "at_risk"]}},
]
# History fields the RSI loop writes itself (the rest is the updater's own text and its diff). A hidden
# name in one of these means the loop put something there it should not have, so the build stops.
LOOP_FIELDS = ("iteration", "candidate", "parent", "outcome", "files_changed", "n_candidate", "n_incumbent",
               "mean_candidate", "mean_incumbent", "se_diff", "p_value", "td_candidate", "td_incumbent",
               "fail_rate_candidate", "fail_rate_incumbent", "note")


def _flat(x):
    """Keys and values as plain text, so a dict pasted into a note reads like the dict itself."""
    if isinstance(x, dict):
        return " ".join(f'"{k}": {_flat(v)}' for k, v in x.items())
    if isinstance(x, (list, tuple)):
        return " ".join(_flat(v) for v in x)
    return str(x)


def _check_generated(name, text, hidden):
    m = hidden.search(text)
    if m:
        raise LeakError(f"{name} contains a hidden name: {m.group(0)!r}")
    m = FORBIDDEN.search(text)
    if m:
        raise LeakError(f"{name} contains a name the solver must never see: {m.group(0)!r}")


def build(run_paths, harness_dir, scope="tools", history=None, last=20, cut=2000, budget=80000,
          allow_mismatch=False, config=CONFIG):
    """Everything the updater gets for one iteration. run_paths: run folders and/or batch folders."""
    if scope not in ("tools", "all"):
        raise ValueError("scope must be tools or all")
    R = _runner()
    hidden = hidden_pattern(config)
    history = history or []
    harness_dir = os.path.abspath(harness_dir)
    runs = sorted((load_run(d) for d in _run_dirs(run_paths)), key=lambda r: r["tag"])
    if not runs:
        raise ValueError(f"no runs with meta.json under {run_paths}")
    n_available = len(runs)
    runs = runs[-last:]
    for key in ("model", "effort", "noise"):
        if len({r[key] for r in runs}) != 1:
            raise ValueError(f"the runs mix {key} values: {sorted({str(r[key]) for r in runs})}")
    model, effort, noise = runs[0]["model"], runs[0]["effort"], runs[0]["noise"]
    warnings = []
    sha = R["harness_hash"](harness_dir)
    other = [r["id"] for r in runs if r["harness_sha"] != sha]
    if other:
        msg = f"{len(other)} of {len(runs)} runs were made with a different harness than {harness_dir} ({sha}): {other}"
        if not allow_mismatch:
            raise ValueError(msg)
        warnings.append(msg)
    scored = [r for r in runs if r["scored"]]
    if not scored:
        raise ValueError("none of the runs has score/public.json")
    now = open(PROMPT_MD).read().replace("{{NOISE}}", R["NOISE_SENTENCE"][noise])
    for r in runs:                                        # part 1 shows today's prompt.md; check the runs got it
        if os.path.exists(r["transcript"]):
            first = json.load(open(r["transcript"]))["messages"][0]["content"]
            got = [b.get("text") for b in first if b.get("type") == "text"]
            if got and got[0] != now:
                warnings.append(f"run {r['id']} was given a different task prompt than today's prompt.md")

    system = fill_prompt(R, model, effort, scope, min(r["composite"] for r in scored),
                         max(r["composite"] for r in scored))
    _check_generated("the updater prompt", system, hidden)
    part1 = solver_view(R, harness_dir, noise, scope)
    _check_generated("part 1 (the solver's files)", part1, hidden)
    summary = runs_summary(runs, n_available, sha, R["CAP"])
    _check_generated("part 2 (run table)", summary, hidden)
    for j, rec in enumerate(history):
        _check_generated(f"history record {j + 1} (fields the loop writes)",
                         _flat({k: rec.get(k) for k in LOOP_FIELDS}), hidden)

    best = min(scored, key=lambda r: (r["composite"], r["tag"]))
    worst = max(scored, key=lambda r: (r["composite"], r["tag"]))
    diagram = os.path.join(DATA_DIRS[noise], "system_diagram.png")
    w, h = png_size(diagram)
    img_tok = image_tokens(w, h)
    removed = [0]

    def scrub(text):
        def rep(_):
            removed[0] += 1
            return "[name removed]"
        return FORBIDDEN.sub(rep, text)

    # cheapest reductions first; stop at the first plan that fits the budget
    both = ("best", "worst") if best is not worst else ("worst",)
    plans = [dict(keep=cut, which=both, full_last=None, finals=None),
             dict(keep=min(cut, 1000), which=both, full_last=None, finals=None),
             dict(keep=min(cut, 500), which=both, full_last=None, finals=None),
             dict(keep=min(cut, 500), which=("worst",), full_last=None, finals=None),
             dict(keep=min(cut, 500), which=("worst",), full_last=10, finals=None),
             dict(keep=min(cut, 500), which=("worst",), full_last=5, finals=10)]
    for i, plan in enumerate(plans):
        removed[0] = 0
        finals = runs if plan["finals"] is None else runs[-plan["finals"]:]
        fin = ["## Final messages",
               *(f"### {r['id']}: composite {r['composite']:.3f}\n\n{scrub(r['final'])}" if r["scored"]
                 else f"### {r['id']}: not scored\n\n{scrub(r['final'])}" for r in finals)]
        if len(finals) < len(runs):
            fin.insert(1, f"Only the {len(finals)} most recent runs' final messages fit; the table above has all {len(runs)}.")
        tr = ["## Transcripts"]
        cut_chars = 0
        for which in plan["which"]:
            r = best if which == "best" else worst
            label = "Best" if which == "best" else ("Worst" if best is not worst else "Only scored")
            if not os.path.exists(r["transcript"]):
                tr.append(f"### {label} run in the table: {r['id']} (transcript missing)")
                continue
            text, n = render_transcript(r["transcript"], plan["keep"])
            cut_chars += n
            tr.append(f"### {label} run in the table: {r['id']}, composite {r['composite']:.3f}\n\n{scrub(text)}")
        if best is not worst and "best" not in plan["which"]:
            tr.insert(1, f"Only the worst run's transcript fits. The best run, {best['id']}, has its final message above.")
        part2 = "\n\n".join([summary, "\n\n".join(fin), "\n\n".join(tr)])
        part3 = scrub(render_history(history, plan["full_last"]))
        sizes = {"system": len(system), "part1": len(part1), "part2": len(part2), "part3": len(part3)}
        total = sum(est_tokens(t) for t in (system, part1, part2, part3)) + img_tok
        if total <= budget or i == len(plans) - 1:
            break
    reductions = []
    if plan["keep"] < cut:
        reductions.append(f"tool outputs cut to {plan['keep']} characters")
    if best is not worst and "best" not in plan["which"]:
        reductions.append("only the worst run's transcript")
    if plan["full_last"] and len(history) > plan["full_last"]:
        reductions.append(f"only the last {plan['full_last']} attempts in full")
    if len(finals) < len(runs):
        reductions.append(f"final messages of the last {len(finals)} runs only")
    if total > budget:
        warnings.append(f"still about {total} tokens after every reduction (budget {budget})")

    with open(diagram, "rb") as f:
        png = base64.b64encode(f.read()).decode()
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png}},
               {"type": "text", "text": part1}, {"type": "text", "text": part2}, {"type": "text", "text": part3}]
    markdown = "\n\n".join(["# System prompt (the updater's instructions)", system,
                            "# User message", f"[image: system_diagram.png, {w} x {h} px, about {img_tok} tokens]",
                            part1, part2, part3])
    shown = os.path.relpath(harness_dir, ROOT) if harness_dir.startswith(ROOT + os.sep) else harness_dir
    stats = {"harness": shown, "harness_sha": sha, "scope": scope, "model": model, "effort": effort,
             "noise": noise, "runs_in_table": [r["id"] for r in runs], "runs_available": n_available,
             "best": best["id"], "worst": worst["id"], "chars": sizes,
             "tokens_est": {**{k: math.ceil(v / CHARS_PER_TOKEN) for k, v in sizes.items()}, "image": img_tok,
                            "total": total, "chars_per_token_assumed": CHARS_PER_TOKEN},
             "budget": budget, "reductions": reductions, "tool_output_chars_cut": cut_chars,
             "names_removed": removed[0], "history_records": len(history), "warnings": warnings}
    return Context(system, content, markdown, stats, UPDATER_TOOLS)


def read_history(path):
    """history.jsonl: one record per line, oldest first."""
    if not path or not os.path.exists(path):
        return []
    return [json.loads(line) for line in open(path) if line.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", nargs="+", required=True, help="run folders and/or batch folders")
    ap.add_argument("--harness", required=True, help="the harness those runs used (system.md, method.md, tools/)")
    ap.add_argument("--scope", choices=["tools", "all"], default="tools")
    ap.add_argument("--history", default=None, help="history.jsonl from the RSI loop")
    ap.add_argument("--last", type=int, default=20, help="most recent runs to show")
    ap.add_argument("--cut", type=int, default=2000, help="characters kept from each tool output")
    ap.add_argument("--budget", type=int, default=80000, help="estimated input tokens to stay under")
    ap.add_argument("--out", default=None, help="folder for context.md and stats.json")
    ap.add_argument("--allow-mismatch", action="store_true", help="runs from another harness only warn")
    ap.add_argument("--config", default=CONFIG, help="scorer config whose hidden grids the leak check guards")
    ap.add_argument("--count-tokens", action="store_true", help="exact count from the API (free; needs ANTHROPIC_API_KEY)")
    ap.add_argument("--model", default="claude-haiku-5-5", help="updater model, for --count-tokens")
    a = ap.parse_args()
    ctx = build(a.runs, a.harness, a.scope, read_history(a.history), a.last, a.cut, a.budget, a.allow_mismatch,
                a.config)
    if a.count_tokens:
        import anthropic
        n = anthropic.Anthropic().messages.count_tokens(
            model=a.model, system=ctx.system, tools=ctx.tools,
            messages=[{"role": "user", "content": ctx.content}]).input_tokens
        chars = sum(ctx.stats["chars"].values())
        ctx.stats["tokens_counted"] = {"model": a.model, "input_tokens": n,
                                       "chars_per_token": round(chars / max(1, n - ctx.stats["tokens_est"]["image"]), 2),
                                       "note": "includes the updater's tool definitions; chars_per_token "
                                               "takes the image estimate off first"}
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        open(os.path.join(a.out, "context.md"), "w").write(ctx.markdown + "\n")
        json.dump(ctx.stats, open(os.path.join(a.out, "stats.json"), "w"), indent=1)
    s = ctx.stats
    print(f"{len(s['runs_in_table'])} runs (best {s['best']}, worst {s['worst']}), scope {s['scope']}")
    print("estimated tokens: " + ", ".join(f"{k} {v}" for k, v in s["tokens_est"].items()
                                           if k != "chars_per_token_assumed"))
    if "tokens_counted" in s:
        print(f"counted by the API: {s['tokens_counted']['input_tokens']} "
              f"({s['tokens_counted']['chars_per_token']} characters a token)")
    for line in s["reductions"] + s["warnings"]:
        print("note:", line)
    if s["names_removed"]:
        print(f"note: {s['names_removed']} forbidden names replaced in solver or updater text")
    if a.out:
        print("wrote", os.path.join(a.out, "context.md"), "and stats.json")


if __name__ == "__main__":
    sys.exit(main())
