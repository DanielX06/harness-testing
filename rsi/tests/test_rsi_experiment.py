"""End-to-end checks of rsi_experiment.py with a scripted fake updater and a fake solver. The fake solver's runs
are copies of the Oct 13 runs (rsi/tests/fixtures), re-stamped with the harness that "made" them, so the updater's
context is built from real transcripts. No API call, no Docker, no ANDES.

    python rsi/tests/test_rsi_experiment.py [--smoke-python PATH]
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace as NS

sys.dont_write_bytecode = True
REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPOSITORY_ROOT)
from common.harness_files import harness_fingerprint  # noqa: E402
from common.project_paths import STARTING_HARNESS_DIR  # noqa: E402
from rsi import rsi_experiment as R  # noqa: E402
from rsi.updater_context import hidden_score_names_pattern  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--smoke-python", default=sys.executable)
smoke_python = parser.parse_args().smoke_python
FIXTURE_BATCH = os.path.join(REPOSITORY_ROOT, "rsi", "tests", "fixtures", "oct13_clean_batch")
SOURCES = sorted(os.path.join(FIXTURE_BATCH, name) for name in os.listdir(FIXTURE_BATCH)
                 if os.path.exists(os.path.join(FIXTURE_BATCH, name, "meta.json")))
work = tempfile.mkdtemp(prefix="rsi_experiment_test_")
passed = 0


def check(condition, description):
    global passed
    if not condition:
        raise AssertionError(description)
    passed += 1
    print("ok:", description)


def read_json(path):
    with open(path) as file:
        return json.load(file)


def write_json(path, content):
    with open(path, "w") as file:
        json.dump(content, file)


def read_lines(path):
    with open(path) as file:
        return [json.loads(line) for line in file if line.strip()]


# ---- a fake solver ------------------------------------------------------------------------------------------
class FakeProcess:
    def __init__(self, returncode):
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def ask_to_stop(self):
        pass

    def wait_or_kill(self, grace_s):
        pass

    def close(self):
        pass


def harness_quality(harness_dir, block):
    """What a harness does to a run's score in this fake world (lower is better)."""
    quality = 1.0
    if os.path.exists(os.path.join(harness_dir, "tools", "closed_loop_check.py")):
        quality *= 0.3
    if os.path.exists(os.path.join(harness_dir, "tools", "fading_check.py")) and block.endswith("_test"):
        quality *= 0.3                  # good in its test block, no better than its parent in its confirmation block
    with open(os.path.join(harness_dir, "method.md")) as file:
        if "Be careful" in file.read():
            quality *= 1.1
    return quality


