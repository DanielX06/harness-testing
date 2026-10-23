"""One solver run: an agent identifies the device's terminal model from grid A's recordings, then the scorer
scores the model it submits, closed loop, on held-out grids.

    python solver/solver_run.py haiku low                       # or 1 1, as before
    python solver/solver_run.py haiku low --harness DIR --noise clean --config scorer/config_rsi.json --workers 2
    python solver/solver_run.py --resume runs/<batch>/<run>     # carry on a run that crashed or was stopped

What the agent gets (assembled here, never edited by the agent):
  solver/task_prompt.md        the task, the data, how it is scored, the submission format (locked in every RSI
                               scope; its {{NOISE}} line is filled from --noise)
  <harness>/system.md          facts about the device and the grid (editable only in the RSI edit-anything scope)
  <harness>/method.md          how to work (editable in both scopes)
  <harness>/tools/             helper code copied into the sandbox (editable in both scopes)
  scorer/submission_parser.py  the scorer's parser, copied in as tools/submission_parser.py (locked)
  grid A's recordings          train/, val/, runs.json, dataset.json, system_diagram.png (locked; --noise clean
                               uses the noise-free copy)

The run folder (<out>/<run tag>/) holds
  meta.json        written when the run starts and after every step: status, cost so far, counts, and at the
                   end the scores. Every budget counts the spend recorded here, so a run that dies still counts.
  checkpoint.json  the conversation so far, rewritten after every message; removed when the run finishes
  sandbox/         the agent's working folder; removed when the run finishes, kept for --resume otherwise
  transcript.json  every message (the diagram replaced by its file name); final.md, the last message
  submission.json  the last json block of the final message, or the sandbox's submission.json; {} if neither
                   parses, which scores 2
  score/, score.log  the scorer's public.json and private.json, and its output

Status values in meta.json:
  running          the run is going, or it died without warning (power cut, kill -9)
  scoring          the agent has finished and the scorer is running
  finished         done; score/ holds the scores
  crashed          stopped by an error it could not ride out ("error" says which); --resume carries on
  stopped          stopped by a signal (Ctrl-C, or the RSI loop stopping its runs); --resume carries on
  scoring_failed   the scorer itself failed (not because of the submission); --resume runs the scorer again
"failures" counts the sessions that ended crashed or scoring_failed (a stop is not a failure).

API problems that usually pass (a lost connection, an overloaded or failing server, a rate limit) are retried in
place for about 35 minutes before the run counts as crashed. A conversation that has outgrown the model's context
window ends the agent's work like a final message without a json block would: the submission is taken from the
sandbox's submission.json, or the run scores 2. That is the run's own outcome, not a crash.
"""
import argparse
import base64
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the repository root
from common import api_pricing  # noqa: E402
from common.harness_files import harness_fingerprint  # noqa: E402
from common.project_paths import (DEFAULT_RUNS_DIR, MIN_SCORER_CONFIG, SCORER_SCRIPT, SOLVER_DATA_DIRS,  # noqa: E402
                                  STARTING_HARNESS_DIR, SUBMISSION_PARSER_FILE, TASK_PROMPT_FILE)
from common.run_provenance import docker_image_id, git_commit  # noqa: E402
from solver.python_sandbox import DOCKER_EXECUTABLE, SANDBOX_IMAGE, DockerPythonSandbox  # noqa: E402

API_BUDGET_USD = 20.0                   # per run; the agent is told to submit once the next steps could pass it
MAX_OUTPUT_TOKENS = 32000
TOOL_OUTPUT_CHARS = 20000               # tool output is cut to its last this-many characters
NOISE_SENTENCES = {"noisy": "The measured channels carry PMU-grade noise.",   # the sentence every earlier run got
                   "clean": "The measured channels are noise-free."}
SOLVER_TOOLS = [{
    "name": "run_python",
    "description": "Run a Python script in the working directory (train/, val/, runs.json, dataset.json, "
                   "tools/). Returns stdout and stderr, truncated.",
    "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
}]
BUDGET_REACHED_MESSAGE = "Budget reached. No more code. Submit your best model now, ending with the json code block."
# waits before each new attempt at a request that failed for a reason that usually passes (about 35 minutes in all)
API_RETRY_WAITS_S = (10, 20, 40, 80, 160, 300, 300, 300, 300, 300, 300)
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504, 529}
RETRYABLE_ERROR_TYPES = {"overloaded_error", "api_error", "rate_limit_error"}
# how the API words a request whose conversation no longer fits the model's context window (a 400 error)
CONTEXT_WINDOW_ERROR_TEXT = re.compile(r"prompt is too long|context window|context length|too many tokens", re.I)
# a backstop around the whole scorer; every ANDES simulation inside it already has its own limit
SCORER_TIME_LIMIT_S = 3 * 3600
STATUSES = ("running", "scoring", "finished", "crashed", "stopped", "scoring_failed")


