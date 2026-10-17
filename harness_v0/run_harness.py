"""Harness v0: one agent run on grid A's recordings, then a closed-loop score on the selection grid.

    python run_harness.py 1 1                  # Haiku 5.5, low effort
    python run_harness.py 1 1 --harness DIR --out DIR --workers 4 --no-score
    python run_harness.py 1 1 --noise clean    # noise-free grid A data, and the prompt says so

What the agent gets (assembled here, never edited by the agent):
  prompt.md                    task, data, scoring, submission format (locked in every scope;
                               its {{NOISE}} line is filled from --noise)
  <harness>/system.md          facts about the device and grid (editable only in the edit-anything scope)
  <harness>/method.md          how to work (editable in both scopes)
  <harness>/tools/             helper code copied into the sandbox (editable in both scopes)
  scorer/symbolic.py           the scorer's parser, copied to the sandbox's tools/ (locked)
  grid A sandbox_data          train/, val/, runs.json, dataset.json, system_diagram.png (locked;
                               --noise clean uses sandbox_data_clean instead)

Each run writes runs/<tag>/: transcript.json, final.md, submission.json, meta.json and, unless
--no-score, score/public.json and score/private.json from scorer/score.py with config_min.json.
Uses the shared Fall DRA/.venv (anthropic and ANDES), and Docker image harness-v0-py:
    docker build -t harness-v0-py .
"""
import argparse
import atexit
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

import anthropic

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                                   # Harness_testing
DATA_DIRS = {"noisy": os.path.join(ROOT, "test_cases", "grid_A", "sandbox_data"),         # PMU-grade noise
             "clean": os.path.join(ROOT, "test_cases", "grid_A", "sandbox_data_clean")}   # make_clean_sandbox.py
# fills {{NOISE}} in prompt.md; the noisy sentence is the one every earlier run was given
NOISE_SENTENCE = {"noisy": "The measured channels carry PMU-grade noise.",
                  "clean": "The measured channels are noise-free."}
SCORER = os.path.join(ROOT, "scorer")
DOCKER = shutil.which("docker") or os.path.expanduser("~/.docker/bin/docker")
IMAGE = "harness-v0-py"

MODELS = [  # (id, $/MTok in, $/MTok out, cache-read multiplier on input price)
    ("claude-haiku-5-5", 0.10, 0.50, 0.10),   # rates x5 when the prompt is over 100K tokens
    ("claude-sonnet-5-5", 2.0, 10.0, 0.10),
    ("claude-opus-5-5", 4.0, 20.0, 0.05),
]
EFFORTS = ["low", "medium", "high", "xhigh", "max"]
CACHE_WRITE = 1.25                       # 5-min cache write multiplier, same on all three
CAP = 20.0
MAX_TOKENS = 32000
TOOL_OUT_CHARS = 20000                   # truncate tool output so one step can't blow up the context

ap = argparse.ArgumentParser()
ap.add_argument("model", type=int, choices=[1, 2, 3], help="1 Haiku, 2 Sonnet, 3 Opus")
ap.add_argument("effort", type=int, choices=[1, 2, 3, 4, 5], help="1 low ... 5 max")
ap.add_argument("--harness", default=os.path.join(HERE, "harness"), help="folder with system.md, method.md, tools/")
ap.add_argument("--out", default=os.path.join(HERE, "runs"), help="parent folder for this run's results")
ap.add_argument("--config", default=os.path.join(SCORER, "config_min.json"))
ap.add_argument("--workers", type=int, default=None, help="ANDES worker processes for scoring")
ap.add_argument("--noise", choices=["noisy", "clean"], default="noisy",
                help="grid A data with PMU-grade noise (default) or noise-free; also sets the prompt's noise sentence")
ap.add_argument("--no-score", action="store_true")
args = ap.parse_args()
DATA = DATA_DIRS[args.noise]
if not os.path.isdir(DATA):
    sys.exit(f"{DATA} is missing; build it with test_cases/make_clean_sandbox.py")
# the folder has to match what the prompt will tell the agent
if any(json.load(open(os.path.join(DATA, "dataset.json")))["measurement_noise_std"].values()) != (args.noise == "noisy"):
    sys.exit(f"noise levels in {DATA}/dataset.json don't match --noise {args.noise}")


