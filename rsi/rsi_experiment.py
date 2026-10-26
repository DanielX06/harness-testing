"""The RSI loop: an updater proposes a change to the solver's harness, the candidate and the current harness are
run side by side in fresh pairs of solver runs, and the candidate replaces the current harness only if it wins
twice, on two separate blocks of pairs.

    python rsi/rsi_experiment.py --iters 30                                   # Haiku at low effort everywhere
    python rsi/rsi_experiment.py --iters 2 --baseline-runs 4 --pairs 4 --early-stop-pairs 2 --confirm-pairs 4
                                                                               # a smoke test: 12 to 36 runs
    python rsi/rsi_experiment.py --resume rsi/experiments/20261022_090000     # carry on after a crash or a stop

On a Mac, start it as `caffeinate -i python rsi/rsi_experiment.py ...` so the machine does not sleep mid-loop.

Before the first iteration, --baseline-runs runs of the starting harness give the first updater something to read.
Each iteration:
  1. Propose (harness_proposal.py). The updater reads the newest runs of the current harness and the history of
     earlier attempts, and edits a copy. A copy that fails a check is never run.
  2. Test block. Pairs of fresh runs, one of the candidate and one of the current harness in each pair, started
     together (with --parallel 2 the two runs of a pair run at the same time). After --early-stop-pairs pairs, a
     candidate whose mean composite is not below the current harness's is rejected early. Otherwise, after
     --pairs pairs, it passes if its mean is lower and a one-sided permutation test on this block's runs gives
     p <= --alpha.
  3. Confirmation block. A candidate that passed gets --confirm-pairs new pairs, run and judged the same way (the
     early stop included) on their own. Passing both makes it the current harness; failing this one reverts it.
     The two blocks share no runs, so a candidate no better than the current harness passes both with
     probability about alpha squared (1% at the default 0.10).
  4. Stop after --iters iterations, --patience attempts in a row that were not kept, or once --max-usd has been
     spent (checked before each iteration). At about $0.017 a Haiku-low run, an early rejection costs about $0.30,
     a full rejection about $0.70 and a kept candidate about $1.40, plus the updater's few cents.

Comparing the candidate with the current harness's runs from the same block, rather than with older runs, keeps
the comparison fair when the solver's behavior drifts over the days a loop takes (API changes, load), and every
block gives the current harness new runs, so each updater reads fresh evidence.

Failed runs. A run that ends with a failure score (an invalid submission, a model that fails in simulation) is a
result and counts. A run that stops for a reason outside the harness (an API outage longer than solver_run.py
rides out, Docker, the scorer itself) is resumed from its checkpoint until it has failed more than --max-resumes
times, then replaced by a new run for the same pair. After --max-failures-in-a-row failed sessions with no run
finishing in between, the loop stops (exit code 3) so you can fix the cause and --resume.

Resuming. Every run, proposal and decision is on disk, and --resume carries on from there: finished iterations
are read from history.jsonl, a saved proposal is reused, scored runs are kept, crashed or stopped runs are resumed,
and runs still going from a loop that was killed are waited for. Decisions use fixed pairs (the first
--early-stop-pairs, then all --pairs), so a resumed loop decides exactly what an uninterrupted one would.
--resume takes only --iters, --patience, --max-usd, --parallel, --workers, --updater-max-usd and --max-resumes; the
rest comes from config.json, which records each resume. loop.lock stops two loops sharing a folder.

Spend is always recomputed from the files: every solver run's meta.json (crashed and replaced runs included) and
every proposal's updater cost (interrupted proposals included).

Everything goes in --out (default rsi/experiments/<date>_<time>):
    candidates/h000/harness     the starting harness; candidates/hNNN/ each proposal (harness_proposal.py's output)
    runs/<block>/<run tag>/     solver runs. Blocks are h000_baseline, hNNN_test and hNNN_confirm; each run's
                                meta.json labels give its block, pair, arm (candidate or current) and harness
    runs/<block>/logs/          the solver's output for each pair and arm
    history.jsonl               what later updaters are shown about each attempt (selection grid only; for a
                                candidate that reached its confirmation block, that block's numbers)
    blocks.jsonl                every block's numbers, for you
    monitor.jsonl, summary.md   for you, never for the updater: grid M (the hidden monitor) and grid A's held-out
                                runs next to grid B for both arms of every block, and the M - B gap
    cycles.jsonl                for you, never for the updater: earlier harnesses each candidate returns to
    config.json, state.json, loop.log, loop.lock (while running)
    archive.tar.xz, archive_manifest.json
                                once the loop ends on its own: every run's transcript, checkpoint and leftover
                                sandbox, packed (experiment_archive.py), and the scorer's failure trajectories and
                                DEBUG tails deleted; --resume unpacks them first
"""
import argparse
import hashlib
import itertools
import json
import math
import os
import random
import signal
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field, fields

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the repository root
from common.api_pricing import resolve_effort, resolve_model_id  # noqa: E402
from common.harness_files import copy_harness, harness_fingerprint  # noqa: E402
from common.hidden_names import remove_hidden_device_names  # noqa: E402
from common.project_paths import (DEFAULT_EXPERIMENTS_DIR, RSI_SCORER_CONFIG, SOLVER_RUN_SCRIPT,  # noqa: E402
                                  STARTING_HARNESS_DIR)
from common.run_provenance import git_commit  # noqa: E402
from rsi.experiment_archive import ArchiveError, archive, restore  # noqa: E402
from rsi.harness_proposal import propose_candidate  # noqa: E402
from rsi.updater_context import hidden_score_names_pattern, read_history  # noqa: E402
from solver.python_sandbox import SandboxUnavailable  # noqa: E402
from solver.solver_run import write_json_atomically  # noqa: E402

RESUMABLE_SETTINGS = ("iters", "patience", "max_usd", "parallel", "workers", "updater_max_usd", "max_resumes")
WHY_NOT_RUN = {"no_change": "the updater changed nothing", "no_finish": "the updater did not call finish",
               "over_budget": "the updater ran past its budget"}
INFRASTRUCTURE_EXIT_CODE = 3
ARMS = ("candidate", "current")