class FakeLauncher:
    """Makes each run at once. A run's score is a fixed draw for its (block, pair) from the Oct 13 runs, times its
    harness's quality, so the two runs of a pair differ only by their harness. ending(block, pair, arm, attempt)
    says how each session ends: "finished", "crashed", "vanished" (the process ends with the status still running)
    or "no_folder" (it ends before making a run folder)."""
    runs_made = 0                       # across every experiment here, so run tags keep increasing

    def __init__(self, ending=None):
        self.ending = ending or (lambda block, pair, arm, attempt: "finished")
        self.launches, self.attempts = [], {}

    def _next_ending(self, block, pair, arm):
        self.attempts[(block, pair, arm)] = self.attempts.get((block, pair, arm), 0) + 1
        return self.ending(block, pair, arm, self.attempts[(block, pair, arm)])

    def start_new(self, block_dir, labels, harness_dir, log_path):
        block, pair, arm = labels["block"], int(labels["pair"]), labels["arm"]
        self.launches.append(("new", block, pair, arm))
        ending = self._next_ending(block, pair, arm)
        if ending == "no_folder":
            return FakeProcess(1)
        FakeLauncher.runs_made += 1
        tag = f"20261022_{100000 + FakeLauncher.runs_made:06d}_haiku_low_{FakeLauncher.runs_made:04x}"
        run_dir = os.path.join(block_dir, tag)
        source = random.Random(f"{block}:{pair}").choice(SOURCES)
        shutil.copytree(source, run_dir)
        public = read_json(os.path.join(run_dir, "score", "public.json"))
        score = public["score"] * harness_quality(harness_dir, block)
        public["score"] = score
        write_json(os.path.join(run_dir, "score", "public.json"), public)
        meta = read_json(os.path.join(run_dir, "meta.json"))
        has_tool = os.path.exists(os.path.join(harness_dir, "tools", "closed_loop_check.py"))
        meta.update(tag=tag, harness=harness_dir, harness_sha=harness_fingerprint(harness_dir), spent_usd=0.02,
                    labels={key: str(value) for key, value in labels.items()}, status="running", failures=0, resumes=0,
                    pid=None, error=None, role_scores={"selection": score, "monitor": score + (0.2 if has_tool else 0.05),
                                                       "train_holdout": score + 0.1})
        write_json(os.path.join(run_dir, "meta.json"), meta)
        return self._end_session(run_dir, ending)

    def resume(self, run_dir, log_path):
        meta = read_json(os.path.join(run_dir, "meta.json"))
        block, pair, arm = meta["labels"]["block"], int(meta["labels"]["pair"]), meta["labels"]["arm"]
        self.launches.append(("resume", block, pair, arm))
        meta["resumes"] = meta.get("resumes", 0) + 1
        write_json(os.path.join(run_dir, "meta.json"), meta)
        return self._end_session(run_dir, self._next_ending(block, pair, arm))

    @staticmethod
    def _end_session(run_dir, ending):
        meta = read_json(os.path.join(run_dir, "meta.json"))
        if ending == "finished":
            meta.update(status="finished", error=None)
        elif ending == "crashed":
            meta.update(status="crashed", error="APIConnectionError: connection lost", failures=meta["failures"] + 1,
                        spent_usd=meta["spent_usd"] + 0.01)
        write_json(os.path.join(run_dir, "meta.json"), meta)
        return FakeProcess(0 if ending == "finished" else 1)


# ---- a fake updater ---------------------------------------------------------------------------------------
class FakeClient:
    def __init__(self, script):
        self.script, self.requests, self.messages = list(script), [], self

    def stream(self, **request):
        self.requests.append(request)
        response = self.script.pop(0)

        class Stream:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get_final_message(self):
                return response
        return Stream()


USAGE = NS(input_tokens=20000, output_tokens=3000, cache_read_input_tokens=0, cache_creation_input_tokens=0)
_counter = [0]


def use(name, **tool_input):
    _counter[0] += 1
    return NS(type="tool_use", id=f"t{_counter[0]}", name=name, input=tool_input)


def reply(*blocks):
    return NS(content=list(blocks), stop_reason="tool_use", usage=USAGE)


FINISH = dict(evidence="B_line fails often.", root_cause="No closed-loop check.", change="Added a closed-loop check.",
              predicted_effect="Fewer B_line failures.", at_risk="Extra steps.")
TOOL = '"""Check.\n\n    python tools/closed_loop_check.py submission.json\n"""\nprint("ok")\n'
FADING_TOOL = '"""Check.\n\n    python tools/fading_check.py submission.json\n"""\nprint("ok")\n'
with open(os.path.join(STARTING_HARNESS_DIR, "method.md")) as file:
    METHOD = file.read().rstrip() + "\n8. Run python tools/closed_loop_check.py submission.json before submitting.\n"


def proposal(*writes):
    """An updater reply that writes files and finishes, then the second finish after its self-test."""
    return [reply(*[use("write_file", path=path, content=content) for path, content in writes], use("finish", **FINISH)),
            reply(use("finish", **FINISH))]


GOOD = proposal(("tools/closed_loop_check.py", TOOL), ("method.md", METHOD))
FORBIDDEN = proposal(("method.md", METHOD + "It is a GFM unit.\n"))
CAREFUL = proposal(("method.md", METHOD + "9. Be careful.\n"))
NO_OP = proposal(("method.md", METHOD + "9. x\n"))
FADING = proposal(("tools/fading_check.py", FADING_TOOL), ("method.md", METHOD.replace("closed_loop_check", "fading_check")))
FAST = dict(sleep=lambda seconds: None, poll_s=0, launch_gap_s=0)


