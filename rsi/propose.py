"""One updater call: build its context from the current harness's runs, let it edit a copy of the harness,
and check the result before any solver run sees it.

    python propose.py --runs ../harness_v0/runs/batch_20261013_095747_m1e1_clean \
                      --harness ../harness_v0/harness --out candidates/h001

Writes, under --out:
    harness/          the candidate harness (system.md, method.md, tools/), ready for run_harness.py --harness
    proposal.json     status, the updater's manifest (its finish call), files changed, checks, warnings,
                      parent and candidate hashes, turns, tokens and cost
    diff.patch        the candidate against its parent
    transcript.json   the updater's whole exchange (the user message's image replaced by its file name)
    context.md, context_stats.json   what the updater was given

Before a finish is accepted, the updater sees its own checker run on the best and worst runs' submissions
once (the self-test) and has to call finish again. --no-self-test skips that.

status is "ok" (ready for solver runs), "invalid" (failed a check; never run), "no_change", "no_finish"
(it stopped or ran out of turns without calling finish) or "over_budget". Only "ok" candidates go on.

From the loop (step 4): propose(run_paths, harness_dir, out_dir, ...) returns the proposal dict.
"""
import argparse
import ast
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import context as C  # noqa: E402

TOOL_NAME = re.compile(r"^tools/[A-Za-z_][A-Za-z0-9_]*\.py$")
MAX_FILE_CHARS = 60000          # one file; method.md is 1.5k today, the largest tool 4.8k
LOCKED_TOOLS = {"tools/symbolic.py"}           # copied over from scorer/ at run time
KEEP_TOOLS = {"tools/check_submission.py"}     # the prompt says it may be extended, not removed
DOCKER = shutil.which("docker") or os.path.expanduser("~/.docker/bin/docker")


# ---- the candidate folder ---------------------------------------------------------------------------
def _harness_files(folder):
    """Relative paths of the harness content: what harness_hash covers (no caches, no dotfiles)."""
    out = []
    for r, dirs, fs in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__" and not d.startswith("."))
        out += [os.path.relpath(os.path.join(r, f), folder).replace(os.sep, "/") for f in sorted(fs)
                if not f.startswith(".")]
    return sorted(out)


def _read(folder, rel):
    with open(os.path.join(folder, rel), encoding="utf-8") as f:
        return f.read()


def check_path(path, scope, for_delete=False):
    """The editable files for the scope. Returns an error message, or None if the path is allowed."""
    if not isinstance(path, str) or not path:
        return "path must be a non-empty string"
    if "\\" in path or path.startswith("/") or ".." in path.split("/"):
        return "path must be relative to the harness folder, with forward slashes and no '..'"
    if for_delete:
        if path in ("method.md", "system.md"):
            return f"{path} cannot be removed"
        if path in LOCKED_TOOLS:
            return "tools/symbolic.py is locked"
        if path in KEEP_TOOLS:
            return "tools/check_submission.py may be extended but not removed"
        return None if TOOL_NAME.match(path) else "only tools/<name>.py files can be removed"
    if path == "method.md":
        return None
    if path == "system.md":
        return None if scope == "all" else "system.md is read-only in this run"
    if path in LOCKED_TOOLS:
        return "tools/symbolic.py is locked: it is the scorer's parser, copied in at run time"
    if TOOL_NAME.match(path):
        return None
    return "you may write method.md" + (", system.md" if scope == "all" else "") + \
           " or tools/<name>.py (one level, a Python identifier, ending in .py)"