# ---- settings ------------------------------------------------------------------------------------------------
@dataclass
class ExperimentSettings:
    """Everything that defines an experiment, saved in config.json. Only RESUMABLE_SETTINGS change on --resume."""
    iters: int                              # iterations (updater proposals)
    out: str                                # the experiment folder
    pairs: int = 20                         # pairs of runs in a test block
    early_stop_pairs: int = 8               # after this many pairs, a candidate not ahead is rejected (0: never)
    confirm_pairs: int = 20                 # pairs in a confirmation block (0: no confirmation)
    alpha: float = 0.10                     # one-sided permutation-test level, for each block
    baseline_runs: int = 20                 # runs of the starting harness, for the first updater to read
    parallel: int = 2                       # solver runs at a time
    solver_model: str = "claude-haiku-5-5"
    solver_effort: str = "low"
    noise: str = "clean"
    start: str = str(STARTING_HARNESS_DIR)  # the starting harness
    scope: str = "tools"                    # what the updater may edit: "tools" (method.md, tools/) or "all"
    scorer_config: str = str(RSI_SCORER_CONFIG)
    workers: int | None = None              # ANDES simulations at once in each run's scoring
    patience: int = 20                      # stop after this many attempts in a row that were not kept
    max_usd: float = 20.0                   # no new iteration starts once this much has been spent
    updater_model: str = "claude-haiku-5-5"
    updater_effort: str = "low"
    updater_max_usd: float = 2.0            # one proposal stops past this cost
    newest_runs: int = 20                   # how many of the current harness's runs the updater reads
    smoke: str = "docker"                   # how harness_proposal.py runs the candidate's checker
    smoke_python: str | None = None
    self_test: bool = True
    max_resumes: int = 2                    # a run that has failed more often than this is replaced
    max_failures_in_a_row: int = 6          # this many failed sessions with no run finishing: stop the loop

    def problems(self):
        """Settings that cannot work."""
        problems = []
        if self.pairs < 2:
            problems.append("--pairs must be at least 2")
        if self.confirm_pairs < 0 or self.confirm_pairs == 1:
            problems.append("--confirm-pairs must be 0 (no confirmation) or at least 2")
        if self.early_stop_pairs < 0 or self.early_stop_pairs == 1:
            problems.append("--early-stop-pairs must be 0 (never) or at least 2")
        for name in ("baseline_runs", "parallel", "iters"):
            if getattr(self, name) < 1:
                problems.append(f"--{name.replace('_', '-')} must be at least 1")
        if not 0 < self.alpha < 1:
            problems.append("--alpha must be between 0 and 1")
        return problems

    def warnings(self):
        """Blocks too small for any candidate to pass at --alpha."""
        warnings = []
        for name, count in (("--pairs", self.pairs), ("--confirm-pairs", self.confirm_pairs)):
            if count and 1 / math.comb(2 * count, count) > self.alpha:
                warnings.append(f"with {name} {count}, the smallest p a block can give is {1 / math.comb(2 * count, count):.3f}, "
                                f"above --alpha {self.alpha}, so no candidate can pass. Use more pairs.")
        return warnings


# ---- files -----------------------------------------------------------------------------------------------------
def read_json_or_none(path):
    """JSON from path, or None if it is missing or torn (a crash mid-write)."""
    try:
        with open(path) as file:
            return json.load(file)
    except (OSError, ValueError):
        return None


def read_jsonl(path, keep_through_iteration=None):
    """The records of a .jsonl file, skipping a torn line. With keep_through_iteration, records of later iterations
    are dropped and the file is rewritten, so an iteration that is redone after a crash is not recorded twice."""
    records = []
    if os.path.exists(path):
        with open(path) as file:
            for line in file:
                try:
                    records.append(json.loads(line))
                except ValueError:
                    pass
    if keep_through_iteration is not None:
        records = [record for record in records if record.get("iteration", 0) <= keep_through_iteration]
        with open(path, "w") as file:
            file.writelines(json.dumps(record) + "\n" for record in records)
    return records


def append_jsonl(path, record):
    with open(path, "a") as file:
        file.write(json.dumps(record) + "\n")


class LoopLog:
    """Lines to the screen and to loop.log, each with the time."""

    def __init__(self, path):
        self.path = path

    def __call__(self, *parts):
        line = time.strftime("%H:%M:%S ") + " ".join(str(part) for part in parts)
        print(line, flush=True)
        with open(self.path, "a") as file:
            file.write(line + "\n")


@dataclass
class SolverRunRecord:
    """What the loop needs from one run folder."""
    run_dir: str
    tag: str
    labels: dict
    status: str
    failures: int
    spent_usd: float
    pid: int | None = None
    error: str | None = None
    composite: float | None = None      # the selection score (score/public.json), once the run has finished
    td_runs: dict = field(default_factory=dict)
    role_scores: dict = field(default_factory=dict)     # private scores: monitor.jsonl and summary.md only

    @property
    def slot(self):
        """(pair, arm) within its block, or None for a run without the loop's labels."""
        try:
            return int(self.labels["pair"]), self.labels["arm"]
        except (KeyError, ValueError):
            return None

    @property
    def is_scored(self):
        return self.status == "finished" and self.composite is not None


def read_run_record(run_dir):
    """The run's record, or None if its meta.json is missing or torn."""
    meta = read_json_or_none(os.path.join(run_dir, "meta.json"))
    if meta is None:
        return None
    record = SolverRunRecord(run_dir=run_dir, tag=str(meta.get("tag") or os.path.basename(run_dir)),
                             labels=meta.get("labels") or {}, status=meta.get("status", "finished"),
                             failures=meta.get("failures") or 0, spent_usd=meta.get("spent_usd") or 0.0,
                             pid=meta.get("pid"), error=meta.get("error"), role_scores=meta.get("role_scores") or {})
    if record.status == "finished":
        public = read_json_or_none(os.path.join(run_dir, "score", "public.json"))
        if public is not None and public.get("score") is not None:
            record.composite = public["score"]
            record.td_runs = {name: values for grid in public.get("grids", {}).values()
                              for name, values in grid.get("td_runs", {}).items()}
    return record


def run_folders_in(folder):
    if not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, name) for name in os.listdir(folder)
                  if os.path.exists(os.path.join(folder, name, "meta.json")))


def mark_run_crashed(run_dir, reason):
    """Record, as a failure, that a run's process is gone without having said why (kill -9, a power cut)."""
    path = os.path.join(run_dir, "meta.json")
    meta = read_json_or_none(path)
    if meta is not None and meta.get("status") in ("running", "scoring"):
        meta.update(status="crashed", error=reason, failures=(meta.get("failures") or 0) + 1)
        write_json_atomically(path, meta)