def settings(name, **changes):
    values = dict(iters=3, out=os.path.join(work, name), pairs=4, early_stop_pairs=2, confirm_pairs=4, baseline_runs=4,
                  parallel=2, smoke="local", smoke_python=smoke_python)
    values.update(changes)
    return R.ExperimentSettings(**values)


def runs_in(experiment, block):
    return R.ExperimentFolder(experiment).run_records(block)


# 1. three iterations: kept after both blocks, never run, rejected early
launcher = FakeLauncher()
client = FakeClient(GOOD + FORBIDDEN + CAREFUL)
experiment = os.path.join(work, "main")
R.start_experiment(settings("main"), client=client, launcher=launcher, **FAST)
history = read_lines(os.path.join(experiment, "history.jsonl"))
blocks = read_lines(os.path.join(experiment, "blocks.jsonl"))
check([record["outcome"] for record in history] == ["accepted", "invalid", "rejected_early"],
      f"outcomes {[record['outcome'] for record in history]}")
check([block["block"] for block in blocks] == ["h000_baseline", "h001_test", "h001_confirm", "h003_test"],
      "blocks: the baseline, h001's test and confirmation blocks, h003's test block")
confirm_runs = [record for record in runs_in(experiment, "h001_confirm") if record.labels["arm"] == "candidate"]
check(history[0]["n_candidate"] == 4 and history[0]["n_current"] == 4
      and abs(history[0]["mean_candidate"] - sum(run.composite for run in confirm_runs) / 4) < 1e-12
      and "first_pass" not in history[0] and blocks[1]["passed"] and blocks[2]["passed"],
      "h001 passed both blocks; the updater is shown the confirmation block's numbers only")
check(blocks[3]["stopped_early"] and blocks[3]["pairs_run"] == 2 and len(runs_in(experiment, "h003_test")) == 4,
      "h003 is rejected after 2 pairs, and pairs 3 and 4 are never run")
check([(kind, pair, arm) for kind, block, pair, arm in launcher.launches if block == "h001_test"][:4]
      == [("new", 1, "candidate"), ("new", 1, "current"), ("new", 2, "current"), ("new", 2, "candidate")],
      "the two runs of a pair start together, and which arm starts first alternates")
current_runs = [record for record in runs_in(experiment, "h001_test") if record.labels["arm"] == "current"]
check(all(record.labels["harness"] == "h000" for record in current_runs)
      and len({record.tag for record in current_runs} & {record.tag for record in runs_in(experiment, "h000_baseline")}) == 0,
      "each block runs the current harness afresh; no run is reused from another block")
context3 = open(os.path.join(experiment, "candidates", "h003", "context.md")).read()
check("[name removed]" in history[1]["note"] and "GFM" not in history[1]["note"] and "GFM" not in context3
      and "Attempt 2: h002 from h001, never run" in context3,
      "an invalid candidate's note is scrubbed, and the next updater never sees the name")
check(history[1]["parent"] == "h001" and history[2]["parent"] == "h001", "later attempts build on the kept harness")
state = read_json(os.path.join(experiment, "state.json"))
check(state["current"] == "h001" and state["misses_in_a_row"] == 2, "state: current h001, two misses in a row")
context2 = open(os.path.join(experiment, "candidates", "h002", "context.md")).read()
check(f"Current harness {harness_fingerprint(os.path.join(experiment, 'candidates', 'h001', 'harness'))}" in context2
      and "Attempt 1: h001 from h000, kept" in context2 and "The table has the 8 most recent of its 8 runs" in context2,
      "iteration 2's updater reads h001's runs from both of its blocks, and attempt 1 in its history")
context1 = open(os.path.join(experiment, "candidates", "h001", "context.md")).read()
check("No earlier attempts" in context1 and "The table has the 4 most recent of its 4 runs" in context1,
      "iteration 1's updater reads the baseline runs only")