class Workspace:
    """A copy of the parent harness that the updater's tool calls edit."""

    def __init__(self, parent, folder, scope):
        self.parent, self.folder, self.scope = parent, folder, scope
        shutil.copytree(parent, folder, ignore=shutil.ignore_patterns("__pycache__", ".*"))
        for r, _, fs in os.walk(folder):                 # the parent may be read-only (harness_v0/harness is)
            os.chmod(r, 0o755)
            for f in fs:
                os.chmod(os.path.join(r, f), 0o644)
        self.refused = []

    def handle(self, name, inp):
        """Apply one tool call. Returns (message for the updater, is_error)."""
        if name == "write_file":
            path, content = inp.get("path"), inp.get("content")
            err = check_path(path, self.scope)
            if err is None and not isinstance(content, str):
                err = "content must be a string"
            if err is None and len(content) > MAX_FILE_CHARS:
                err = f"content is {len(content)} characters; the limit is {MAX_FILE_CHARS}"
            if err is None and not content.strip():
                err = "content is empty; use delete_file to remove a tool"
            if err:
                self.refused.append({"tool": name, "path": path, "reason": err})
                return f"refused: {err}", True
            p = os.path.join(self.folder, path)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            existed = os.path.exists(p)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            return f"{'replaced' if existed else 'created'} {path} ({len(content)} characters)", False
        if name == "delete_file":
            path = inp.get("path")
            err = check_path(path, self.scope, for_delete=True)
            if err is None and not os.path.exists(os.path.join(self.folder, path)):
                err = f"{path} does not exist"
            if err:
                self.refused.append({"tool": name, "path": path, "reason": err})
                return f"refused: {err}", True
            os.remove(os.path.join(self.folder, path))
            return f"removed {path}", False
        return f"unknown tool {name}", True

    def changes(self):
        """{path: (old text or None, new text or None)} for every file that differs from the parent."""
        a, b = set(_harness_files(self.parent)), set(_harness_files(self.folder))
        out = {}
        for rel in sorted(a | b):
            old = _read(self.parent, rel) if rel in a else None
            new = _read(self.folder, rel) if rel in b else None
            if old != new:
                out[rel] = (old, new)
        return out


def unified_diff(changes):
    parts = []
    for rel, (old, new) in changes.items():
        parts += difflib.unified_diff((old or "").splitlines(keepends=True), (new or "").splitlines(keepends=True),
                                      fromfile=f"a/{rel}" if old is not None else "/dev/null",
                                      tofile=f"b/{rel}" if new is not None else "/dev/null")
    return "".join(p if p.endswith("\n") else p + "\n" for p in parts)


# ---- checks before any solver run -------------------------------------------------------------------
def _imports(src):
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def static_checks(ws, changes):
    """(errors, warnings). An error makes the candidate invalid."""
    errors, warnings = [], []
    folder = ws.folder
    files = _harness_files(folder)
    for rel in files:
        if C.FORBIDDEN.search(rel):
            errors.append(f"the file name {rel} contains a name the solver must never see")
        text = _read(folder, rel)
        m = C.FORBIDDEN.search(text)
        if m:
            errors.append(f"{rel} contains a name the solver must never see: {m.group(0)!r}")
        if rel.endswith(".py"):
            try:
                compile(text, rel, "exec")
            except SyntaxError as e:
                errors.append(f"{rel} does not compile: line {e.lineno}: {e.msg}")
    if "method.md" not in files or not _read(folder, "method.md").strip():
        errors.append("method.md is missing or empty")
    if ws.scope == "tools" and "system.md" in changes:
        errors.append("system.md changed in the tools scope")
    # check_submission.py must keep parsing with symbolic.py, directly or through a tool it imports
    cs = "tools/check_submission.py"
    if cs not in files:
        errors.append(f"{cs} is missing")
    else:
        try:
            imp = _imports(_read(folder, cs))
            via = {n for n in imp if f"tools/{n}.py" in files and "symbolic" in _imports(_read(folder, f"tools/{n}.py"))}
            if "symbolic" not in imp and not via:
                errors.append(f"{cs} no longer imports symbolic, directly or through another tool")
        except SyntaxError:
            pass                                          # already reported above
    # warnings: things a reviewer should look at, that don't block solver runs
    method = _read(folder, "method.md") if "method.md" in files else ""
    for rel, (old, new) in changes.items():
        if old is None and new is not None and rel.startswith("tools/"):
            stem = rel[len("tools/"):]
            if stem not in method:
                warnings.append(f"new tool {rel} is not named in method.md, so the solver may never find it")
            try:
                if not ast.get_docstring(ast.parse(new)):
                    warnings.append(f"new tool {rel} has no docstring with its command line")
            except SyntaxError:
                pass
    if "method.md" in changes:
        old, new = changes["method.md"]
        seen = set(re.findall(r"\d+(?:\.\d+)?", (old or "") + open(C.PROMPT_MD).read()))
        added = "\n".join(l[1:] for l in difflib.unified_diff((old or "").splitlines(), (new or "").splitlines(),
                                                               lineterm="") if l.startswith("+") and not l.startswith("+++"))
        nums = sorted({n for n in re.findall(r"(?<![\w.])\d+\.\d+|(?<![\w.])\d{2,}(?![\w.])", added)} - seen)
        if nums:
            warnings.append("method.md gains numbers that are not in the parent or the task prompt; check none was "
                            "fitted from these recordings: " + ", ".join(nums[:12]))
    return errors, warnings