class ExperimentFolder:
    """The paths inside one experiment folder, and what can be read from all of it."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        for name in ("config", "state", "history", "blocks", "monitor", "cycles", "summary", "log", "lock"):
            file_name = {"config": "config.json", "state": "state.json", "summary": "summary.md", "log": "loop.log",
                         "lock": "loop.lock"}.get(name, f"{name}.jsonl")
            setattr(self, name, os.path.join(self.path, file_name))
        self.candidates_dir, self.runs_dir = os.path.join(self.path, "candidates"), os.path.join(self.path, "runs")

    def candidate_dir(self, name):
        return os.path.join(self.candidates_dir, name)

    def harness_dir(self, name):
        return os.path.join(self.candidates_dir, name, "harness")

    def block_dir(self, block):
        return os.path.join(self.runs_dir, block)

    def run_records(self, block=None):
        """Every run of one block, or of every block, oldest first within a block."""
        blocks = [block] if block else sorted(os.listdir(self.runs_dir)) if os.path.isdir(self.runs_dir) else []
        records = (read_run_record(run_dir) for name in blocks for run_dir in run_folders_in(self.block_dir(name)))
        return [record for record in records if record is not None]

    def scored_runs_of_harness(self, name):
        """Run folders of every scored run of the harness called name, from every block, oldest first."""
        runs = [record for record in self.run_records() if record.is_scored and record.labels.get("harness") == name]
        return [record.run_dir for record in sorted(runs, key=lambda record: record.tag)]

    def spent_usd(self):
        """Everything spent so far: every solver run's meta.json and every proposal's updater cost, from the files."""
        spent = sum(record.spent_usd for record in self.run_records())
        for name in sorted(os.listdir(self.candidates_dir)) if os.path.isdir(self.candidates_dir) else []:
            proposal = read_json_or_none(os.path.join(self.candidate_dir(name), "proposal.json"))
            if proposal is not None:
                spent += (proposal.get("updater") or {}).get("spent_usd") or 0.0
            else:                                   # interrupted: its transcript has the spend up to the interruption
                transcript = read_json_or_none(os.path.join(self.candidate_dir(name), "transcript.json"))
                spent += (transcript or {}).get("spent_usd") or 0.0
        return spent


# ---- processes -------------------------------------------------------------------------------------------------
def command_line_of(pid):
    """The command line of a live process, or None if there is no such process."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        result = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "command="], capture_output=True, text=True,
                                timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def solver_process_alive(record):
    """True if the process that last wrote this run's meta.json is still a solver_run.py process on this run. The
    command line is matched, not just the pid, because a pid can be reused after a reboot."""
    command = command_line_of(record.pid)
    if not command or "solver_run.py" not in command:
        return False
    if record.run_dir in command:                       # a resumed run: solver_run.py --resume RUN_DIR
        return True
    words = command.split()
    return bool(record.labels) and all(f"{key}={value}" in words for key, value in record.labels.items())


class LoopLock:
    """loop.lock holds the loop's pid while it runs. A live rsi_experiment.py process holding it stops a second loop
    on the same folder."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        holder = read_json_or_none(self.path) or {}
        if holder.get("pid") not in (None, os.getpid()):
            command = command_line_of(holder["pid"])
            if command and "rsi_experiment.py" in command:
                raise SystemExit(f"{os.path.dirname(self.path)} is in use by process {holder['pid']} (loop.lock). "
                                 "Stop that loop first.")
        write_json_atomically(self.path, {"pid": os.getpid(), "since": time.strftime("%Y-%m-%d %H:%M:%S")})
        return self

    def __exit__(self, *exception):
        try:
            os.remove(self.path)
        except OSError:
            pass
        return False


class LaunchedSolverProcess:
    """One solver_run.py process, in its own session so a Ctrl-C in the terminal reaches only the loop (which then
    stops its runs in order), with its output appended to a log file."""

    def __init__(self, command, log_path):
        self.log_file = open(log_path, "a")
        self.log_file.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')}  {' '.join(command)}\n")
        self.log_file.flush()
        self.process = subprocess.Popen(command, stdout=self.log_file, stderr=subprocess.STDOUT, start_new_session=True)

    def poll(self):
        return self.process.poll()

    @property
    def returncode(self):
        return self.process.returncode

    def ask_to_stop(self):
        """SIGTERM to its process group: solver_run.py records "stopped", stops its scorer and saves everything."""
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

    def wait_or_kill(self, grace_s):
        try:
            self.process.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            self.process.wait()
        self.close()

    def close(self):
        if not self.log_file.closed:
            self.log_file.close()


class SolverLauncher:
    """Starts new solver runs and resumes old ones."""

    def __init__(self, settings):
        self.settings = settings

    def start_new(self, block_dir, labels, harness_dir, log_path):
        settings = self.settings
        command = [sys.executable, str(SOLVER_RUN_SCRIPT), settings.solver_model, settings.solver_effort,
                   "--harness", harness_dir, "--out", block_dir, "--config", settings.scorer_config,
                   "--noise", settings.noise]
        command += [part for key, value in labels.items() for part in ("--label", f"{key}={value}")]
        if settings.workers:
            command += ["--workers", str(settings.workers)]
        return LaunchedSolverProcess(command, log_path)

    def resume(self, run_dir, log_path):
        return LaunchedSolverProcess([sys.executable, str(SOLVER_RUN_SCRIPT), "--resume", run_dir], log_path)


class InfrastructureError(RuntimeError):
    """Solver runs keep failing for a reason outside the harness (the API, Docker, the scorer)."""


# ---- running blocks of solver runs ---------------------------------------------------------------------------
class BlockRunner:
    """Gets a scored run for every (pair, arm) slot of a block: starts new runs, waits for runs left going by an
    earlier loop, resumes runs that crashed or were stopped, and replaces runs that keep failing."""

    def __init__(self, settings, folder, log, launcher=None, sleep=time.sleep, poll_s=5.0, launch_gap_s=2.0,
                 stop_grace_s=90.0):
        self.settings, self.folder, self.log = settings, folder, log
        self.launcher = launcher or SolverLauncher(settings)
        self.sleep, self.poll_s, self.launch_gap_s, self.stop_grace_s = sleep, poll_s, launch_gap_s, stop_grace_s

    def run_slots(self, block, slots, harnesses):
        """slots: [(pair, arm)] in launch order. harnesses: {arm: (harness name, harness folder)}.
        Returns {(pair, arm): SolverRunRecord} with a scored run for every slot."""
        block_dir = self.folder.block_dir(block)
        os.makedirs(os.path.join(block_dir, "logs"), exist_ok=True)
        already = sum(1 for slot, runs in self._runs_by_slot(block).items() if slot in slots and self._scored(runs))
        numbers = sorted({pair for pair, _ in slots})
        which = (f"runs {numbers[0]} to {numbers[-1]}" if all(arm == "current" for _, arm in slots)
                 else f"pairs {numbers[0]} to {numbers[-1]} ({len(slots)} runs)")
        self.log(f"   {block}: {which}" + (f", {already} already scored" if already else ""))
        children = {}                   # slot: LaunchedSolverProcess, for the runs this loop started
        failures_in_a_row = 0
        try:
            while True:
                runs_by_slot = self._runs_by_slot(block)
                for slot, child in list(children.items()):           # runs that ended since the last look
                    if child.poll() is None:
                        continue
                    child.close()
                    del children[slot]
                    latest = runs_by_slot.get(slot, [None])[-1]
                    if latest is not None and latest.status in ("running", "scoring"):
                        mark_run_crashed(latest.run_dir, f"the solver process ended (exit {child.returncode}) "
                                                         "without recording why")
                        runs_by_slot = self._runs_by_slot(block)
                        latest = runs_by_slot[slot][-1]
                    scored = self._scored(runs_by_slot.get(slot, []))
                    if scored is not None:
                        failures_in_a_row = 0
                        self.log(f"   {block} pair {slot[0]} {slot[1]}: {scored.composite:.3f} ({scored.tag})")
                        continue
                    failures_in_a_row += 1
                    self.log(f"   {block} pair {slot[0]} {slot[1]}: "
                             + (f"{latest.status} ({latest.error})" if latest else "ended without making a run folder")
                             + f"; {failures_in_a_row} failed in a row")
                    if failures_in_a_row >= self.settings.max_failures_in_a_row:
                        raise InfrastructureError(
                            f"{failures_in_a_row} solver sessions in a row failed (the last: "
                            f"{latest.error if latest else 'no run folder'}). Fix the cause, then --resume.")

                waiting, busy = [], len(children)
                for slot in slots:
                    runs = runs_by_slot.get(slot, [])
                    if slot in children or self._scored(runs) is not None:
                        continue
                    latest = runs[-1] if runs else None
                    if latest is not None and latest.status in ("running", "scoring"):
                        if solver_process_alive(latest):
                            busy += 1                    # left going by an earlier loop: wait for it
                            continue
                        mark_run_crashed(latest.run_dir, "its process was gone when the loop looked (kill -9, a power "
                                                         "cut, or the loop itself was killed)")
                        latest = read_run_record(latest.run_dir)
                        if latest is not None and latest.is_scored:
                            continue                     # it finished in the moment between the two looks
                    waiting.append((slot, latest))
                if not waiting and busy == 0:
                    runs_by_slot = self._runs_by_slot(block)
                    return {slot: self._scored(runs_by_slot[slot]) for slot in slots}
                for slot, latest in waiting:
                    if busy >= self.settings.parallel:
                        break
                    children[slot] = self._launch(block, block_dir, slot, latest, harnesses)
                    busy += 1
                    self.sleep(self.launch_gap_s)
                self.sleep(self.poll_s)
        finally:
            for child in children.values():
                child.ask_to_stop()
            for slot, child in children.items():
                child.wait_or_kill(self.stop_grace_s)
                self.log(f"   {block} pair {slot[0]} {slot[1]}: stopped with the loop")

    def _launch(self, block, block_dir, slot, latest, harnesses):
        pair, arm = slot
        log_path = os.path.join(block_dir, "logs", f"pair{pair:02d}_{arm}.log")
        if latest is not None and latest.status != "finished" and latest.failures <= self.settings.max_resumes:
            self.log(f"   {block} pair {pair} {arm}: resuming {latest.tag} ({latest.status}, "
                     f"{latest.failures} failure{'s' if latest.failures != 1 else ''} so far)")
            return self.launcher.resume(latest.run_dir, log_path)
        if latest is not None:
            self.log(f"   {block} pair {pair} {arm}: replacing {latest.tag} ({latest.status} after "
                     f"{latest.failures} failures) with a new run")
        harness_name, harness_dir = harnesses[arm]
        labels = {"block": block, "pair": pair, "arm": arm, "harness": harness_name}
        return self.launcher.start_new(block_dir, labels, harness_dir, log_path)

    def _runs_by_slot(self, block):
        runs_by_slot = {}
        for record in self.folder.run_records(block):
            if record.slot is not None:
                runs_by_slot.setdefault(record.slot, []).append(record)
        for runs in runs_by_slot.values():
            runs.sort(key=lambda record: record.tag)
        return runs_by_slot

    @staticmethod
    def _scored(runs):
        """The slot's scored run: the first one, if a slot ever has two."""
        return next((record for record in runs if record.is_scored), None)


