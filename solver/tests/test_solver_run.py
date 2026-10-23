"""Checks for solver_run.py with a scripted fake API client, a fake sandbox and a fake scorer. No API call, no
Docker, no ANDES.

    python solver/tests/test_solver_run.py
"""
import json
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace as NS

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPOSITORY_ROOT)
from solver import solver_run as S  # noqa: E402
from solver.python_sandbox import SandboxResult, TIMED_OUT_MESSAGE  # noqa: E402

work = tempfile.mkdtemp(prefix="solver_run_test_")
S.API_RETRY_WAITS_S = (0, 0, 0)                 # no real waiting between retries
passed = 0


def check(condition, description):
    global passed
    if not condition:
        raise AssertionError(description)
    passed += 1
    print("ok:", description)


class FakeClient:
    """Replays scripted responses (or raises scripted exceptions); records every request."""

    def __init__(self, script):
        self.script, self.requests, self.messages = list(script), [], self

    def stream(self, **request):
        self.requests.append({**request, "messages": list(request["messages"])})
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return _Stream(item)


class _Stream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.response


class FakeSandbox:
    def __init__(self, folder, broken=False):
        self.folder, self.broken = folder, broken
        os.makedirs(folder, exist_ok=True)
        self.calls = []

    def run_python_code(self, code, max_output_chars=None):
        self.calls.append(code)
        if self.broken:
            raise OSError("docker daemon not running")
        if code == "SLOW":
            return SandboxResult(TIMED_OUT_MESSAGE, True, 124)
        return SandboxResult(f"ran {code}", False, 0)

    def remove(self):
        shutil.rmtree(self.folder, ignore_errors=True)


def create_fake_sandbox(folder, data_dir, tools_dir, parser_file):
    return FakeSandbox(folder)


USAGE = NS(input_tokens=20000, output_tokens=2000, cache_read_input_tokens=0, cache_creation_input_tokens=0)
SUBMISSION = {"params": {}, "states": {}, "outputs": {"P": "P0", "Q": "Q0"}}
_counter = [0]


def tool_call(code):
    _counter[0] += 1
    return NS(content=[NS(type="text", text="Let me look."), NS(type="tool_use", id=f"toolu_{_counter[0]}",
                                                                   name="run_python", input={"code": code})],
              stop_reason="tool_use", usage=USAGE)


def final(text=None):
    text = text if text is not None else "The model.\n```json\n" + json.dumps(SUBMISSION) + "\n```\n"
    return NS(content=[NS(type="text", text=text)], stop_reason="end_turn", usage=USAGE)


FAKE_SCORER = os.path.join(work, "fake_scorer.py")
with open(FAKE_SCORER, "w") as file:
    file.write('''import json, os, sys, time
out = sys.argv[sys.argv.index("--out") + 1]
mode = os.environ.get("FAKE_SCORER_MODE", "ok")
if mode == "crash":
    sys.exit(1)
if mode == "hang":
    time.sleep(60)
os.makedirs(out, exist_ok=True)
json.dump({"score": 0.5, "grids": {"grid_B": {"score": 0.5, "td": 0.4, "td_runs": {}, "failures": []}},
           "submission_error": None}, open(os.path.join(out, "public.json"), "w"))
json.dump({"role_scores": {"selection": 0.5}, "grids": {"grid_B": {"score": 0.5, "td": 0.4, "fr": 0.6, "par": 0.7}}},
          open(os.path.join(out, "private.json"), "w"))
''')


def settings(**changes):
    values = dict(model_id="claude-haiku-5-5", effort="low", harness_dir=os.path.join(REPOSITORY_ROOT, "harness_v0", "harness"),
                  noise="clean", scorer_config=os.path.join(REPOSITORY_ROOT, "scorer", "config_min.json"),
                  labels={"block": "iter001_screen", "arm": "candidate"})
    values.update(changes)
    return S.SolverSettings(**values)


def start(script, scorer_mode="ok", create_sandbox=create_fake_sandbox, **changes):
    os.environ["FAKE_SCORER_MODE"] = scorer_mode
    client = FakeClient(script)
    run = S.SolverRun.start(settings(**changes), os.path.join(work, "runs"), client=client,
                            create_sandbox=create_sandbox, scorer_script=FAKE_SCORER)
    return run, client


def meta_of(run):
    return json.load(open(os.path.join(run.run_dir, "meta.json")))


# 1. a run that goes through: two tool calls, a final message, a score
run, client = start([tool_call("print(1)"), tool_call("SLOW"), final()])
status = run.execute()
meta = meta_of(run)
check(status == "finished" and meta["status"] == "finished", "a normal run finishes")
check(meta["steps"] == 3 and meta["tool_calls"] == 2 and meta["tool_timeouts"] == 1 and meta["spent_usd"] > 0,
      "steps, tool calls, timeouts and spend are counted")
