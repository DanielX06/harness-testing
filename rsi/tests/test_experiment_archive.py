"""Checks of experiment_archive.py on a small made-up experiment folder: what is packed, what is deleted and what
stays, a pack and restore that gives back every packed byte, an older archive that still holds the scorer's failure
files, a leftover sandbox rebuilt from its data folder, and the failures that must
leave everything where it was. No API call, no Docker, no ANDES.

    python rsi/tests/test_experiment_archive.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True
REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPOSITORY_ROOT)
from rsi import experiment_archive as A  # noqa: E402

work = tempfile.mkdtemp(prefix="experiment_archive_test_")
passed = 0
messages = []


def check(condition, description):
    global passed
    if not condition:
        raise AssertionError(description)
    passed += 1
    print("ok:", description)


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(content, bytes) else "w") as file:
        file.write(content)


def snapshot(folder):
    """{path relative to folder: sha256} of every file, the archive and its manifest left out."""
    files = {}
    for root, _, names in os.walk(folder):
        for name in names:
            path = os.path.join(root, name)
            relative = os.path.relpath(path, folder)
            if relative not in (A.ARCHIVE_NAME, A.MANIFEST_NAME):
                files[relative] = A.sha256_of_file(path)
    return files


def make_experiment(name, data_dir):
    experiment = os.path.join(work, name)
    write(os.path.join(experiment, "config.json"), "{}")
    write(os.path.join(experiment, "summary.md"), "# summary\n")
    write(os.path.join(experiment, "candidates", "h001", "transcript.json"), '{"updater": true}')
    finished = os.path.join(experiment, "runs", "h000_baseline", "r1")
    write(os.path.join(finished, "meta.json"), json.dumps({"status": "finished", "data": data_dir}))
    write(os.path.join(finished, "transcript.json"), json.dumps({"messages": ["step"] * 2000}))
    write(os.path.join(finished, "submission.json"), "{}")
    write(os.path.join(finished, "final.md"), "done\n")
    write(os.path.join(finished, "score", "public.json"), '{"score": 0.8}')
    write(os.path.join(finished, "score", "andes", "grid_B__B_vref.log"), "INFO\n")
    write(os.path.join(finished, "score", "andes", "grid_B__B_vref_partial.npz"), os.urandom(5000))
    write(os.path.join(finished, "score", "andes", "grid_B__B_vref.debug.log"), "DEBUG\n" * 500)
    write(os.path.join(experiment, "runs", "h000_baseline", "logs", "run1.log"), "solver output\n")
    stopped = os.path.join(experiment, "runs", "h001_test", "r2")
    write(os.path.join(stopped, "meta.json"), json.dumps({"status": "stopped", "data": data_dir}))
    write(os.path.join(stopped, "checkpoint.json"), '{"messages": []}')
    write(os.path.join(stopped, "transcript.json"), '{"messages": []}')
    shutil.copytree(data_dir, os.path.join(stopped, "sandbox"))
    write(os.path.join(stopped, "sandbox", "tools", "helper.py"), "print('tool')\n")
    write(os.path.join(stopped, "sandbox", "submission.json"), '{"agent": 1}')
    write(os.path.join(stopped, "sandbox", "train", "a.csv"), "edited by the agent\n")
    write(os.path.join(stopped, "sandbox", "tools", "__pycache__", "helper.cpython-312.pyc"), b"bytecode")
    return experiment


data_dir = os.path.join(work, "data")
write(os.path.join(data_dir, "dataset.json"), "{}")
write(os.path.join(data_dir, "train", "a.csv"), "t,p\n" + "0,1\n" * 1000)
write(os.path.join(data_dir, "train", "b.csv"), "t,q\n" + "0,2\n" * 1000)
write(os.path.join(data_dir, "val", "c.csv"), "t,v\n" + "0,3\n" * 1000)

# 1. packing: what goes in, what stays
experiment = make_experiment("main", data_dir)
before = snapshot(experiment)
manifest = A.archive(experiment, messages.append)
packed = {entry["path"] for entry in manifest["files"]}
check(os.path.exists(os.path.join(experiment, A.ARCHIVE_NAME)) and os.path.exists(os.path.join(experiment, A.MANIFEST_NAME)),
      "packing writes archive.tar.xz and archive_manifest.json")
DELETED = {"runs/h000_baseline/r1/score/andes/grid_B__B_vref_partial.npz",
           "runs/h000_baseline/r1/score/andes/grid_B__B_vref.debug.log"}
check(packed == {"runs/h000_baseline/r1/transcript.json", "runs/h001_test/r2/checkpoint.json",
                 "runs/h001_test/r2/transcript.json", "runs/h001_test/r2/sandbox/tools/helper.py",
                 "runs/h001_test/r2/sandbox/submission.json", "runs/h001_test/r2/sandbox/train/a.csv"},
      "packed: transcripts, checkpoints, and a sandbox's own and edited files")
check(not packed & DELETED and all(not os.path.exists(os.path.join(experiment, path)) for path in DELETED)
      and manifest["deleted_files"] == 2 and manifest["deleted_bytes"] == 5000 + len("DEBUG\n" * 500)
      and any("deleted 2 scorer failure files" in message for message in messages),
      "the scorer's failure trajectories and DEBUG tails are deleted, not packed, and the manifest counts them")
check(not any("__pycache__" in path for path in packed), "a sandbox's __pycache__ is not packed")
check(manifest["sandboxes"]["runs/h001_test/r2"]["dropped_inputs"] == 3,
      "a sandbox's unchanged recordings are dropped, an edited one is packed")
check(all(not os.path.exists(os.path.join(experiment, path)) for path in packed)
      and not os.path.exists(os.path.join(experiment, "runs", "h001_test", "r2", "sandbox")),
      "the packed files and the leftover sandbox are removed")
kept = set(snapshot(experiment))
check(kept == set(before) - packed - DELETED - {"runs/h001_test/r2/sandbox/dataset.json", "runs/h001_test/r2/sandbox/train/b.csv",
                                      "runs/h001_test/r2/sandbox/val/c.csv",
                                      "runs/h001_test/r2/sandbox/tools/__pycache__/helper.cpython-312.pyc"},
      "everything else stays: meta, submission, final.md, scores, INFO logs, solver logs, candidates/, summary")
check(not os.path.exists(os.path.join(experiment, A.ARCHIVE_NAME + ".tmp")), "no temporary archive is left behind")

# 2. restoring gives back every byte
pycache = "runs/h001_test/r2/sandbox/tools/__pycache__/helper.cpython-312.pyc"
before.pop(pycache)
for path in DELETED:
    before.pop(path)
check(A.restore(experiment, messages.append) and snapshot(experiment) == before,
      "restoring gives back every packed file, the sandbox's recordings copied from its data folder")
check(not os.path.exists(os.path.join(experiment, A.ARCHIVE_NAME)) and not os.path.exists(os.path.join(experiment, A.MANIFEST_NAME)),
      "restoring removes the archive and its manifest")
check(A.restore(experiment, messages.append) is False, "restoring a folder with no archive does nothing")

# 3. packing twice: the old archive goes into the new one
A.archive(experiment, messages.append)
write(os.path.join(experiment, "runs", "h002_test", "r3", "meta.json"), '{"status": "finished"}')
write(os.path.join(experiment, "runs", "h002_test", "r3", "transcript.json"), '{"later": true}')
before_second = dict(before, **{"runs/h002_test/r3/meta.json": None, "runs/h002_test/r3/transcript.json": None})
second = A.archive(experiment, messages.append)
check(len(second["files"]) == len(manifest["files"]) + 1, "packing again folds the old archive into the new one")
A.restore(experiment, messages.append)
after_second = snapshot(experiment)
check(set(after_second) == set(before_second) and all(after_second[path] == before[path] for path in before),
      "and restoring that one gives back both packs")

# 4. a failed check leaves everything where it was
before_failure = snapshot(experiment)
original_check = A.check_archive
A.check_archive = lambda path, entries: (_ for _ in ()).throw(A.ArchiveError("simulated mismatch"))
try:
    A.archive(experiment, messages.append)
    raised = False
except A.ArchiveError:
    raised = True
A.check_archive = original_check
check(raised and snapshot(experiment) == before_failure and not os.listdir(experiment).count(A.ARCHIVE_NAME + ".tmp")
      and not os.path.exists(os.path.join(experiment, A.ARCHIVE_NAME)),
      "an archive that fails its read-back check is deleted and nothing is removed")

# 5. restoring never overwrites a different file outside a rebuilt sandbox
A.archive(experiment, messages.append)
clobbered = os.path.join(experiment, "runs", "h000_baseline", "r1", "transcript.json")
write(clobbered, "a different transcript")
try:
    A.restore(experiment, messages.append)
    refused = False
except A.ArchiveError:
    refused = True
check(refused and os.path.exists(os.path.join(experiment, A.ARCHIVE_NAME)),
      "restoring refuses to overwrite a file that differs from its archived copy, and keeps the archive")
os.remove(clobbered)
check(A.restore(experiment, messages.append) and snapshot(experiment) == after_second,
      "once that file is moved aside, restoring finishes, including files a stopped restore had already written")

# 6. a restore where the data folder is gone still gives back the archived files
moved = make_experiment("moved", data_dir)
moved_before = snapshot(moved)
A.archive(moved, messages.append)
shutil.move(data_dir, data_dir + "_elsewhere")
messages.clear()
A.restore(moved, messages.append)
shutil.move(data_dir + "_elsewhere", data_dir)
moved_after = snapshot(moved)
check(any("is not on this machine" in message for message in messages)
      and all(moved_after.get(path) == moved_before[path] for path in moved_before
              if not path.endswith(("dataset.json", "b.csv", "c.csv", ".pyc") + A.DELETED_SUFFIXES)),
      "without its data folder, a sandbox is restored without its recordings, with a warning")

# 7. an archive made before the failure files were deleted gives them back on restore; packing again deletes them
legacy = make_experiment("legacy", data_dir)
legacy_before = snapshot(legacy)
current_files_to_pack = A.files_to_pack
A.files_to_pack = lambda folder, data: (lambda found: (found[0] + found[2], found[1], []))(current_files_to_pack(folder, data))
old_manifest = A.archive(legacy, messages.append)                  # packs them, as the archiver used to
A.files_to_pack = current_files_to_pack
check(DELETED <= {entry["path"] for entry in old_manifest["files"]}, "(setup) the old-style archive holds the failure files")
A.restore(legacy, messages.append)
check(all(snapshot(legacy).get(path) == legacy_before[path] for path in DELETED),
      "restoring an old-style archive gives the failure files back")
A.archive(legacy, messages.append)
again = json.load(open(os.path.join(legacy, A.MANIFEST_NAME)))
check(not DELETED & {entry["path"] for entry in again["files"]}
      and all(not os.path.exists(os.path.join(legacy, path)) for path in DELETED),
      "packing an old-style archive again deletes them instead of packing them")
cleanup_only = make_experiment("cleanup_only", data_dir)
for path in ("runs/h000_baseline/r1/transcript.json", "runs/h001_test/r2/checkpoint.json", "runs/h001_test/r2/transcript.json"):
    os.remove(os.path.join(cleanup_only, path))
shutil.rmtree(os.path.join(cleanup_only, "runs", "h001_test", "r2", "sandbox"))
check(A.archive(cleanup_only, messages.append) is None and not os.path.exists(os.path.join(cleanup_only, A.ARCHIVE_NAME))
      and all(not os.path.exists(os.path.join(cleanup_only, path)) for path in DELETED),
      "with nothing to pack, the failure files are still deleted and no archive is written")

# 8. a folder this user cannot empty (root-owned, as the Docker container leaves it on Linux) stops packing first
locked = make_experiment("locked", data_dir)
locked_tools = os.path.join(locked, "runs", "h001_test", "r2", "sandbox", "tools")
if os.geteuid() != 0:
    locked_before = snapshot(locked)
    os.chmod(locked_tools, 0o555)
    try:
        A.archive(locked, messages.append)
        stopped_early = False
    except A.ArchiveError as error:
        stopped_early = "sudo chown" in str(error)
    os.chmod(locked_tools, 0o755)
    check(stopped_early and snapshot(locked) == locked_before and not os.path.exists(os.path.join(locked, A.ARCHIVE_NAME)),
          "a sandbox folder this user cannot empty stops packing before anything is written, with the chown to run")

# 9. nothing to pack, and paths outside the folder
empty = os.path.join(work, "empty")
write(os.path.join(empty, "config.json"), "{}")
check(A.archive(empty, messages.append) is None and not os.path.exists(os.path.join(empty, A.ARCHIVE_NAME)),
      "a folder with nothing to pack gets no archive")
try:
    A._inside(experiment, "../outside.json")
    escaped = True
except A.ArchiveError:
    escaped = False
check(not escaped, "a member path that leaves the experiment folder is refused")

shutil.rmtree(work, ignore_errors=True)
print(f"\nall {passed} checks passed")