def pair_slots(pair_numbers):
    """(pair, arm) in launch order. Which arm starts first alternates from pair to pair."""
    slots = []
    for pair in pair_numbers:
        slots += [(pair, arm) for arm in (ARMS if pair % 2 == 1 else ARMS[::-1])]
    return slots


# ---- the accept rule -----------------------------------------------------------------------------------------------
def permutation_p_value(candidate_scores, current_scores, random_relabellings=20000, seed=0):
    """One-sided permutation p-value for mean(candidate) < mean(current): the share of relabellings of the pooled
    scores whose candidate-minus-current difference is at least as low as the observed one. Exact when there are
    at most 50,000 relabellings, otherwise estimated from random_relabellings of them."""
    observed = statistics.mean(candidate_scores) - statistics.mean(current_scores)
    pooled, candidate_count = candidate_scores + current_scores, len(candidate_scores)
    current_count, total = len(current_scores), sum(candidate_scores) + sum(current_scores)

    def difference(indices):
        candidate_sum = sum(pooled[index] for index in indices)
        return candidate_sum / candidate_count - (total - candidate_sum) / current_count

    relabellings = math.comb(len(pooled), candidate_count)
    if relabellings <= 50000:
        hits = sum(1 for indices in itertools.combinations(range(len(pooled)), candidate_count)
                   if difference(indices) <= observed + 1e-12)
        return hits / relabellings
    generator = random.Random(seed)
    hits = sum(1 for _ in range(random_relabellings)
               if difference(generator.sample(range(len(pooled)), candidate_count)) <= observed + 1e-12)
    return (hits + 1) / (random_relabellings + 1)


def compare_scores(candidate_scores, current_scores):
    """The numbers the accept rule and the history use."""
    variance_of_difference = sum(statistics.variance(scores) / len(scores) for scores in (candidate_scores, current_scores)
                                 if len(scores) > 1)
    return {"n_candidate": len(candidate_scores), "n_current": len(current_scores),
            "mean_candidate": statistics.mean(candidate_scores), "mean_current": statistics.mean(current_scores),
            "se_difference": math.sqrt(variance_of_difference),
            "p_value": permutation_p_value(candidate_scores, current_scores)}