class TransientApiError(Exception):
    """Stands in for an API problem that usually passes (used by tests)."""


class ContextWindowFull(Exception):
    """Stands in for the API's refusal of a conversation too long for the model (used by tests)."""


class ScoringFailed(Exception):
    """The scorer itself failed (exit code, not a failure score), so there is nothing to record yet."""


def is_transient_api_error(error):
    """True for API problems that usually pass: a lost connection or a timeout, an overloaded or failing
    server, a rate limit. Anything else (a bad request, a refused key) is not retried."""
    if isinstance(error, TransientApiError):
        return True
    if type(error).__module__.split(".")[0] in ("httpx", "httpx2", "httpcore", "httpcore2"):
        return True                         # a connection that broke while the answer was streaming in
    try:
        import anthropic
    except ImportError:
        return False
    if isinstance(error, anthropic.APIConnectionError):     # includes APITimeoutError
        return True
    if isinstance(error, anthropic.APIStatusError):
        if getattr(error, "status_code", None) in RETRYABLE_STATUS_CODES:
            return True
        body = getattr(error, "body", None)
        error_type = body.get("error", {}).get("type") if isinstance(body, dict) else None
        return error_type in RETRYABLE_ERROR_TYPES
    return False


def is_context_window_error(error):
    """True when the API refused the request because the conversation no longer fits the model's context window."""
    if isinstance(error, ContextWindowFull):
        return True
    return getattr(error, "status_code", None) == 400 and bool(CONTEXT_WINDOW_ERROR_TEXT.search(str(error)))


def content_block_as_dict(block):
    """A response content block as the dict the API client sends back for it (fields the API did not set are
    left out), so a conversation saved to disk can be sent again exactly as it would have been."""
    if isinstance(block, dict):
        return block
    if hasattr(block, "to_dict"):
        return block.to_dict(mode="json")
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json", by_alias=True, exclude_unset=True)
    return dict(vars(block))


def write_json_atomically(path, content):
    """Write to a temporary file and rename it over path, so a crash mid-write never leaves a torn file."""
    temporary = f"{path}.tmp"
    with open(temporary, "w") as file:
        json.dump(content, file, indent=1, default=str)
    os.replace(temporary, path)


def read_json(path):
    with open(path) as file:
        return json.load(file)


def task_prompt(noise):
    """The locked task prompt with its {{NOISE}} line filled in."""
    template = TASK_PROMPT_FILE.read_text()
    if template.count("{{NOISE}}") != 1:
        raise ValueError(f"{TASK_PROMPT_FILE} needs exactly one {{{{NOISE}}}} placeholder")
    return template.replace("{{NOISE}}", NOISE_SENTENCES[noise])


def data_dir_for(noise):
    """Grid A's recordings for this noise setting, after checking dataset.json agrees with what the prompt will say."""
    data_dir = str(SOLVER_DATA_DIRS[noise])
    if not os.path.isdir(data_dir):
        sys.exit(f"{data_dir} is missing; build it with test_cases/make_noise_free_sandbox.py")
    noise_levels = read_json(os.path.join(data_dir, "dataset.json"))["measurement_noise_std"].values()
    if any(noise_levels) != (noise == "noisy"):
        sys.exit(f"noise levels in {data_dir}/dataset.json don't match --noise {noise}")
    return data_dir


def extract_submission(final_text, sandbox_dir):
    """(submission, where it came from): the last json code block of the final message that parses as JSON;
    failing that, submission.json in the sandbox; failing that, (None, "none")."""
    for block in reversed(re.findall(r"```json\s*\n(.*?)```", final_text, re.S)):
        try:
            return json.loads(block), "final_message"
        except json.JSONDecodeError:
            continue
    path = os.path.join(sandbox_dir, "submission.json")
    if os.path.exists(path):
        try:
            return read_json(path), "sandbox_file"
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    return None, "none"