text = open(os.path.join(experiment, "history.jsonl")).read() + context2
check(hidden_score_names_pattern().search(text) is None and "gap_mean" not in text and "screen" not in text,
      "no monitor numbers reach the history or the context")
monitor = read_lines(os.path.join(experiment, "monitor.jsonl"))
check([line["block"] for line in monitor] == [block["block"] for block in blocks]
      and monitor[1]["arms"]["candidate"]["gap_mean"] > monitor[1]["arms"]["current"]["gap_mean"]
      and set(monitor[0]["arms"]) == {"current"}, "monitor.jsonl has both arms of every block")
summary = open(os.path.join(experiment, "summary.md")).read()
check(summary.count("\n| ") == 6 and "| 1 | h001_confirm | h001 / h000 | 4 / 4 |" in summary and "| accepted |" in summary
      and "| 2 | - | h002 / h001 |" in summary, "summary.md has the baseline, h001's two blocks, h002 and h003")
check(not client.script, "every scripted updater reply was used (self-test rounds included)")
all_runs = R.ExperimentFolder(experiment).run_records()
updater_spend = sum(read_json(os.path.join(experiment, "candidates", name, "proposal.json"))["updater"]["spent_usd"]
                    for name in ("h001", "h002", "h003"))
check(len(all_runs) == 4 + 8 + 8 + 4 and abs(state["spent_usd"] - (0.02 * len(all_runs) + updater_spend)) < 1e-3,
      f"spend is counted from the files (${state['spent_usd']:.3f} for {len(all_runs)} runs and three proposals)")

# 2. patience stops the loop
experiment = os.path.join(work, "patience")
R.start_experiment(settings("patience", iters=5, patience=2), client=FakeClient(NO_OP * 2), launcher=FakeLauncher(), **FAST)
check(len(read_lines(os.path.join(experiment, "history.jsonl"))) == 2, "--patience 2 stops after two misses")

# 3. a candidate that passes its test block and not its confirmation block is reverted
experiment = os.path.join(work, "fading")
R.start_experiment(settings("fading", iters=1), client=FakeClient(FADING), launcher=FakeLauncher(), **FAST)
history = read_lines(os.path.join(experiment, "history.jsonl"))
blocks = read_lines(os.path.join(experiment, "blocks.jsonl"))
check(blocks[1]["passed"] and not blocks[2]["passed"] and history[0]["outcome"] == "reverted"
      and history[0]["n_candidate"] == blocks[2]["n_candidate"] and history[0]["mean_candidate"] == blocks[2]["mean_candidate"],
      "a candidate that fails its confirmation block is reverted, and the history shows that block's numbers")


# 4. crashes and resumes: the loop dies in h001's confirmation block, then inside h002's proposal
class Crash(Exception):
    pass


class CrashingLauncher(FakeLauncher):
    def start_new(self, block_dir, labels, harness_dir, log_path):
        if labels["block"] == "h001_confirm" and sum(1 for launch in self.launches if launch[1] == "h001_confirm") == 2:
            raise Crash("the loop dies")
        return super().start_new(block_dir, labels, harness_dir, log_path)


experiment = os.path.join(work, "crash")
try:
    R.start_experiment(settings("crash", patience=5), client=FakeClient(GOOD), launcher=CrashingLauncher(), **FAST)
    crashed = False
except Crash:
    crashed = True
first_confirm_runs = sorted(record.tag for record in runs_in(experiment, "h001_confirm"))
check(crashed and not os.path.exists(os.path.join(experiment, "loop.lock")) and len(first_confirm_runs) == 2
      and open(os.path.join(experiment, "history.jsonl")).read() == "",
      "crash 1: the lock is released, h001's confirmation block has 2 runs, no iteration is recorded")

holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "rsi_experiment.py"])
write_json(os.path.join(experiment, "loop.lock"), {"pid": holder.pid})
try:
    R.resume_experiment(experiment, client=FakeClient([]), launcher=FakeLauncher(), **FAST)
    message = ""
except SystemExit as stop:
    message = str(stop)
holder.kill()
holder.wait()
check("loop.lock" in message, "a resume refuses a folder that a live loop holds")
os.remove(os.path.join(experiment, "loop.lock"))