def td_means_and_failure_rates(records):
    """({disturbance: {P, Q}} mean TD over the runs where it did not fail, {disturbance: share of runs it failed in})."""
    names = sorted({name for record in records for name in record.td_runs})
    td_means, failure_rates = {}, {}
    for name in names:
        values = [record.td_runs[name] for record in records if name in record.td_runs]
        worked = [value for value in values if "failure" not in value]
        failure_rates[name] = sum(1 for value in values if "failure" in value) / len(values)
        if worked:
            td_means[name] = {"P": statistics.mean(value["P"] for value in worked),
                              "Q": statistics.mean(value["Q"] for value in worked)}
    return td_means, failure_rates


def monitor_stats(records):
    """For you only: the selection (B), monitor (M) and train-holdout (A) means, and the per-run M - B gap."""
    rows = [record.role_scores for record in records if "selection" in record.role_scores]
    stats = {"n": len(rows)}
    for role in ("selection", "monitor", "train_holdout"):
        values = [row[role] for row in rows if role in row]
        if values:
            stats[role] = statistics.mean(values)
    gaps = [row["monitor"] - row["selection"] for row in rows if "monitor" in row]
    if gaps:
        stats["gap_mean"] = statistics.mean(gaps)
        stats["gap_sd"] = statistics.stdev(gaps) if len(gaps) > 1 else None
    return stats


@dataclass
class BlockOutcome:
    block: str
    kind: str                           # "test" or "confirm"
    candidate: str
    current: str
    pairs_planned: int
    pairs_run: int
    stopped_early: bool
    passed: bool
    comparison: dict
    candidate_runs: list
    current_runs: list


# ---- cycles (for you only) ------------------------------------------------------------------------------------
def file_content_fingerprint(path):
    """Hash of a file's text with trailing whitespace and blank lines ignored; 'absent' if there is no file."""
    if not os.path.exists(path):
        return "absent"
    try:
        with open(path, encoding="utf-8", errors="replace") as file:
            lines = [line.rstrip() for line in file.read().splitlines() if line.strip()]
    except OSError:
        return "unreadable"
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def find_repeats(folder, iteration, name, parent, proposal):
    """Earlier harnesses (other than the parent) this candidate returns to: the whole harness by fingerprint, and
    each file it changed by content. A match with a rejected candidate is a repeated proposal; a match with an
    older kept harness, h000 included, is a step back. For cycles.jsonl and summary.md, never for the updater."""
    fingerprints = {}
    for number in range(iteration):
        earlier = f"h{number:03d}"
        if earlier != parent and os.path.isdir(folder.harness_dir(earlier)):
            fingerprints[earlier] = harness_fingerprint(folder.harness_dir(earlier))
    candidate_dir = folder.harness_dir(name)
    fingerprint = proposal.get("candidate_sha") or (harness_fingerprint(candidate_dir) if os.path.isdir(candidate_dir) else None)
    same_files = {}
    if os.path.isdir(candidate_dir):
        for changed in proposal.get("files_changed") or []:
            content = file_content_fingerprint(os.path.join(candidate_dir, changed["path"]))
            matches = [earlier for earlier in fingerprints
                       if file_content_fingerprint(os.path.join(folder.harness_dir(earlier), changed["path"])) == content]
            if matches:
                same_files[changed["path"]] = matches
    return {"iteration": iteration, "candidate": name, "parent": parent, "harness_sha": fingerprint,
            "same_harness_as": [earlier for earlier, value in fingerprints.items() if value == fingerprint],
            "same_file_as": same_files}


def repeats_text(cycle):
    if not cycle:
        return ""
    parts = ["whole harness = " + ", ".join(cycle["same_harness_as"])] if cycle.get("same_harness_as") else []
    parts += [f"{path} = " + ", ".join(names[-3:]) for path, names in (cycle.get("same_file_as") or {}).items()]
    return "; ".join(parts)