MODEL, PRICE_IN, PRICE_OUT, CACHE_READ = MODELS[args.model - 1]
EFFORT = EFFORTS[args.effort - 1]
HARNESS = os.path.abspath(args.harness)
TAG = f"{time.strftime('%Y%m%d_%H%M%S')}_{MODEL.split('-')[1]}_{EFFORT}_{uuid.uuid4().hex[:4]}"
RUN_DIR = os.path.join(os.path.abspath(args.out), TAG)
os.makedirs(RUN_DIR)
print(f"Using {MODEL} at effort {EFFORT}, harness {HARNESS}\nData: {args.noise} ({DATA})\nResults in {RUN_DIR}")


def harness_hash(folder):
    """sha256 over the editable surface, so every run records exactly which harness produced it."""
    h = hashlib.sha256()
    for r, _, fs in sorted(os.walk(folder)):
        for f in sorted(fs):
            if "__pycache__" in r:
                continue
            p = os.path.join(r, f)
            h.update(os.path.relpath(p, folder).encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()[:16]


# Each run gets its own scratch copy of the data and tools. Files the agent writes persist across its
# tool calls within this run, and the folder is deleted when the run ends, so runs (including ones
# running at the same time) cannot see each other's files. Kept under HERE (in /Users) so Docker
# Desktop can mount it.
SANDBOX = os.path.join(HERE, f".work_{uuid.uuid4().hex[:8]}")
shutil.copytree(DATA, SANDBOX)
shutil.copytree(os.path.join(HARNESS, "tools"), os.path.join(SANDBOX, "tools"),
                ignore=shutil.ignore_patterns("__pycache__"))
# locked: the scorer's own parser, so the checker always applies the scorer's rules
shutil.copy(os.path.join(SCORER, "symbolic.py"), os.path.join(SANDBOX, "tools", "symbolic.py"))
atexit.register(shutil.rmtree, SANDBOX, ignore_errors=True)

PROMPT = open(os.path.join(HERE, "prompt.md")).read()
assert PROMPT.count("{{NOISE}}") == 1, "prompt.md needs exactly one {{NOISE}} placeholder"
PROMPT = PROMPT.replace("{{NOISE}}", NOISE_SENTENCE[args.noise])
SYSTEM = open(os.path.join(HARNESS, "system.md")).read()
METHOD = open(os.path.join(HARNESS, "method.md")).read()
TOOLS = [{
    "name": "run_python",
    "description": "Run a Python script in the working directory (train/, val/, runs.json, dataset.json, "
                   "tools/). Returns stdout and stderr, truncated.",
    "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
}]


def run_python(code):
    try:
        # fresh container per call: no network, no host files except the sandbox, no API key.
        # `timeout` runs inside so the container dies too; the outer timeout is a backstop.
        r = subprocess.run([DOCKER, "run", "--rm", "--network", "none", "--memory", "2g",
                            "-v", f"{SANDBOX}:/work", "-w", "/work", IMAGE,
                            "timeout", "120", "python", "-c", code],
                           capture_output=True, text=True, timeout=150)
        if r.returncode == 124:
            return "ERROR: timed out after 120 s"
        return (r.stdout + r.stderr)[-TOOL_OUT_CHARS:]
    except subprocess.TimeoutExpired:
        return "ERROR: timed out after 120 s"


def rates(prompt_tokens):
    # Haiku 5.5 bills the whole request at $0.50/$2.50 once the prompt passes 100K tokens
    m = 5 if MODEL == "claude-haiku-5-5" and prompt_tokens > 100_000 else 1
    return PRICE_IN * m, PRICE_OUT * m


def cost(u):
    read, write = u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0
    p_in, p_out = rates(u.input_tokens + read + write)
    return (u.input_tokens * p_in + read * p_in * CACHE_READ
            + write * p_in * CACHE_WRITE + u.output_tokens * p_out) / 1e6


def worst_case_next(u):
    # whole context billed at the cache-write rate, plus a full tool result, plus max output
    ctx = (u.input_tokens + (u.cache_read_input_tokens or 0)
           + (u.cache_creation_input_tokens or 0) + u.output_tokens + TOOL_OUT_CHARS)
    p_in, p_out = rates(ctx)
    return (ctx * p_in * CACHE_WRITE + MAX_TOKENS * p_out) / 1e6


client = anthropic.Anthropic()
png = base64.b64encode(open(os.path.join(DATA, "system_diagram.png"), "rb").read()).decode()
content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png}},
           {"type": "text", "text": PROMPT},
           {"type": "text", "text": SYSTEM},
           {"type": "text", "text": METHOD}]
messages = [{"role": "user", "content": content}]
state = {"spent": 0.0, "steps": 0, "tool_calls": 0, "budget_stop": False, "t0": time.monotonic()}
last = None