def _reference(run_paths):
    """The best scored submission among the runs, for the smoke run."""
    best = None
    for d in C._run_dirs(run_paths):
        pub, sub = os.path.join(d, "score", "public.json"), os.path.join(d, "submission.json")
        if os.path.exists(pub) and os.path.exists(sub):
            s = json.load(open(pub))["score"]
            if s is not None and (best is None or s < best[0]):
                best = (s, sub)
    return best[1] if best else None


def _val_files(noise):
    data = C.DATA_DIRS[noise]
    return sorted(v["file"] for v in json.load(open(os.path.join(data, "runs.json"))).values() if v["split"] == "val")


def run_checker(ws, noise, jobs, mode="docker", python=None, image="harness-v0-py"):
    """Run the candidate's tools/check_submission.py the way the solver would, once per job.
    jobs: (label, submission file or None for an empty submission, csv relative path or None).
    Returns [{label, cmd, exit, seconds, output}]."""
    data = C.DATA_DIRS[noise]
    work = os.path.join(HERE, f".work_{uuid.uuid4().hex[:8]}")   # under the repo, so Docker Desktop can mount it
    log = []
    try:
        os.makedirs(os.path.join(work, "val"))
        for f in ("runs.json", "dataset.json"):
            shutil.copy(os.path.join(data, f), os.path.join(work, f))
        for _, _, csv in jobs:
            if csv and not os.path.exists(os.path.join(work, csv)):
                shutil.copy(os.path.join(data, csv), os.path.join(work, csv))
        shutil.copytree(os.path.join(ws.folder, "tools"), os.path.join(work, "tools"))
        shutil.copy(C.SYMBOLIC, os.path.join(work, "tools", "symbolic.py"))
        for k, (label, sub, csv) in enumerate(jobs):
            name = f"sub{k}.json"
            if sub:
                shutil.copy(sub, os.path.join(work, name))
            else:
                with open(os.path.join(work, name), "w") as f:
                    f.write("{}")
            args = ["python", "tools/check_submission.py", name] + ([csv] if csv else [])
            if mode == "docker":
                cmd = [DOCKER, "run", "--rm", "--network", "none", "--memory", "2g", "-v", f"{work}:/work",
                       "-w", "/work", image, "timeout", "120"] + args
            else:
                cmd = [python or sys.executable] + args[1:]
            t0 = time.monotonic()
            try:
                r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=150)
                rc, out = r.returncode, (r.stdout + r.stderr)
            except subprocess.TimeoutExpired:
                rc, out = 124, "timed out"
            log.append({"label": label, "cmd": " ".join(["python", "tools/check_submission.py", "submission.json"]
                                                         + ([csv] if csv else [])),
                        "exit": rc, "seconds": round(time.monotonic() - t0, 1), "output": out[-4000:]})
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return log


def _can_run(mode):
    if mode == "off":
        return "smoke run skipped (--smoke off)"
    if mode == "docker" and not os.path.exists(DOCKER):
        return "smoke run skipped: docker not found"
    return None