check(meta["score_selection"] == 0.5 and meta["components"]["grid_B"]["fr"] == 0.6 and meta["submission_source"] == "final_message",
      "the scores and the submission's source are recorded")
check(json.load(open(os.path.join(run.run_dir, "submission.json"))) == SUBMISSION, "submission.json holds the json block")
check(not os.path.exists(os.path.join(run.run_dir, "checkpoint.json")) and not os.path.exists(run.sandbox.folder),
      "a finished run removes its checkpoint and its sandbox")
transcript = json.load(open(os.path.join(run.run_dir, "transcript.json")))
check(transcript["messages"][0]["content"][0] == {"type": "image", "source": "system_diagram.png"},
      "the transcript replaces the diagram with its file name")
check(meta["labels"] == {"block": "iter001_screen", "arm": "candidate"} and "git_commit" in meta and meta["harness_sha"],
      "labels, the git commit and the harness fingerprint are in meta.json")
first_request = client.requests[0]
check(first_request["tool_choice"] == {"type": "auto"} and first_request["output_config"] == {"effort": "low"}
      and first_request["tools"] == S.SOLVER_TOOLS and len(first_request["messages"][0]["content"]) == 4,
      "the first request carries the diagram, the prompt, system.md and method.md, and the solver's tool")
check(client.requests[1]["messages"][2]["content"][0]["content"] == "ran print(1)",
      "tool results go back to the agent")

# 2. an API problem that passes is retried in place
run, client = start([S.TransientApiError("overloaded"), final()])
check(run.execute() == "finished" and meta_of(run)["api_retries"] == 1, "a passing API problem is retried, then the run finishes")

# 3. an API problem that does not pass crashes the run; --resume carries on from the checkpoint
run, client = start([tool_call("print(1)")] + [S.TransientApiError("connection lost")] * 4)
try:
    run.execute()
    crashed = False
except S.TransientApiError:
    crashed = True
meta = meta_of(run)
checkpoint = json.load(open(os.path.join(run.run_dir, "checkpoint.json")))
check(crashed and meta["status"] == "crashed" and "connection lost" in meta["error"] and meta["spent_usd"] > 0
      and meta["failures"] == 1, "after the retries the run is marked crashed, with its error, the spend so far and one failure")
check(len(checkpoint["messages"]) == 3 and os.path.isdir(run.sandbox.folder),
      "the checkpoint holds every message so far, and the sandbox is kept")
spent_before = meta["spent_usd"]
client = FakeClient([final()])
resumed = S.SolverRun.load_for_resume(run.run_dir, client=client, sandbox=FakeSandbox(run.sandbox.folder),
                                      scorer_script=FAKE_SCORER)
check(resumed.execute() == "finished", "the resumed run finishes")
meta = meta_of(resumed)
check(meta["resumes"] == 1 and meta["steps"] == 2 and meta["spent_usd"] > spent_before and meta["error"] is None,
      "the resumed run keeps counting from where it stopped")
check(len(client.requests[0]["messages"]) == 3 and client.requests[0]["messages"][1]["role"] == "assistant",
      "the resumed run sends the saved conversation unchanged")

# 4. a crash while a tool runs: on resume the tool call is run again
run, _ = start([tool_call("print(1)")], create_sandbox=lambda folder, *args: FakeSandbox(folder, broken=True))
try:
    run.execute()
except OSError:
    pass
check(meta_of(run)["status"] == "crashed", "a sandbox failure crashes the run")
sandbox = FakeSandbox(run.sandbox.folder)
resumed = S.SolverRun.load_for_resume(run.run_dir, client=FakeClient([final()]), sandbox=sandbox, scorer_script=FAKE_SCORER)
check(resumed.execute() == "finished" and sandbox.calls == ["print(1)"], "the resumed run re-runs the interrupted tool call")

# 5. a stop signal (the RSI loop stopping its runs) is recorded as stopped
run, _ = start([SystemExit(143)])
try:
    run.execute()
    stopped = False
except SystemExit:
    stopped = True
check(stopped and meta_of(run)["status"] == "stopped" and "143" in meta_of(run)["error"] and meta_of(run)["failures"] == 0,
      "a stop is recorded and passed on, and is not counted as a failure")

# 6. the budget: once the next steps could pass it, one last answer without tools
budget = S.API_BUDGET_USD
S.API_BUDGET_USD = 0.001
run, client = start([tool_call("print(1)"), final()])
status = run.execute()
S.API_BUDGET_USD = budget
check(status == "finished" and meta_of(run)["budget_stop"] and client.requests[-1]["tool_choice"] == {"type": "none"}
      and client.requests[-1]["messages"][-1]["content"][-1]["text"] == S.BUDGET_REACHED_MESSAGE,
      "the budget stop sends the budget message and forbids more tool calls")