@dataclass
class SolverSettings:
    model_id: str
    effort: str
    harness_dir: str
    noise: str = "noisy"
    scorer_config: str | None = str(MIN_SCORER_CONFIG)   # None: don't score
    scoring_workers: int | None = None
    labels: dict = field(default_factory=dict)          # free-form tags, such as the RSI loop's block and arm


@dataclass
class RunProgress:
    """Everything a resumed run needs besides the messages; saved in the checkpoint after every message."""
    phase: str = "agent"                # "agent" until the final message, then "scoring"
    spent_usd: float = 0.0
    steps: int = 0
    tool_calls: int = 0
    tool_timeouts: int = 0
    budget_stop: bool = False
    api_retries: int = 0
    agent_seconds: float = 0.0          # summed over every session that worked on the run
    last_usage: dict | None = None      # the last response's usage: the basis of the next step's worst-case cost
    stop_reason: str | None = None      # the last response's stop reason


class SolverRun:
    """One agent run in its run folder, from the first request to the scores. Every message is checkpointed, so
    a run that crashed or was stopped carries on from where it stopped (load_for_resume)."""

    def __init__(self, run_dir, settings, meta, messages, progress, client=None, sandbox=None,
                 scorer_script=SCORER_SCRIPT):
        self.run_dir, self.settings, self.meta = run_dir, settings, meta
        self.messages, self.progress = messages, progress
        self.price = api_pricing.price_for(settings.model_id)
        self.sandbox = sandbox or DockerPythonSandbox(os.path.join(run_dir, "sandbox"))
        self.scorer_script = str(scorer_script)
        self._client = client
        self._session_started = time.monotonic()
        self._scorer_process = None

    # ---- starting and resuming -----------------------------------------------------------------------
    @classmethod
    def start(cls, settings, runs_dir, client=None, create_sandbox=DockerPythonSandbox.create,
              scorer_script=SCORER_SCRIPT):
        """Make the run folder and its sandbox, and write meta.json and the first checkpoint."""
        for required in ("system.md", "method.md", "tools"):
            if not os.path.exists(os.path.join(settings.harness_dir, required)):
                sys.exit(f"{settings.harness_dir} has no {required}; a harness needs system.md, method.md and tools/")
        data_dir = data_dir_for(settings.noise)
        tag = f"{time.strftime('%Y%m%d_%H%M%S')}_{settings.model_id.split('-')[1]}_{settings.effort}_{uuid.uuid4().hex[:4]}"
        run_dir = os.path.join(os.path.abspath(runs_dir), tag)
        os.makedirs(run_dir)
        sandbox = create_sandbox(os.path.join(run_dir, "sandbox"), data_dir, os.path.join(settings.harness_dir, "tools"),
                                 str(SUBMISSION_PARSER_FILE))
        with open(os.path.join(data_dir, "system_diagram.png"), "rb") as file:
            diagram = base64.b64encode(file.read()).decode()
        harness_text = {}
        for name in ("system.md", "method.md"):
            with open(os.path.join(settings.harness_dir, name)) as file:
                harness_text[name] = file.read()
        first_message = {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": diagram}},
            {"type": "text", "text": task_prompt(settings.noise)},
            {"type": "text", "text": harness_text["system.md"]},
            {"type": "text", "text": harness_text["method.md"]}]}
        meta = {"tag": tag, "model": settings.model_id, "effort": settings.effort, "harness": settings.harness_dir,
                "harness_sha": harness_fingerprint(settings.harness_dir), "spent_usd": 0.0, "steps": 0, "tool_calls": 0,
                "tool_timeouts": 0, "budget_stop": False, "agent_seconds": 0.0, "submission_source": None,
                "data": data_dir, "noise": settings.noise, "config": settings.scorer_config,
                "status": "running", "error": None, "stop_reason": None, "api_retries": 0, "resumes": 0, "failures": 0,
                "labels": settings.labels, "git_commit": git_commit(),
                "docker_image": docker_image_id(DOCKER_EXECUTABLE, SANDBOX_IMAGE),
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        run = cls(run_dir, settings, meta, [first_message], RunProgress(), client, sandbox, scorer_script)
        run._save_checkpoint()
        print(f"Using {settings.model_id} at effort {settings.effort}, harness {settings.harness_dir}\n"
              f"Data: {settings.noise} ({data_dir})\nResults in {run_dir}", flush=True)
        return run

    @classmethod
    def load_for_resume(cls, run_dir, client=None, sandbox=None, scorer_script=SCORER_SCRIPT):
        """The run as its last checkpoint left it, ready for execute()."""
        run_dir = os.path.abspath(run_dir)
        meta = read_json(os.path.join(run_dir, "meta.json"))
        checkpoint_path = os.path.join(run_dir, "checkpoint.json")
        if not os.path.exists(checkpoint_path):
            sys.exit(f"{run_dir} has no checkpoint.json (status {meta.get('status')}); nothing to resume")
        checkpoint = read_json(checkpoint_path)
        meta["resumes"] = meta.get("resumes", 0) + 1
        meta["error"] = None
        run = cls(run_dir, SolverSettings(**checkpoint["settings"]), meta, checkpoint["messages"],
                  RunProgress(**checkpoint["progress"]), client, sandbox, scorer_script)
        print(f"Resuming {run_dir} (phase {run.progress.phase}, {run.progress.steps} steps, "
              f"${run.progress.spent_usd:.4f} spent)", flush=True)
        return run

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    # ---- the run -------------------------------------------------------------------------------------
    def execute(self):
        """Run (or carry on) to the end. Returns the final status; re-raises a crash or a stop after recording it."""
        try:
            self._set_status("running" if self.progress.phase == "agent" else "scoring")
            if self.progress.phase == "agent":
                self._run_agent()
                self._finish_agent()
            self._set_status("scoring")
            self._score()
            self._set_status("finished")
            self._remove_resume_files()
        except ScoringFailed:
            self.meta["failures"] = self.meta.get("failures", 0) + 1
            self._set_status("scoring_failed")
        except (KeyboardInterrupt, SystemExit) as stop:
            self.meta["error"] = "stopped (Ctrl-C)" if isinstance(stop, KeyboardInterrupt) else f"stopped (exit {stop.code})"
            self._set_status("stopped")
            raise
        except Exception as error:
            self.meta["error"] = f"{type(error).__name__}: {error}"[:2000]
            self.meta["failures"] = self.meta.get("failures", 0) + 1
            self._set_status("crashed")
            raise
        finally:
            self._stop_scorer()
            self._save_transcript()
            self._write_meta()
        return self.meta["status"]

    def _run_agent(self):
        """Request, run the tool calls, repeat, until a message comes back without tool calls."""
        while True:
            last_message = self.messages[-1]
            if last_message["role"] == "user":
                # after the budget message the agent may not call tools: one last answer, then stop
                try:
                    self._request_next_message({"type": "none"} if self.progress.budget_stop else {"type": "auto"})
                except Exception as error:
                    if not is_context_window_error(error):
                        raise
                    self.progress.stop_reason = "context_window_full"     # the agent's work ends here
                    return
                continue
            if self.progress.stop_reason != "tool_use" or self.progress.budget_stop:
                return
            tool_uses = [block for block in last_message["content"] if block.get("type") == "tool_use"]
            if not tool_uses:
                return
            results = [{"type": "tool_result", "tool_use_id": block["id"], "content": self._run_tool(block)}
                       for block in tool_uses]
            self.progress.tool_calls += len(results)
            worst_case_next = self.price.worst_case_next_request_cost(self.progress.last_usage, MAX_OUTPUT_TOKENS,
                                                                      TOOL_OUTPUT_CHARS)
            if self.progress.spent_usd + 2 * worst_case_next > API_BUDGET_USD:
                # keep one step's worth of budget for the final answer, and forbid more tool calls
                results.append({"type": "text", "text": BUDGET_REACHED_MESSAGE})
                self.progress.budget_stop = True
            self._append_message({"role": "user", "content": results})

    def _run_tool(self, tool_use):
        result = self.sandbox.run_python_code((tool_use.get("input") or {}).get("code", ""), TOOL_OUTPUT_CHARS)
        if result.timed_out:
            self.progress.tool_timeouts += 1
        return result.output

    def _request_next_message(self, tool_choice):
        response = self._call_api_with_retries(tool_choice)
        self.progress.spent_usd += self.price.request_cost(response.usage)
        self.progress.steps += 1
        self.progress.last_usage = api_pricing.usage_as_dict(response.usage)
        self.progress.stop_reason = response.stop_reason
        self._append_message({"role": "assistant", "content": [content_block_as_dict(block) for block in response.content]})
        print(f"step {self.progress.steps}: ${self.progress.spent_usd:.4f} spent", flush=True)

    def _call_api_with_retries(self, tool_choice):
        for attempt, wait_s in enumerate((0,) + tuple(API_RETRY_WAITS_S)):
            if wait_s:
                print(f"API problem ({self.meta.get('last_api_error')}); retrying in {wait_s} s", flush=True)
                time.sleep(wait_s)
            try:
                # streaming: the client refuses non-streaming requests this large.
                # cache_control: caches the conversation so far, so each step re-reads it at the cache rate.
                with self.client.messages.stream(model=self.settings.model_id, max_tokens=MAX_OUTPUT_TOKENS,
                                                 tools=SOLVER_TOOLS, tool_choice=tool_choice,
                                                 output_config={"effort": self.settings.effort},
                                                 cache_control={"type": "ephemeral"}, messages=self.messages) as stream:
                    return stream.get_final_message()
            except Exception as error:
                if not is_transient_api_error(error) or attempt == len(API_RETRY_WAITS_S):
                    raise
                self.progress.api_retries += 1
                self.meta["last_api_error"] = f"{type(error).__name__}: {error}"[:300]
                self._write_meta()

    def _finish_agent(self):
        """Save the final message and the submission taken from it; the agent's part is done."""
        last_message = self.messages[-1]
        final_text = "\n".join(block.get("text", "") for block in last_message["content"]
                               if block.get("type") == "text") if last_message["role"] == "assistant" else ""
        with open(os.path.join(self.run_dir, "final.md"), "w") as file:
            file.write(final_text)
        submission, source = extract_submission(final_text, self.sandbox.folder)
        with open(os.path.join(self.run_dir, "submission.json"), "w") as file:
            json.dump(submission if submission is not None else {}, file, indent=1)   # {} scores 2
        self.meta["submission_source"] = source
        print(final_text, flush=True)
        self.progress.agent_seconds = self._agent_seconds()
        self.progress.phase = "scoring"
        self._save_checkpoint()

    def _score(self):
        """Run the scorer on submission.json and record its scores in meta.json."""
        if not self.settings.scorer_config:
            return
        score_dir = os.path.join(self.run_dir, "score")
        command = [sys.executable, self.scorer_script, os.path.join(self.run_dir, "submission.json"),
                   "--config", self.settings.scorer_config, "--out", score_dir]
        if self.settings.scoring_workers:
            command += ["--workers", str(self.settings.scoring_workers)]
        print("scoring closed loop ...", flush=True)
        with open(os.path.join(self.run_dir, "score.log"), "w") as log:
            # its own process group, so a timeout can stop the scorer and its ANDES workers together
            self._scorer_process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                return_code = self._scorer_process.wait(timeout=SCORER_TIME_LIMIT_S)
            except subprocess.TimeoutExpired:
                self._stop_scorer()
                from scorer.score_submission import failure_report, write_score_files
                write_score_files(failure_report(self.settings.scorer_config, os.path.join(self.run_dir, "submission.json"),
                                                 "scoring_timeout", f"the scorer did not finish in {SCORER_TIME_LIMIT_S} s"),
                                  score_dir)
                return_code = 0
            self._scorer_process = None
        public_path = os.path.join(score_dir, "public.json")
        if return_code != 0 or not os.path.exists(public_path):
            self.meta["score_error"] = f"scorer exit code {return_code}, see score.log"
            raise ScoringFailed(self.meta["score_error"])
        public, private = read_json(public_path), read_json(os.path.join(score_dir, "private.json"))
        self.meta.pop("score_error", None)
        self.meta["score_selection"] = public["score"]
        self.meta["role_scores"] = private["role_scores"]
        self.meta["components"] = {grid: {key: values[key] for key in ("score", "td", "fr", "par")}
                                   for grid, values in private["grids"].items()}
        print(f"selection score {public['score']}  (all roles: {private['role_scores']})", flush=True)

    def _stop_scorer(self):
        process, self._scorer_process = self._scorer_process, None
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            process.wait()

    # ---- what is written to disk ----------------------------------------------------------------------
    def _append_message(self, message):
        self.messages.append(message)
        self._save_checkpoint()
        self._write_meta()

    def _agent_seconds(self):
        if self.progress.phase != "agent":
            return self.progress.agent_seconds
        return round(self.progress.agent_seconds + time.monotonic() - self._session_started, 1)

    def _save_checkpoint(self):
        write_json_atomically(os.path.join(self.run_dir, "checkpoint.json"),
                              {"settings": asdict(self.settings),
                               "progress": {**asdict(self.progress), "agent_seconds": self._agent_seconds()},
                               "messages": self.messages})

    def _set_status(self, status):
        self.meta["status"] = status
        self._write_meta()

    def _write_meta(self):
        progress = self.progress
        self.meta.update(spent_usd=round(progress.spent_usd, 4), steps=progress.steps, tool_calls=progress.tool_calls,
                         tool_timeouts=progress.tool_timeouts, budget_stop=progress.budget_stop,
                         agent_seconds=self._agent_seconds(), stop_reason=progress.stop_reason,
                         api_retries=progress.api_retries, pid=os.getpid(), host=socket.gethostname(),
                         updated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        write_json_atomically(os.path.join(self.run_dir, "meta.json"), self.meta)

    def _save_transcript(self):
        """Every message, for auditing and for the RSI updater; the diagram is replaced by its file name."""
        def without_image_data(block):
            return {"type": "image", "source": "system_diagram.png"} if block.get("type") == "image" else block
        messages = [{"role": message["role"], "content": [without_image_data(block) for block in message["content"]]}
                    for message in self.messages]
        write_json_atomically(os.path.join(self.run_dir, "transcript.json"),
                              {"model": self.settings.model_id, "effort": self.settings.effort,
                               "harness": self.settings.harness_dir, "spent_usd": round(self.progress.spent_usd, 4),
                               "messages": messages})

    def _remove_resume_files(self):
        """A finished run needs neither its checkpoint nor its sandbox."""
        if os.path.exists(os.path.join(self.run_dir, "checkpoint.json")):
            os.remove(os.path.join(self.run_dir, "checkpoint.json"))
        self.sandbox.remove()


# ---- command line --------------------------------------------------------------------------------------
def _stop_on_signal(signal_number, frame):
    raise SystemExit(128 + signal_number)       # so execute() records "stopped" and saves everything


def parse_labels(pairs):
    labels = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator or not key:
            raise SystemExit(f"--label needs KEY=VALUE, got {pair!r}")
        labels[key] = value
    return labels


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description="One solver run, then its closed-loop score.")
    parser.add_argument("model", nargs="?", help="1-3, or haiku, sonnet, opus")
    parser.add_argument("effort", nargs="?", help="1-5, or low, medium, high, xhigh, max")
    parser.add_argument("--harness", default=str(STARTING_HARNESS_DIR), help="folder with system.md, method.md, tools/")
    parser.add_argument("--out", default=str(DEFAULT_RUNS_DIR), help="parent folder for this run's folder")
    parser.add_argument("--config", default=str(MIN_SCORER_CONFIG),
                        help="scorer config; scorer/config_rsi.json adds the hidden monitor grid M")
    parser.add_argument("--no-score", action="store_true")
    parser.add_argument("--workers", type=int, default=None, help="ANDES simulations at once when scoring")
    parser.add_argument("--noise", choices=["noisy", "clean"], default="noisy",
                        help="grid A data with PMU-grade noise (default) or noise-free; also sets the prompt's noise sentence")
    parser.add_argument("--label", action="append", default=[], metavar="KEY=VALUE", help="a tag stored in meta.json")
    parser.add_argument("--resume", metavar="RUN_DIR", help="carry on a run that crashed or was stopped")
    options = parser.parse_args(argv)
    if options.resume is None and (options.model is None or options.effort is None):
        parser.error("give the model and the effort, or --resume RUN_DIR")
    return options


def main(argv=None):
    options = parse_arguments(argv)
    for signal_number in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signal_number, _stop_on_signal)
    if options.resume:
        meta = read_json(os.path.join(options.resume, "meta.json"))
        if meta.get("status") == "finished":
            print(f"{options.resume} already finished")
            return 0
        run = SolverRun.load_for_resume(options.resume)
    else:
        settings = SolverSettings(model_id=api_pricing.resolve_model_id(options.model),
                                  effort=api_pricing.resolve_effort(options.effort),
                                  harness_dir=os.path.abspath(options.harness), noise=options.noise,
                                  scorer_config=None if options.no_score else os.path.abspath(options.config),
                                  scoring_workers=options.workers, labels=parse_labels(options.label))
        run = SolverRun.start(settings, options.out)
    return 0 if run.execute() == "finished" else 1


if __name__ == "__main__":
    sys.exit(main())