launcher = FakeLauncher()
try:
    R.resume_experiment(experiment, client=FakeClient(CAREFUL[:1]), launcher=launcher, **FAST)
    crashed = False
except IndexError:                      # the scripted updater runs out in the middle of h002's proposal
    crashed = True
history = read_lines(os.path.join(experiment, "history.jsonl"))
confirm_runs = sorted(record.tag for record in runs_in(experiment, "h001_confirm"))
check(crashed and [record["outcome"] for record in history] == ["accepted"] and len(confirm_runs) == 8
      and confirm_runs[:2] == first_confirm_runs and len(read_lines(os.path.join(experiment, "blocks.jsonl"))) == 3
      and not any(block in ("h000_baseline", "h001_test") for _, block, _, _ in launcher.launches),
      "resume 1: h001 finishes its confirmation block with 6 new runs and is kept; nothing else is run again")
check(os.path.isdir(os.path.join(experiment, "candidates", "h002"))
      and not os.path.exists(os.path.join(experiment, "candidates", "h002", "proposal.json")),
      "crash 2: h002 is left without a proposal.json")

R.resume_experiment(experiment, {"iters": 3}, client=FakeClient(CAREFUL + CAREFUL), launcher=FakeLauncher(), **FAST)
history = read_lines(os.path.join(experiment, "history.jsonl"))
check([record["outcome"] for record in history] == ["accepted", "rejected_early", "rejected_early"]
      and [record["iteration"] for record in history] == [1, 2, 3],
      f"resume 2: outcomes {[record['outcome'] for record in history]}, iterations 1 to 3 once each")
interrupted = [name for name in os.listdir(os.path.join(experiment, "candidates")) if name.startswith("h002.interrupted_")]
check(len(interrupted) == 1, "the interrupted h002 was moved aside and made again")
check([line["block"] for line in read_lines(os.path.join(experiment, "monitor.jsonl"))]
      == ["h000_baseline", "h001_test", "h001_confirm", "h002_test", "h003_test"], "monitor.jsonl has one line per block, no repeats")
cycles = read_lines(os.path.join(experiment, "cycles.jsonl"))
check([cycle["candidate"] for cycle in cycles] == ["h001", "h002", "h003"] and cycles[2]["same_harness_as"] == ["h002"]
      and cycles[2]["same_file_as"] == {"method.md": ["h002"]} and not cycles[1]["same_harness_as"] and not cycles[0]["same_file_as"],
      "cycles.jsonl: h003 is the same harness as the rejected h002")
summary = open(os.path.join(experiment, "summary.md")).read()
context3 = open(os.path.join(experiment, "candidates", "h003", "context.md")).read()
check("whole harness = h002" in summary and "same_harness_as" not in context3 and "cycles" not in context3,
      "the repeat shows in summary.md and never in the updater's context")
state = read_json(os.path.join(experiment, "state.json"))
folder = R.ExperimentFolder(experiment)
updater_spend = sum(read_json(os.path.join(experiment, "candidates", name, "proposal.json"))["updater"]["spent_usd"]
                    for name in ("h001", "h002", "h003"))
interrupted_spend = read_json(os.path.join(experiment, "candidates", interrupted[0], "transcript.json"))["spent_usd"]
run_count = len(folder.run_records())
check(interrupted_spend > 0 and run_count == 4 + 8 + 8 + 4 + 4
      and abs(state["spent_usd"] - (0.02 * run_count + updater_spend + interrupted_spend)) < 1e-3,
      f"spend is counted once from the files, the interrupted proposal included (${state['spent_usd']:.3f}, {run_count} runs)")
config = read_json(os.path.join(experiment, "config.json"))
check(len(config["resumes"]) == 2 and config["resumes"][1]["changed"] == {} and config["settings"]["pairs"] == 4
      and config["settings"]["confirm_pairs"] == 4 and not os.path.exists(os.path.join(experiment, "loop.lock")),
      "config.json records both resumes and keeps the original settings")