# 7. a scorer that never finishes: the run still gets a failure score of 2
limit = S.SCORER_TIME_LIMIT_S
S.SCORER_TIME_LIMIT_S = 1
run, _ = start([final()], scorer_mode="hang")
status = run.execute()
S.SCORER_TIME_LIMIT_S = limit
public = json.load(open(os.path.join(run.run_dir, "score", "public.json")))
check(status == "finished" and meta_of(run)["score_selection"] == 2.0
      and public["grids"]["grid_B"]["failures"][0]["failure"] == "scoring_timeout",
      "a scorer timeout scores 2, with the failure named")

# 8. a scorer that fails by itself: scoring_failed, and --resume only re-runs the scorer
run, _ = start([final()], scorer_mode="crash")
check(run.execute() == "scoring_failed" and "exit code 1" in meta_of(run)["score_error"] and meta_of(run)["failures"] == 1,
      "a scorer crash is scoring_failed, and counts as a failure")
os.environ["FAKE_SCORER_MODE"] = "ok"
resumed = S.SolverRun.load_for_resume(run.run_dir, client=FakeClient([]), sandbox=FakeSandbox(run.sandbox.folder),
                                      scorer_script=FAKE_SCORER)
check(resumed.execute() == "finished" and meta_of(resumed)["score_selection"] == 0.5 and "score_error" not in meta_of(resumed),
      "resuming a scoring failure re-runs only the scorer")

# 9. where the submission comes from
run, _ = start([final("No json here.")])
run.execute()
check(meta_of(run)["submission_source"] == "none" and json.load(open(os.path.join(run.run_dir, "submission.json"))) == {},
      "no json block and no sandbox file: an empty submission")


def create_sandbox_with_file(folder, *args):
    sandbox = FakeSandbox(folder)
    json.dump(SUBMISSION, open(os.path.join(folder, "submission.json"), "w"))
    return sandbox


os.environ["FAKE_SCORER_MODE"] = "ok"
run = S.SolverRun.start(settings(), os.path.join(work, "runs"), client=FakeClient([final("Done.")]),
                        create_sandbox=create_sandbox_with_file, scorer_script=FAKE_SCORER)
run.execute()
check(meta_of(run)["submission_source"] == "sandbox_file", "without a json block, the sandbox's submission.json is used")

# 10. a conversation too long for the model ends the agent's work; the sandbox's submission is scored
class TooLong(Exception):
    status_code = 400


run = S.SolverRun.start(settings(), os.path.join(work, "runs"), create_sandbox=create_sandbox_with_file,
                        client=FakeClient([tool_call("print(1)"), TooLong("Error code: 400 - prompt is too long: "
                                                                          "210000 tokens > 200000 maximum")]),
                        scorer_script=FAKE_SCORER)
status = run.execute()
meta = meta_of(run)
check(status == "finished" and meta["stop_reason"] == "context_window_full" and meta["submission_source"] == "sandbox_file"
      and meta["failures"] == 0 and open(os.path.join(run.run_dir, "final.md")).read() == "",
      "a conversation past the context window ends the run normally, scored from the sandbox's submission.json")
check(not S.is_context_window_error(TooLong("Error code: 400 - tools: field required"))
      and S.is_context_window_error(S.ContextWindowFull()), "other bad requests are not taken for a full context window")

# 11. Docker failing is a crash, not tool output for the agent
from solver.python_sandbox import DockerPythonSandbox, SandboxUnavailable  # noqa: E402
fake_docker = os.path.join(work, "fake_docker")
with open(fake_docker, "w") as file:
    file.write("#!/bin/sh\necho 'docker: Cannot connect to the Docker daemon. Is the docker daemon running?' >&2\nexit 125\n")
os.chmod(fake_docker, 0o755)
os.makedirs(os.path.join(work, "docker_down"))
try:
    DockerPythonSandbox(os.path.join(work, "docker_down"), docker_executable=fake_docker).run_python_code("print(1)")
    raised = ""
except SandboxUnavailable as error:
    raised = str(error)
check("Cannot connect to the Docker daemon" in raised, "a docker run that fails by itself raises instead of answering the agent")

# 12. which API errors are retried
check(S.is_transient_api_error(S.TransientApiError()) and not S.is_transient_api_error(ValueError("bad request")),
      "only passing API problems are retried")

shutil.rmtree(work, ignore_errors=True)
print(f"\nall {passed} checks passed")