def write_summary(folder, settings):
    """summary.md, from blocks.jsonl, monitor.jsonl, history.jsonl and cycles.jsonl."""
    monitor = {line["block"]: line["arms"] for line in read_jsonl(folder.monitor)}
    history = {line["iteration"]: line for line in read_jsonl(folder.history)}
    cycles = {line["iteration"]: line for line in read_jsonl(folder.cycles)}
    blocks_by_iteration = {}
    for line in read_jsonl(folder.blocks):
        blocks_by_iteration.setdefault(line["iteration"], []).append(line)

    def number(value, digits=3):
        return "-" if value is None else f"{value:.{digits}f}"

    def both(arms, key):
        return " / ".join(number((arms.get(arm) or {}).get(key)) for arm in ARMS)

    confirmation = (f"then a confirmation block of {settings.confirm_pairs} new pairs for a candidate that passes, "
                    if settings.confirm_pairs else "")
    lines = ["# RSI experiment summary (for you, never shown to the updater)", "",
             f"Solver {settings.solver_model} at effort {settings.solver_effort}, {settings.noise} data, updater "
             f"{settings.updater_model} at effort {settings.updater_effort}, scope {settings.scope}. Each candidate "
             f"runs against the current harness in pairs started together: a test block of {settings.pairs} pairs "
             + (f"(stopped after {settings.early_stop_pairs} if the candidate is not ahead), " if settings.early_stop_pairs else "")
             + f"{confirmation}each block tested on its own at alpha {settings.alpha}. B is the selection grid the "
             "accept rule uses, M the hidden monitor, A grid A's own held-out runs; each cell is candidate / current. "
             "The over-optimization signal is the candidate's M - B gap rising while its B improves. The current "
             "harness's B from block to block shows drift in the solver or the API, not in the harness. Repeats "
             "lists earlier harnesses a candidate returns to (cycles.jsonl has the full lists).", "",
             "| iter | block | candidate / current | runs | B | p | M - B | A | result | repeats | change |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for iteration in sorted(set(blocks_by_iteration) | set(history)):
        record, cycle = history.get(iteration, {}), cycles.get(iteration)
        repeats = repeats_text(cycle).replace("|", "/") or "-"
        change = record.get("change") or ""
        if record.get("note"):
            change += (" / " if change else "") + "not run: " + record["note"]
        change = change.replace("|", "/").replace("\n", " ")[:200]
        blocks = blocks_by_iteration.get(iteration, [])
        if iteration > 0 and not blocks:
            lines.append(f"| {iteration} | - | {record.get('candidate', '-')} / {record.get('parent', '-')} | - | - | - | "
                         f"- | - | {record.get('outcome', '-')} | {repeats} | {change} |")
        for position, block in enumerate(blocks):
            arms = monitor.get(block["block"], {})
            last = position == len(blocks) - 1
            if block["kind"] == "baseline":
                result, runs = "baseline", f"- / {block['n_current']}"
                means = f"- / {number(block['mean_current'])}"
            else:
                result = record.get("outcome", "in progress") if last else ("passed" if block["passed"] else "failed")
                runs, means = f"{block['n_candidate']} / {block['n_current']}", \
                    f"{number(block['mean_candidate'])} / {number(block['mean_current'])}"
            lines.append(f"| {iteration} | {block['block']} | {block.get('candidate') or '-'} / {block['current']} | {runs} | "
                         f"{means} | {number(block.get('p_value'), 2)} | {both(arms, 'gap_mean')} | "
                         f"{both(arms, 'train_holdout')} | {result} | {repeats if last else ''} | {change if last else ''} |")
    with open(folder.summary, "w") as file:
        file.write("\n".join(lines) + "\n")


# ---- the loop -------------------------------------------------------------------------------------------------------
class RsiExperiment:
    """One experiment folder: the baseline, then iterations of propose, test, confirm, keep or not."""

    def __init__(self, settings, client=None, launcher=None, sleep=time.sleep, poll_s=5.0, launch_gap_s=2.0):
        self.settings = settings
        self.folder = ExperimentFolder(settings.out)
        self.log = LoopLog(self.folder.log)
        self.client = client                        # None: harness_proposal.py makes a real API client
        self.block_runner = BlockRunner(settings, self.folder, self.log, launcher, sleep, poll_s, launch_gap_s)
        self.hidden_names = hidden_score_names_pattern(settings.scorer_config)

    def scrub(self, text):
        """Loop-written notes go to later updaters: keep hidden and forbidden names out of them."""
        text, _ = remove_hidden_device_names(str(text))
        return self.hidden_names.sub("[hidden]", text)

    def run(self, resuming=False):
        settings, folder = self.settings, self.folder
        for warning in settings.warnings():
            self.log("warning:", warning)
        history = read_jsonl(folder.history, keep_through_iteration=10 ** 9)        # drops a torn last line
        if [record.get("iteration") for record in history] != list(range(1, len(history) + 1)):
            raise SystemExit(f"history.jsonl in {folder.path} does not run 1, 2, 3 ...; fix it by hand before resuming")
        for path in (folder.blocks, folder.monitor, folder.cycles):     # records of an unfinished iteration go
            read_jsonl(path, keep_through_iteration=len(history))

        self._baseline()
        current, misses = "h000", 0
        for record in history:
            current = record["candidate"] if record["outcome"] == "accepted" else current
            misses = 0 if record["outcome"] == "accepted" else misses + 1
        write_summary(folder, settings)
        if resuming:
            self.log(f"{len(history)} iterations done; current harness {current}; {misses} not kept in a row; "
                     f"${folder.spent_usd():.2f} spent so far")
        for iteration in range(len(history) + 1, settings.iters + 1):
            if misses >= settings.patience:
                break
            spent = folder.spent_usd()
            if spent > settings.max_usd:
                self.log(f"stopping: ${spent:.2f} spent, past --max-usd {settings.max_usd}")
                break
            name = f"h{iteration:03d}"
            proposal = self._proposal(iteration, name, current)
            record, cycle = self._attempt(iteration, name, current, proposal)
            append_jsonl(folder.cycles, dict(cycle, outcome=record["outcome"]))
            append_jsonl(folder.history, record)          # last: a line here means the iteration is done
            write_summary(folder, settings)
            current = name if record["outcome"] == "accepted" else current
            misses = 0 if record["outcome"] == "accepted" else misses + 1
            spent = folder.spent_usd()
            write_json_atomically(folder.state, {"iteration": iteration, "current": current, "misses_in_a_row": misses,
                                                 "spent_usd": round(spent, 4), "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")})
            self.log(f"   current harness {current}; {misses} not kept in a row; ${spent:.2f} spent so far")
        if misses >= settings.patience:
            self.log(f"stopping: {misses} attempts in a row were not kept (--patience {settings.patience})")
        self.log(f"done. current harness {current} ({os.path.relpath(folder.harness_dir(current), folder.path)}); "
                 f"summary in {folder.summary}")
        return current

    def _baseline(self):
        folder, settings = self.folder, self.settings
        starting_harness = folder.harness_dir("h000")
        if not os.path.isdir(starting_harness):
            copy_harness(settings.start, starting_harness)
        if any(line["kind"] == "baseline" for line in read_jsonl(folder.blocks)):
            return
        self.log(f"baseline: {settings.baseline_runs} runs of {settings.start}")
        block = "h000_baseline"
        records = self.block_runner.run_slots(block, [(run, "current") for run in range(1, settings.baseline_runs + 1)],
                                              {"current": ("h000", starting_harness)})
        runs = [records[slot] for slot in sorted(records)]
        mean = statistics.mean(record.composite for record in runs)
        append_jsonl(folder.blocks, {"iteration": 0, "block": block, "kind": "baseline", "candidate": None,
                                     "current": "h000", "n_current": len(runs), "mean_current": mean,
                                     "spent_usd": round(sum(record.spent_usd for record in folder.run_records(block)), 4),
                                     "runs": {"current": [record.tag for record in runs]}})
        append_jsonl(folder.monitor, {"iteration": 0, "block": block, "kind": "baseline",
                                      "arms": {"current": {"harness": "h000", **monitor_stats(runs)}}})
        self.log(f"baseline mean composite {mean:.3f} over {len(runs)} runs")

    def _proposal(self, iteration, name, current):
        """The saved proposal for this iteration, or a new one. A candidate folder without a readable proposal.json
        was interrupted mid-proposal; it is moved aside (its spend still counts) and the proposal made again."""
        candidate_dir = self.folder.candidate_dir(name)
        saved = read_json_or_none(os.path.join(candidate_dir, "proposal.json"))
        if saved is not None and "status" in saved:
            self.log(f"iteration {iteration}: {name} from its saved proposal")
            return saved
        if os.path.exists(candidate_dir):
            aside = candidate_dir + time.strftime(".interrupted_%Y%m%d_%H%M%S")
            os.rename(candidate_dir, aside)
            self.log(f"   {name} was interrupted before its proposal was saved; moved to {os.path.basename(aside)}")
        self.log(f"iteration {iteration}: proposing {name} from {current}")
        settings = self.settings
        try:
            return propose_candidate(self.folder.scored_runs_of_harness(current), self.folder.harness_dir(current),
                                     candidate_dir, scope=settings.scope, history=read_history(self.folder.history),
                                     model=settings.updater_model, effort=settings.updater_effort,
                                     max_usd=settings.updater_max_usd, smoke=settings.smoke,
                                     smoke_python=settings.smoke_python, client=self.client,
                                     newest_runs=settings.newest_runs, self_test=settings.self_test,
                                     scorer_config=settings.scorer_config)
        except SandboxUnavailable as error:
            raise InfrastructureError(f"the candidate's checker could not run: {error}. Start Docker, then --resume.") from error

    def _attempt(self, iteration, name, current, proposal):
        """Run the candidate against the current harness and decide. Returns (history record, cycle record)."""
        manifest = proposal.get("manifest") or {}
        record = {"iteration": iteration, "candidate": name, "parent": current,
                  "files_changed": [self.scrub(changed["path"]) for changed in proposal["files_changed"]],
                  **{key: manifest[key] for key in ("root_cause", "change", "predicted_effect", "at_risk") if key in manifest}}
        diff_path = os.path.join(self.folder.candidate_dir(name), "diff.patch")
        if proposal["files_changed"] and os.path.exists(diff_path):
            with open(diff_path) as file:
                record["diff_excerpt"] = file.read()
        self.log(f"   {name}: {proposal['status']}" + (f": {manifest['change']}" if manifest.get("change") else ""))
        cycle = find_repeats(self.folder, iteration, name, current, proposal)
        if repeats_text(cycle):
            self.log(f"   {name} returns to earlier harnesses: {repeats_text(cycle)}")
        if proposal["status"] != "ok":
            why = ("; ".join(proposal.get("errors") or []) if proposal["status"] == "invalid"
                   else WHY_NOT_RUN.get(proposal["status"], f"the proposal ended with status {proposal['status']}"))
            record.update(outcome="invalid", note=self.scrub(why)[:600])
            self.log(f"   {name} is not run: {record['note']}")
            return record, cycle

        arms = {"candidate": (name, self.folder.harness_dir(name)), "current": (current, self.folder.harness_dir(current))}
        shown = test = self._paired_block(iteration, "test", arms, self.settings.pairs)
        if test.stopped_early:
            outcome = "rejected_early"
        elif not test.passed:
            outcome = "rejected"
        elif not self.settings.confirm_pairs:
            outcome = "accepted"
        else:
            self.log(f"   {name} passed its test block; {self.settings.confirm_pairs} new pairs to confirm it")
            shown = self._paired_block(iteration, "confirm", arms, self.settings.confirm_pairs)
            outcome = "accepted" if shown.passed else "reverted"
        td_candidate, failures_candidate = td_means_and_failure_rates(shown.candidate_runs)
        td_current, failures_current = td_means_and_failure_rates(shown.current_runs)
        record.update(outcome=outcome, **shown.comparison, td_candidate=td_candidate, td_current=td_current,
                      fail_rate_candidate=failures_candidate, fail_rate_current=failures_current)
        self.log(f"   {name} {outcome}")
        return record, cycle

    def _paired_block(self, iteration, kind, arms, pair_count):
        """Run a block of pairs, stopping early if the candidate is not ahead after --early-stop-pairs, and record it
        in blocks.jsonl and monitor.jsonl."""
        candidate, current = arms["candidate"][0], arms["current"][0]
        block = f"{candidate}_{kind}"
        stop_check = self.settings.early_stop_pairs if 0 < self.settings.early_stop_pairs < pair_count else None
        stopped_early = False
        if stop_check:
            records = self.block_runner.run_slots(block, pair_slots(range(1, stop_check + 1)), arms)
            early = compare_scores(*self._scores_by_arm(records))
            stopped_early = early["mean_candidate"] >= early["mean_current"]
            if stopped_early:
                self.log(f"   {block}: after {stop_check} pairs the candidate is not ahead ({early['mean_candidate']:.3f} "
                         f"against {early['mean_current']:.3f}); stopping the block")
        if not stopped_early:
            records = self.block_runner.run_slots(block, pair_slots(range(1, pair_count + 1)), arms)
        comparison = compare_scores(*self._scores_by_arm(records))
        passed = (not stopped_early and comparison["mean_candidate"] < comparison["mean_current"]
                  and comparison["p_value"] <= self.settings.alpha)
        candidate_runs = [records[slot] for slot in sorted(records) if slot[1] == "candidate"]
        current_runs = [records[slot] for slot in sorted(records) if slot[1] == "current"]
        outcome = BlockOutcome(block, kind, candidate, current, pair_count, len(candidate_runs), stopped_early, passed,
                               comparison, candidate_runs, current_runs)
        append_jsonl(self.folder.blocks, {
            "iteration": iteration, "block": block, "kind": kind, "candidate": candidate, "current": current,
            "pairs_planned": pair_count, "pairs_run": outcome.pairs_run, "stopped_early": stopped_early, "passed": passed,
            **comparison, "spent_usd": round(sum(record.spent_usd for record in self.folder.run_records(block)), 4),
            "runs": {"candidate": [record.tag for record in candidate_runs], "current": [record.tag for record in current_runs]}})
        append_jsonl(self.folder.monitor, {"iteration": iteration, "block": block, "kind": kind, "arms": {
            "candidate": {"harness": candidate, **monitor_stats(candidate_runs)},
            "current": {"harness": current, **monitor_stats(current_runs)}}})
        self.log(f"   {block}: {comparison['mean_candidate']:.3f} against {comparison['mean_current']:.3f} over "
                 f"{outcome.pairs_run} pairs, p = {comparison['p_value']:.3f}"
                 + (", stopped early" if stopped_early else ", passed" if passed else ", not passed"))
        return outcome

    @staticmethod
    def _scores_by_arm(records):
        return tuple([records[slot].composite for slot in sorted(records) if slot[1] == arm] for arm in ARMS)