def save_transcript():
    # full record of every tool call and result, so a run can be audited (and shown to the updater).
    def plain(b):
        b = b.model_dump() if hasattr(b, "model_dump") else dict(b)
        if b.get("type") == "image":
            b = {"type": "image", "source": "system_diagram.png"}
        return b
    msgs = [{"role": m["role"], "content": [plain(b) for b in m["content"]]} for m in messages]
    with open(os.path.join(RUN_DIR, "transcript.json"), "w") as f:
        json.dump({"model": MODEL, "effort": EFFORT, "harness": HARNESS, "spent_usd": round(state["spent"], 4),
                   "messages": msgs}, f, indent=1, default=str)


atexit.register(save_transcript)   # registered after the sandbox cleanup, so it runs first; also on a crash


def step(tool_choice):
    global last
    # streaming: the SDK refuses non-streaming requests this large.
    # cache_control: caches the conversation so far, so each step re-reads it at the cache rate.
    with client.messages.stream(model=MODEL, max_tokens=MAX_TOKENS, tools=TOOLS,
                                tool_choice=tool_choice, output_config={"effort": EFFORT},
                                cache_control={"type": "ephemeral"},
                                messages=messages) as s:
        r = s.get_final_message()
    state["spent"] += cost(r.usage)
    state["steps"] += 1
    last = r.usage
    messages.append({"role": "assistant", "content": r.content})
    print(f"step {state['steps']}: ${state['spent']:.4f} spent")
    return r


def extract_submission(text):
    """The last json code block in the final message; failing that, submission.json in the sandbox."""
    for block in reversed(re.findall(r"```json\s*\n(.*?)```", text, re.S)):
        try:
            return json.loads(block), "final_message"
        except json.JSONDecodeError:
            continue
    p = os.path.join(SANDBOX, "submission.json")
    if os.path.exists(p):
        try:
            return json.load(open(p)), "sandbox_file"
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    return None, "none"


r = step({"type": "auto"})
while r.stop_reason == "tool_use":
    results = [{"type": "tool_result", "tool_use_id": b.id, "content": run_python(b.input["code"])}
               for b in r.content if b.type == "tool_use"]
    state["tool_calls"] += len(results)
    if state["spent"] + 2 * worst_case_next(last) > CAP:
        # keep one step's worth of budget for the final answer, and forbid more tool calls
        results.append({"type": "text", "text": "Budget reached. No more code. Submit your best model now, "
                                                "ending with the json code block."})
        messages.append({"role": "user", "content": results})
        state["budget_stop"] = True
        r = step({"type": "none"})
        break
    messages.append({"role": "user", "content": results})
    r = step({"type": "auto"})

final = "\n".join(b.text for b in r.content if b.type == "text")
open(os.path.join(RUN_DIR, "final.md"), "w").write(final)
sub, source = extract_submission(final)
sub_path = os.path.join(RUN_DIR, "submission.json")
with open(sub_path, "w") as f:
    # no usable submission: an empty object, which the scorer rejects as invalid (score 2)
    json.dump(sub if sub is not None else {}, f, indent=1)
print(final)

meta = {"tag": TAG, "model": MODEL, "effort": EFFORT, "harness": HARNESS, "harness_sha": harness_hash(HARNESS),
        "spent_usd": round(state["spent"], 4), "steps": state["steps"], "tool_calls": state["tool_calls"],
        "budget_stop": state["budget_stop"], "agent_seconds": round(time.monotonic() - state["t0"], 1),
        "submission_source": source, "data": DATA, "noise": args.noise}

if not args.no_score:
    cmd = [sys.executable, os.path.join(SCORER, "score.py"), sub_path, "--config", args.config,
           "--out", os.path.join(RUN_DIR, "score")]
    if args.workers:
        cmd += ["--workers", str(args.workers)]
    print("scoring closed loop ...")
    with open(os.path.join(RUN_DIR, "score.log"), "w") as log:
        rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode
    pub = os.path.join(RUN_DIR, "score", "public.json")
    if rc == 0 and os.path.exists(pub):
        p = json.load(open(pub))
        priv = json.load(open(os.path.join(RUN_DIR, "score", "private.json")))
        meta["score_selection"] = p["score"]
        meta["role_scores"] = priv["role_scores"]
        meta["components"] = {g: {k: v[k] for k in ("score", "td", "fr", "par")} for g, v in priv["grids"].items()}
        print(f"selection score {p['score']}  (all roles: {priv['role_scores']})")
    else:
        meta["score_error"] = f"scorer exit code {rc}, see score.log"
        print(meta["score_error"])

with open(os.path.join(RUN_DIR, "meta.json"), "w") as f:
    json.dump(meta, f, indent=1)