lines_before = len(read_lines(os.path.join(experiment, "history.jsonl")))
R.resume_experiment(experiment, client=FakeClient([]), launcher=FakeLauncher(), **FAST)
check(len(read_lines(os.path.join(experiment, "history.jsonl"))) == lines_before, "resuming a finished experiment changes nothing")
R.resume_experiment(experiment, {"iters": 4}, client=FakeClient(CAREFUL), launcher=FakeLauncher(), **FAST)
cycles = read_lines(os.path.join(experiment, "cycles.jsonl"))
check(len(read_lines(os.path.join(experiment, "history.jsonl"))) == 4 and cycles[3]["same_harness_as"] == ["h002", "h003"],
      "--iters 4 adds one iteration, and a third identical proposal matches both earlier ones")
for argv in (["--resume", experiment, "--pairs", "10"],):
    try:
        R.parse_arguments(argv)
        took = True
    except SystemExit:
        took = False
    check(not took, "--resume refuses settings that would change the experiment (--pairs)")
try:
    R.resume_experiment(experiment, {"alpha": 0.5}, client=FakeClient([]), launcher=FakeLauncher(), **FAST)
    took = True
except SystemExit:
    took = False
check(not took, "resume_experiment refuses them too (alpha)")


# 5. failed runs inside a block: resumed, replaced, waited for
def block_runner(name, launcher, **options):
    folder = R.ExperimentFolder(os.path.join(work, name))
    os.makedirs(folder.runs_dir, exist_ok=True)
    runner_settings = R.ExperimentSettings(iters=1, out=folder.path, parallel=2)
    timing = {**FAST, **options}
    return folder, R.BlockRunner(runner_settings, folder, R.LoopLog(os.path.join(folder.path, "loop.log")), launcher,
                                 timing["sleep"], timing["poll_s"], timing["launch_gap_s"])


def ending(block, pair, arm, attempt):
    if pair == 2:
        return "crashed" if attempt == 1 else "finished"           # crashes once
    if pair == 3:
        return "crashed" if attempt <= 3 else "finished"           # fails three times, so it is replaced
    if pair == 4:
        return "vanished" if attempt == 1 else "finished"          # its process ends without saying why
    if pair == 5:
        return "no_folder" if attempt == 1 else "finished"         # it ends before making a run folder
    return "finished"


launcher = FakeLauncher(ending)
folder, runner = block_runner("failures", launcher)
slots = [(pair, "current") for pair in range(1, 7)]
results = runner.run_slots("b", slots, {"current": ("h000", str(STARTING_HARNESS_DIR))})
by_pair = {pair: [record for record in folder.run_records("b") if record.slot == (pair, "current")] for pair in range(1, 7)}
check(sorted(results) == slots and all(record.is_scored for record in results.values()), "every slot ends with a scored run")
check(len(by_pair[2]) == 1 and by_pair[2][0].failures == 1 and read_json(os.path.join(by_pair[2][0].run_dir, "meta.json"))["resumes"] == 1,
      "a run that crashed once is resumed in its own folder")
check(len(by_pair[3]) == 2 and by_pair[3][0].status == "crashed" and by_pair[3][0].failures == 3 and results[(3, "current")] is not None
      and results[(3, "current")].run_dir == by_pair[3][1].run_dir
      and [kind for kind, _, pair, _ in launcher.launches if pair == 3] == ["new", "resume", "resume", "new"],
      "a run that failed three times (more than --max-resumes 2) is replaced by a new run")
check(by_pair[4][0].failures == 1 and len(by_pair[4]) == 1, "a process that ended without saying why is counted as a failure and resumed")
check(len(by_pair[5]) == 1 and [kind for kind, _, pair, _ in launcher.launches if pair == 5] == ["new", "new"],
      "a process that ended before making a folder is started again")
check(abs(folder.spent_usd() - sum(record.spent_usd for records in by_pair.values() for record in records)) < 1e-9
      and by_pair[3][0].spent_usd > 0, "the replaced run's spend still counts")

launcher = FakeLauncher(lambda block, pair, arm, attempt: "no_folder")
folder, runner = block_runner("outage", launcher)
try:
    runner.run_slots("b", slots, {"current": ("h000", str(STARTING_HARNESS_DIR))})
    message = ""