def smoke_checks(ws, run_paths, noise, mode="docker", python=None, image="harness-v0-py"):
    """A valid submission must pass the candidate's checker (exit 0) on a validation file within 120 s,
    and an empty one must be rejected (nonzero exit). (errors, warnings, log)"""
    skip = _can_run(mode)
    if skip:
        return [], [skip], []
    ref, val = _reference(run_paths), _val_files(noise)
    if not ref or not val:
        return [], ["smoke run skipped: no scored submission or no validation file"], []
    log = run_checker(ws, noise, [("best submission", ref, val[0]), ("empty submission", None, None)],
                      mode, python, image)
    errors = []
    for entry, want_ok in zip(log, (True, False)):
        rc, out = entry["exit"], entry["output"]
        if rc == 124:
            errors.append(f"{entry['cmd']} did not finish in 120 s")
        elif want_ok and rc != 0:
            errors.append(f"the checker fails on a valid submission (exit {rc}): {out.strip()[-300:]}")
        elif not want_ok and rc == 0:
            errors.append("the checker accepts an empty submission")
    return errors, [], log


def _run_dir_of(run_paths, rid):
    for d in C._run_dirs(run_paths):
        if os.path.basename(d).endswith("_" + rid):
            return d
    return None


def self_test(ws, run_paths, ctx, mode="docker", python=None, image="harness-v0-py"):
    """The candidate's checker on the best and worst runs' submissions, as text for the updater, plus the log.
    None if it can't run."""
    if _can_run(mode):
        return None, []
    val = _val_files(ctx.stats["noise"])
    jobs = []
    for which in ("best", "worst"):
        rid = ctx.stats[which]
        d = _run_dir_of(run_paths, rid)
        if d and os.path.exists(os.path.join(d, "submission.json")) and val:
            jobs.append((f"{which} run {rid}", os.path.join(d, "submission.json"), val[0]))
    if not jobs:
        return None, []
    log = run_checker(ws, ctx.stats["noise"], jobs, mode, python, image)
    parts = ["Not submitted yet. Before you submit, here is your harness's checker on two real submissions from "
             "the runs above, run the way the solver will run it. Check that what your tools tell the solver is "
             "right for both: the best run's model is the best this harness has produced."]
    for e in log:
        parts.append(f"{e['label']}: {e['cmd']} (exit {e['exit']}, {e['seconds']} s)\n{e['output'].strip()}")
    parts.append("Then call finish again: as it is to submit this harness, or after more edits.")
    return "\n\n".join(parts), log


# ---- the updater call -------------------------------------------------------------------------------
def _cost(R, model, u):
    """The runner's own pricing (run_harness.py cost()), for the updater's usage."""
    price = {m[0]: m[1:] for m in R["MODELS"]}
    p_in, p_out, cache_read = price[model]
    read, write = getattr(u, "cache_read_input_tokens", 0) or 0, getattr(u, "cache_creation_input_tokens", 0) or 0
    mult = 5 if model == "claude-haiku-5-5" and u.input_tokens + read + write > 100_000 else 1
    p_in, p_out = p_in * mult, p_out * mult
    return (u.input_tokens * p_in + read * p_in * cache_read + write * p_in * R["CACHE_WRITE"]
            + u.output_tokens * p_out) / 1e6


def _plain(b):
    b = b.model_dump() if hasattr(b, "model_dump") else (dict(b) if isinstance(b, dict) else dict(vars(b)))
    if b.get("type") == "image":
        b = {"type": "image", "source": "system_diagram.png"}
    return b


MANIFEST_KEYS = ("evidence", "root_cause", "change", "predicted_effect", "at_risk")