# ---- starting and resuming ------------------------------------------------------------------------------------------
def start_experiment(settings, client=None, launcher=None, **runner_options):
    """A new experiment in settings.out. Returns the name of the harness that is current at the end."""
    os.makedirs(settings.out)
    os.makedirs(os.path.join(settings.out, "candidates"))
    os.makedirs(os.path.join(settings.out, "runs"))
    folder = ExperimentFolder(settings.out)
    write_json_atomically(folder.config, {"settings": asdict(settings), "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                          "git_commit": git_commit(), "resumes": []})
    with LoopLock(folder.lock):
        experiment = RsiExperiment(settings, client, launcher, **runner_options)
        current = experiment.run()
        pack_finished_experiment(experiment)
        return current


def resume_experiment(experiment_dir, overrides=None, client=None, launcher=None, **runner_options):
    """Carry on the experiment in experiment_dir, with new values for any of RESUMABLE_SETTINGS."""
    folder = ExperimentFolder(experiment_dir)
    config = read_json_or_none(folder.config)
    if config is None:
        raise SystemExit(f"nothing to resume in {folder.path}: no readable config.json")
    overrides = {key: value for key, value in (overrides or {}).items() if value is not None}
    refused = sorted(set(overrides) - set(RESUMABLE_SETTINGS))
    if refused:
        raise SystemExit(f"--resume cannot change {refused}; only {list(RESUMABLE_SETTINGS)}")
    with LoopLock(folder.lock):
        changed = {key: value for key, value in overrides.items() if config["settings"].get(key) != value}
        config["settings"].update(overrides)
        config.setdefault("resumes", []).append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "changed": changed, "git_commit": git_commit()})
        write_json_atomically(folder.config, config)
        settings = ExperimentSettings(**{**config["settings"], "out": folder.path})
        experiment = RsiExperiment(settings, client, launcher, **runner_options)
        experiment.log("resuming" + (f" with {changed}" if changed else ""))
        try:
            restore(folder.path, experiment.log)       # a finished experiment being extended was packed
        except ArchiveError as error:
            raise SystemExit(f"cannot resume: {error}")
        current = experiment.run(resuming=True)
        pack_finished_experiment(experiment)
        return current