except R.InfrastructureError as error:
    message = str(error)
check("6 solver sessions in a row failed" in message and len(launcher.launches) == 6,
      "six failed sessions in a row with no run finishing stop the loop")

# a run left going by a loop that was killed: waited for, not started again; a dead one is resumed
folder, runner = block_runner("orphans", FakeLauncher(), sleep=time.sleep, poll_s=0.2)
block_dir = folder.block_dir("b")
os.makedirs(block_dir)
orphans = {}
for pair in (1, 2):
    run_dir = os.path.join(block_dir, f"20261021_00000{pair}_haiku_low_orp{pair}")
    shutil.copytree(SOURCES[pair], run_dir)
    labels = {"block": "b", "pair": str(pair), "arm": "current", "harness": "h000"}
    finish_later = ("import json, os, sys, time; time.sleep(2); path = sys.argv[1]; meta = json.load(open(path)); "
                    "meta['status'] = 'finished'; out = open(path + '.tmp', 'w'); json.dump(meta, out); out.close(); "
                    "os.replace(path + '.tmp', path)")
    process = subprocess.Popen([sys.executable, "-c", finish_later if pair == 1 else "pass",
                                os.path.join(run_dir, "meta.json"), "solver_run.py"] + [f"{k}={v}" for k, v in labels.items()])
    if pair == 2:
        process.wait()                  # this one is already gone
    orphans[pair] = process
    meta = read_json(os.path.join(run_dir, "meta.json"))
    meta.update(labels=labels, status="running", pid=process.pid, failures=0, resumes=0)
    write_json(os.path.join(run_dir, "meta.json"), meta)
results = runner.run_slots("b", [(1, "current"), (2, "current"), (3, "current")],
                           {"current": ("h000", str(STARTING_HARNESS_DIR))})
orphans[1].wait()
check(results[(1, "current")].run_dir.endswith("orp1") and results[(2, "current")].run_dir.endswith("orp2")
      and [launch[0] for launch in runner.launcher.launches if launch[2] == 1] == []
      and [launch[0] for launch in runner.launcher.launches if launch[2] == 2] == ["resume"]
      and results[(2, "current")].failures == 1,
      "a live run from a killed loop is waited for; a dead one is marked as a failure and resumed")

# 6. the command line
settings_new, _ = R.parse_arguments(["--iters", "1", "--max-usd", "40", "--updater-max-usd", "4", "--out", os.path.join(work, "x")])
_, (resumed_dir, overrides) = R.parse_arguments(["--resume", experiment, "--max-usd", "55", "--updater-max-usd", "3"])
check(settings_new.max_usd == 40 and settings_new.updater_max_usd == 4 and overrides["max_usd"] == 55
      and overrides["updater_max_usd"] == 3, "--max-usd and --updater-max-usd set the budgets (USD), on a new run and on --resume")
defaults, _ = R.parse_arguments(["--iters", "1", "--out", os.path.join(work, "y")])
check((defaults.solver_model, defaults.solver_effort, defaults.updater_model, defaults.updater_effort)
      == ("claude-haiku-5-5", "low", "claude-haiku-5-5", "low")
      and (defaults.pairs, defaults.early_stop_pairs, defaults.confirm_pairs, defaults.alpha, defaults.patience)
      == (20, 8, 20, 0.10, 20), "defaults: Haiku at low effort everywhere; 20 pairs, early stop at 8, 20 to confirm, "
                                "alpha 0.10, patience 20")
try:
    R.parse_arguments(["--iters", "1", "--pairs", "1"])
    took = True
except SystemExit:
    took = False
check(not took, "a block of one pair is refused")

# 7. the permutation test
check(abs(R.permutation_p_value([1, 2], [3, 4]) - 1 / 6) < 1e-12 and R.permutation_p_value([3, 4], [1, 2]) == 1.0,
      "permutation p-values are exact for small blocks")

shutil.rmtree(work, ignore_errors=True)
print(f"\nall {passed} checks passed")