def propose(run_paths, harness_dir, out_dir, scope="tools", history=None, model="claude-haiku-5-5",
            effort="high", max_turns=20, max_usd=2.0, smoke="docker", smoke_python=None, client=None,
            last=20, budget=80000, do_self_test=True):
    R = C._runner()
    if model not in {m[0] for m in R["MODELS"]}:
        raise ValueError(f"unknown model {model}; run_harness.py prices {[m[0] for m in R['MODELS']]}")
    if os.path.exists(out_dir):
        raise FileExistsError(f"{out_dir} already exists")
    harness_dir = os.path.abspath(harness_dir)
    ctx = C.build(run_paths, harness_dir, scope=scope, history=history, last=last, budget=budget)
    os.makedirs(out_dir)
    with open(os.path.join(out_dir, "context.md"), "w") as f:
        f.write(ctx.markdown + "\n")
    json.dump(ctx.stats, open(os.path.join(out_dir, "context_stats.json"), "w"), indent=1)
    ws = Workspace(harness_dir, os.path.join(out_dir, "harness"), scope)

    if client is None:
        import anthropic
        client = anthropic.Anthropic(max_retries=6)     # rides out short overloads in an unattended loop
    messages = [{"role": "user", "content": ctx.content}]
    spent, turns, manifest, status, nudged = 0.0, 0, None, None, False
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    per_turn = []           # the first turn's input is the exact size of the context, for CHARS_PER_TOKEN
    self_tested, self_test_log = False, []
    t0 = time.monotonic()
    try:
        while turns < max_turns:
            with client.messages.stream(model=model, max_tokens=R["MAX_TOKENS"], system=ctx.system,
                                        tools=ctx.tools, output_config={"effort": effort},
                                        cache_control={"type": "ephemeral"}, messages=messages) as s:
                r = s.get_final_message()
            turns += 1
            spent += _cost(R, model, r.usage)
            for k in usage:
                usage[k] += getattr(r.usage, k, 0) or 0
            per_turn.append({k: getattr(r.usage, k, 0) or 0 for k in usage})
            messages.append({"role": "assistant", "content": r.content})
            print(f"updater turn {turns}: ${spent:.4f} spent, stop reason {r.stop_reason}")
            uses = [b for b in r.content if b.type == "tool_use"]
            if not uses:
                if r.stop_reason == "max_tokens":
                    note = "Your reply hit the output limit before any tool call. Write one file per write_file call."
                elif nudged:
                    status = "no_finish"
                    break
                else:
                    note = "Make your change with write_file or delete_file, then call finish."
                    nudged = True
                messages.append({"role": "user", "content": [{"type": "text", "text": note}]})
                continue
            results, finish = [], None
            for b in uses:                               # edits first, in order; finish last
                if b.name == "finish":
                    finish = b
                    continue
                msg, err = ws.handle(b.name, b.input if isinstance(b.input, dict) else {})
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": msg,
                                **({"is_error": True} if err else {})})
            if finish is not None:
                inp = finish.input if isinstance(finish.input, dict) else {}
                missing = [k for k in MANIFEST_KEYS if not str(inp.get(k, "")).strip()]
                if not ws.changes():
                    results.append({"type": "tool_result", "tool_use_id": finish.id, "is_error": True,
                                    "content": "refused: the harness is unchanged; write at least one file first"})
                elif missing:
                    results.append({"type": "tool_result", "tool_use_id": finish.id, "is_error": True,
                                    "content": f"refused: finish needs non-empty {', '.join(missing)}"})
                elif do_self_test and not self_tested:
                    self_tested = True
                    text, st_log = self_test(ws, run_paths, ctx, smoke, smoke_python, R["IMAGE"])
                    self_test_log += st_log
                    if text is None:                     # nothing to test with: take the submission
                        manifest = {k: str(inp[k]).strip() for k in MANIFEST_KEYS}
                        results.append({"type": "tool_result", "tool_use_id": finish.id, "content": "submitted"})
                        messages.append({"role": "user", "content": results})
                        break
                    results.append({"type": "tool_result", "tool_use_id": finish.id, "content": text})
                else:
                    manifest = {k: str(inp[k]).strip() for k in MANIFEST_KEYS}
                    results.append({"type": "tool_result", "tool_use_id": finish.id, "content": "submitted"})
                    messages.append({"role": "user", "content": results})
                    break
            messages.append({"role": "user", "content": results})
            if spent > max_usd:
                status = "over_budget"
                break
        else:
            status = "no_finish"
    finally:
        json.dump({"model": model, "effort": effort, "spent_usd": round(spent, 4),
                   "messages": [{"role": m["role"], "content": [_plain(b) for b in m["content"]]} for m in messages]},
                  open(os.path.join(out_dir, "transcript.json"), "w"), indent=1, default=str)

    changes = ws.changes()
    with open(os.path.join(out_dir, "diff.patch"), "w") as f:
        f.write(unified_diff(changes))
    errors, warnings, smoke_log = [], [], []
    if manifest is not None:
        if not changes:
            status = "no_change"
        else:
            errors, warnings = static_checks(ws, changes)
            if not errors:
                e2, w2, smoke_log = smoke_checks(ws, run_paths, ctx.stats["noise"], smoke, smoke_python, R["IMAGE"])
                errors, warnings = errors + e2, warnings + w2
            status = "invalid" if errors else "ok"
    proposal = {
        "status": status, "candidate": os.path.basename(os.path.normpath(out_dir)),
        "parent": harness_dir, "parent_sha": ctx.stats["harness_sha"],
        "candidate_sha": R["harness_hash"](ws.folder), "scope": scope, "manifest": manifest,
        "files_changed": [{"path": p, "kind": "added" if o is None else "removed" if n is None else "modified"}
                          for p, (o, n) in changes.items()],
        "errors": errors, "warnings": warnings, "refused": ws.refused, "smoke": smoke_log, "self_test": self_test_log,
        "updater": {"model": model, "effort": effort, "turns": turns, "seconds": round(time.monotonic() - t0, 1),
                    "spent_usd": round(spent, 4), "usage": usage, "usage_per_turn": per_turn,
                    "context_tokens": (sum(per_turn[0][k] for k in ("input_tokens", "cache_read_input_tokens",
                                                                     "cache_creation_input_tokens")) if per_turn else None)},
        "context": {k: ctx.stats[k] for k in ("runs_in_table", "best", "worst", "tokens_est", "reductions",
                                               "history_records")},
    }
    json.dump(proposal, open(os.path.join(out_dir, "proposal.json"), "w"), indent=1)
    return proposal


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", nargs="+", required=True, help="the current harness's run or batch folders")
    ap.add_argument("--harness", required=True, help="the current harness folder")
    ap.add_argument("--out", required=True, help="new folder for the candidate, e.g. candidates/h001")
    ap.add_argument("--scope", choices=["tools", "all"], default="tools")
    ap.add_argument("--history", default=None, help="history.jsonl from the loop")
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--max-turns", type=int, default=20)
    ap.add_argument("--max-usd", type=float, default=2.0, help="stop the updater past this cost")
    ap.add_argument("--smoke", choices=["docker", "local", "off"], default="docker",
                    help="run the candidate's checker in the solver's Docker image (default), with --smoke-python, or not")
    ap.add_argument("--no-self-test", action="store_true",
                    help="skip showing the updater its checker on the best and worst submissions before it submits")
    ap.add_argument("--smoke-python", default=None, help="interpreter for --smoke local (needs numpy, pandas, scipy, sympy)")
    a = ap.parse_args()
    p = propose(a.runs, a.harness, a.out, a.scope, C.read_history(a.history), a.model, a.effort, a.max_turns,
                a.max_usd, a.smoke, a.smoke_python, do_self_test=not a.no_self_test)
    print(f"\n{p['candidate']}: {p['status']}  ({p['updater']['turns']} turns, ${p['updater']['spent_usd']:.4f}, "
          f"{p['updater']['seconds']} s)")
    for f in p["files_changed"]:
        print(f"  {f['kind']:8s} {f['path']}")
    if p["manifest"]:
        print("  change:", p["manifest"]["change"])
    for e in p["errors"]:
        print("  error:", e)
    for w in p["warnings"]:
        print("  warning:", w)
    for r in p["refused"]:
        print(f"  refused {r['tool']} {r['path']}: {r['reason']}")
    if p["updater"]["context_tokens"]:
        print(f"  context: {p['updater']['context_tokens']} tokens on the first turn "
              f"(estimated {p['context']['tokens_est']['total']})")
    print(f"  candidate hash {p['candidate_sha']} (parent {p['parent_sha']}); details in {os.path.join(a.out, 'proposal.json')}")
    return 0 if p["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