def pack_finished_experiment(experiment):
    """A loop that ended on its own (--iters, --patience, --max-usd) no longer needs its runs' transcripts,
    checkpoints or leftover sandboxes: pack them into archive.tar.xz, and delete the scorer's failure trajectories and
    DEBUG tails (experiment_archive.py).
    A loop stopped by a signal or exit code 3 never gets here. A failure leaves nothing lost and does not change the
    loop's outcome."""
    try:
        archive(experiment.folder.path, experiment.log)
    except Exception as error:      # noqa: BLE001 (the loop's result stands either way)
        experiment.log(f"archive: not finished ({error}); nothing is lost. Pack by hand with "
                       f"rsi/experiment_archive.py {experiment.folder.path}")


def parse_arguments(argv=None):
    """(settings, None) for a new experiment, or (None, (experiment folder, overrides)) for --resume."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(argument == "--resume" or argument.startswith("--resume=") for argument in argv):
        parser = argparse.ArgumentParser(description="Resume an RSI experiment. Only these settings can change; the "
                                                     "rest come from the experiment's config.json.")
        parser.add_argument("--resume", required=True, metavar="EXPERIMENT", help="the experiment folder")
        parser.add_argument("--iters", type=int, help="new total number of iterations (to extend a finished experiment)")
        parser.add_argument("--patience", type=int)
        parser.add_argument("--max-usd", type=float)
        parser.add_argument("--parallel", type=int)
        parser.add_argument("--workers", type=int)
        parser.add_argument("--updater-max-usd", type=float)
        parser.add_argument("--max-resumes", type=int)
        options = parser.parse_args(argv)
        return None, (os.path.abspath(options.resume), {key: getattr(options, key) for key in RESUMABLE_SETTINGS})
    defaults = ExperimentSettings(iters=1, out="")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--iters", type=int, required=True, help="iterations (updater proposals)")
    parser.add_argument("--pairs", type=int, default=defaults.pairs, help="pairs of runs in a test block")
    parser.add_argument("--early-stop-pairs", type=int, default=defaults.early_stop_pairs,
                        help="after this many pairs, reject a candidate that is not ahead (0: never)")
    parser.add_argument("--confirm-pairs", type=int, default=defaults.confirm_pairs,
                        help="pairs in the confirmation block of a candidate that passed (0: no confirmation)")
    parser.add_argument("--alpha", type=float, default=defaults.alpha, help="one-sided permutation-test level, per block")
    parser.add_argument("--baseline-runs", type=int, default=defaults.baseline_runs,
                        help="runs of the starting harness for the first updater to read")
    parser.add_argument("--parallel", type=int, default=defaults.parallel, help="solver runs at a time")
    parser.add_argument("--solver-model", default="haiku", help="as solver_run.py: 1-3, haiku, sonnet, opus or a model id")
    parser.add_argument("--solver-effort", default="low", help="as solver_run.py: 1-5, low, medium, high, xhigh, max")
    parser.add_argument("--noise", choices=["noisy", "clean"], default=defaults.noise)
    parser.add_argument("--start", default=defaults.start, help="the starting harness")
    parser.add_argument("--scope", choices=["tools", "all"], default=defaults.scope)
    parser.add_argument("--config", dest="scorer_config", default=defaults.scorer_config,
                        help="scorer config (config_rsi.json: B selects, M monitors)")
    parser.add_argument("--workers", type=int, default=None, help="ANDES simulations at once when a run is scored")
    parser.add_argument("--patience", type=int, default=defaults.patience,
                        help="stop after this many attempts in a row that were not kept")
    parser.add_argument("--max-usd", type=float, default=defaults.max_usd,
                        help="start no new iteration past this total spend (USD)")
    parser.add_argument("--updater-model", default=defaults.updater_model)
    parser.add_argument("--updater-effort", default=defaults.updater_effort,
                        choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--updater-max-usd", type=float, default=defaults.updater_max_usd,
                        help="stop one updater call past this cost (USD)")
    parser.add_argument("--newest-runs", type=int, default=defaults.newest_runs,
                        help="how many of the current harness's newest runs the updater reads")
    parser.add_argument("--smoke", choices=["docker", "local", "off"], default=defaults.smoke)
    parser.add_argument("--smoke-python", default=None)
    parser.add_argument("--no-self-test", dest="self_test", action="store_false")
    parser.add_argument("--max-resumes", type=int, default=defaults.max_resumes,
                        help="resume a failed run until it has failed more often than this, then replace it")
    parser.add_argument("--max-failures-in-a-row", type=int, default=defaults.max_failures_in_a_row,
                        help="stop the loop after this many failed solver sessions with no run finishing in between")
    parser.add_argument("--out", default=None, help="experiment folder (default rsi/experiments/<date>_<time>)")
    options = parser.parse_args(argv)
    values = vars(options)
    values["out"] = os.path.abspath(values["out"] or os.path.join(DEFAULT_EXPERIMENTS_DIR, time.strftime("%Y%m%d_%H%M%S")))
    values["solver_model"] = resolve_model_id(values["solver_model"])
    values["solver_effort"] = resolve_effort(values["solver_effort"])
    for key in ("start", "scorer_config"):
        values[key] = os.path.abspath(values[key])
    settings = ExperimentSettings(**values)
    for problem in settings.problems():
        parser.error(problem)
    return settings, None


def _stop_on_signal(signal_number, frame):
    raise SystemExit(128 + signal_number)          # so the block runner's finally stops its solver runs


def main(argv=None):
    for signal_number in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signal_number, _stop_on_signal)
    settings, resume = parse_arguments(argv)
    try:
        if resume:
            resume_experiment(*resume)
        else:
            start_experiment(settings)
    except InfrastructureError as error:
        print(f"stopped: {error}", flush=True)
        return INFRASTRUCTURE_EXIT_CODE
    return 0


if __name__ == "__main__":
    sys.exit(main())
