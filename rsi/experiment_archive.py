"""Packs the bulky per-run files of an RSI experiment into one archive, and unpacks them again.

    python rsi/experiment_archive.py rsi/experiments/<experiment>              # pack (by hand: after a killed loop)
    python rsi/experiment_archive.py rsi/experiments/<experiment> --restore    # unpack

rsi_experiment.py packs an experiment itself when its loop ends on its own (--iters, --patience or --max-usd), and
unpacks it when --resume finds an archive, before anything reads the runs. A loop stopped by Ctrl-C, a signal or
exit code 3 is left unpacked, since it is usually resumed soon; pack it by hand once you are done with it. Packing
by hand is safe at any point the loop is not running: --resume unpacks first and the stopped runs carry on.

Packed, from every run folder under runs/, at its path relative to the experiment folder:
  transcript.json, checkpoint.json      the updater reads transcripts while the loop runs, so they stay unpacked
                                        until it stops
  *_partial.npz, *.debug.log            score/andes/: the trajectory and the DEBUG tail of each failed
                                        closed-loop task, for classifying failures
  sandbox/ of a run that never finished only what is not an unchanged copy of the run's data folder (meta.json
                                        "data"): the tools, the agent's own files, any recording it edited. The
                                        unchanged recordings are dropped and copied back from the data folder on
                                        --restore. A finished run has no sandbox (solver_run.py removes it).
Everything else stays: meta.json, submission.json, final.md, score/public.json and private.json, the ANDES INFO
logs, runs/<block>/logs/, all of candidates/ and the experiment-level files. That is what the experiments
repository commits.

archive.tar.xz holds the files. archive_manifest.json beside it lists each one with its size and sha256, and each
removed sandbox with its data folder and that folder's fingerprint. Packing writes the archive to a temporary file,
reads every file back out of it and checks its hash, and only then removes the originals, so a failure at any step
leaves the run files where they were. It first checks that it can remove everything it packs: on Linux the solver's
Docker container writes into the sandbox as root, and those folders need a `sudo chown` first. A sandbox's
__pycache__ folders are removed, not packed. An experiment has one archive: packing again unpacks the old one first.
Restoring checks every hash as it writes, then removes the archive and the manifest.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the repository root

ARCHIVE_NAME = "archive.tar.xz"
MANIFEST_NAME = "archive_manifest.json"
PACKED_RUN_FILES = ("transcript.json", "checkpoint.json")       # at the top of a run folder
PACKED_SUFFIXES = ("_partial.npz", ".debug.log")                # anywhere in a run folder outside its sandbox
CHUNK_BYTES = 1 << 20


class ArchiveError(RuntimeError):
    """The archive or the folder is not in the state packing or restoring needs; nothing was removed."""


def _sha256(file):
    digest = hashlib.sha256()
    for chunk in iter(lambda: file.read(CHUNK_BYTES), b""):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_of_file(path):
    with open(path, "rb") as file:
        return _sha256(file)


def _read_json_or_none(path):
    try:
        with open(path) as file:
            return json.load(file)
    except (OSError, ValueError):
        return None


def _write_json_atomically(path, content):
    temporary = path + ".tmp"
    with open(temporary, "w") as file:
        json.dump(content, file, indent=1)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def _inside(root, relative):
    """root/relative, refusing a path that is absolute or leaves root."""
    path = os.path.normpath(os.path.join(root, relative))
    if os.path.isabs(relative) or os.path.commonpath([root, path]) != root:
        raise ArchiveError(f"{relative!r} is not a path inside {root}")
    return path


def run_folders(experiment_dir):
    """Every run folder (runs/<block>/<run>/ with a meta.json), in order."""
    runs_dir = os.path.join(experiment_dir, "runs")
    folders = []
    for block in sorted(os.listdir(runs_dir)) if os.path.isdir(runs_dir) else []:
        block_dir = os.path.join(runs_dir, block)
        if os.path.isdir(block_dir):
            folders += [os.path.join(block_dir, name) for name in sorted(os.listdir(block_dir))
                        if os.path.isfile(os.path.join(block_dir, name, "meta.json"))]
    return folders


class DataFolders:
    """Each data folder's files with their sizes and hashes, read once per folder."""

    def __init__(self):
        self._files = {}

    def files(self, data_dir):
        """{path inside data_dir: (bytes, sha256)}, or None if data_dir is not a folder on this machine."""
        if data_dir not in self._files:
            index = None
            if data_dir and os.path.isdir(data_dir):
                index = {}
                for root, dirs, names in os.walk(data_dir):
                    dirs.sort()
                    for name in sorted(names):
                        path = os.path.join(root, name)
                        if os.path.isfile(path):
                            index[os.path.relpath(path, data_dir)] = (os.path.getsize(path), sha256_of_file(path))
            self._files[data_dir] = index
        return self._files[data_dir]

    def fingerprint(self, data_dir):
        files = self.files(data_dir)
        if files is None:
            return None
        digest = hashlib.sha256()
        for relative in sorted(files):
            digest.update(f"{relative}\0{files[relative][0]}\0{files[relative][1]}\n".encode())
        return digest.hexdigest()[:16]


def files_to_pack(experiment_dir, data_folders):
    """(paths, sandboxes). paths: every file to pack, relative to experiment_dir. sandboxes: {run folder relative to
    experiment_dir: what restoring needs to rebuild its sandbox} for every sandbox packing removes."""
    paths, sandboxes = [], {}

    def relative(path):
        return os.path.relpath(path, experiment_dir)

    for run_dir in run_folders(experiment_dir):
        for root, dirs, names in os.walk(run_dir):
            if root == run_dir and "sandbox" in dirs:
                dirs.remove("sandbox")
            dirs.sort()
            for name in sorted(names):
                path = os.path.join(root, name)
                if os.path.isfile(path) and ((root == run_dir and name in PACKED_RUN_FILES)
                                             or name.endswith(PACKED_SUFFIXES)):
                    paths.append(relative(path))
        sandbox_dir = os.path.join(run_dir, "sandbox")
        if not os.path.isdir(sandbox_dir):
            continue
        data_dir = (_read_json_or_none(os.path.join(run_dir, "meta.json")) or {}).get("data")
        inputs = data_folders.files(data_dir) or {}
        dropped = 0
        for root, dirs, names in os.walk(sandbox_dir):
            dirs[:] = sorted(name for name in dirs if name != "__pycache__")     # bytecode: removed, not packed
            for name in sorted(names):
                path = os.path.join(root, name)
                if not os.path.isfile(path):
                    continue
                known = inputs.get(os.path.relpath(path, sandbox_dir))
                if known and known[0] == os.path.getsize(path) and known[1] == sha256_of_file(path):
                    dropped += 1
                else:
                    paths.append(relative(path))
        sandboxes[relative(run_dir)] = {"data": data_dir if dropped else None,
                                        "data_fingerprint": data_folders.fingerprint(data_dir) if dropped else None,
                                        "dropped_inputs": dropped}
    return paths, sandboxes


def check_removable(experiment_dir, paths, sandboxes):
    """ArchiveError, before anything is written, if this user cannot remove a packed file or a sandbox. On Linux the
    solver's Docker container writes into the sandbox as root, and a root-owned folder cannot be emptied."""
    folders = {os.path.dirname(os.path.join(experiment_dir, path)) for path in paths}
    for run in sandboxes:
        folders.add(os.path.join(experiment_dir, run))
        for root, _, _ in os.walk(os.path.join(experiment_dir, run, "sandbox")):
            folders.add(root)
    blocked = sorted(folder for folder in folders if not os.access(folder, os.W_OK | os.X_OK))
    if blocked:
        owner = os.stat(blocked[0]).st_uid
        raise ArchiveError(f"cannot remove files in {len(blocked)} folders, {blocked[0]} (owner uid {owner}) first; "
                           "nothing was changed. Files the solver's Docker container wrote are owned by root: run "
                           f"`sudo chown -R $(id -u):$(id -g) {experiment_dir}` and pack again")


def check_archive(archive_path, entries):
    """Read every member of archive_path back and check it against entries; ArchiveError on any difference."""
    expected, seen = {entry["path"]: entry for entry in entries}, set()
    with tarfile.open(archive_path, "r:xz") as tar:
        for member in tar:
            entry = expected.get(member.name)
            if entry is None or not member.isfile() or member.name in seen:
                raise ArchiveError(f"{archive_path}: unexpected member {member.name}")
            if _sha256(tar.extractfile(member)) != entry["sha256"]:
                raise ArchiveError(f"{archive_path}: {member.name} does not match its original")
            seen.add(member.name)
    missing = sorted(set(expected) - seen)
    if missing:
        raise ArchiveError(f"{archive_path} is missing {len(missing)} files, {missing[0]} first")


def _megabytes(count):
    return f"{count / 1e6:.1f} MB"


def archive(experiment_dir, log=print):
    """Pack experiment_dir's bulky run files (see the module docstring). Returns the manifest, or None if there was
    nothing to pack. The caller makes sure no loop is using the folder."""
    experiment_dir = os.path.abspath(experiment_dir)
    archive_path = os.path.join(experiment_dir, ARCHIVE_NAME)
    if os.path.exists(archive_path):
        restore(experiment_dir, log)            # one archive per experiment: the old one goes into the new one
    data_folders = DataFolders()
    paths, sandboxes = files_to_pack(experiment_dir, data_folders)
    if not paths and not sandboxes:
        log("archive: nothing to pack")
        return None
    check_removable(experiment_dir, paths, sandboxes)
    entries = [{"path": path, "bytes": os.path.getsize(os.path.join(experiment_dir, path)),
                "sha256": sha256_of_file(os.path.join(experiment_dir, path))} for path in paths]
    temporary = archive_path + ".tmp"
    try:
        with tarfile.open(temporary, "w:xz", preset=6) as tar:
            for entry in entries:
                tar.add(os.path.join(experiment_dir, entry["path"]), arcname=entry["path"], recursive=False)
        check_archive(temporary, entries)
    except BaseException:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    manifest = {"created_at": time.strftime("%Y-%m-%d %H:%M:%S"), "files": entries, "sandboxes": sandboxes,
                "bytes": sum(entry["bytes"] for entry in entries), "archive_bytes": os.path.getsize(temporary)}
    _write_json_atomically(os.path.join(experiment_dir, MANIFEST_NAME), manifest)    # before the archive is in place
    os.replace(temporary, archive_path)
    for entry in entries:
        os.remove(os.path.join(experiment_dir, entry["path"]))
    for run in sandboxes:
        shutil.rmtree(os.path.join(experiment_dir, run, "sandbox"))
    dropped = sum(sandbox["dropped_inputs"] for sandbox in sandboxes.values())
    log(f"archive: packed {len(entries)} files ({_megabytes(manifest['bytes'])}) into {ARCHIVE_NAME} "
        f"({_megabytes(manifest['archive_bytes'])}); removed {len(sandboxes)} sandboxes"
        + (f" and {dropped} unchanged recordings in them (copied back on restore)" if dropped else ""))
    return manifest


def restore(experiment_dir, log=print):
    """Unpack experiment_dir's archive, if it has one, and remove it. Returns True if there was one to unpack."""
    experiment_dir = os.path.abspath(experiment_dir)
    archive_path = os.path.join(experiment_dir, ARCHIVE_NAME)
    manifest_path = os.path.join(experiment_dir, MANIFEST_NAME)
    if not os.path.exists(archive_path):
        return False
    manifest = _read_json_or_none(manifest_path)
    if manifest is None:
        raise ArchiveError(f"{archive_path} has no readable {MANIFEST_NAME} beside it; unpack it by hand")
    data_folders, rebuilt = DataFolders(), []
    for run, sandbox in sorted(manifest.get("sandboxes", {}).items()):
        sandbox_dir = _inside(experiment_dir, os.path.join(run, "sandbox"))
        rebuilt.append(sandbox_dir + os.sep)
        data_dir = sandbox.get("data")
        if not sandbox.get("dropped_inputs"):
            continue
        fingerprint = data_folders.fingerprint(data_dir)
        if fingerprint is None:
            log(f"archive: warning: {data_dir} is not on this machine; {run}'s sandbox is restored without its "
                "recordings, so --resume cannot carry that run on")
            continue
        if fingerprint != sandbox.get("data_fingerprint"):
            log(f"archive: warning: {data_dir} has changed since {run} was packed; its sandbox gets today's copy")
        shutil.copytree(data_dir, sandbox_dir, dirs_exist_ok=True)
    expected, seen, restored = {entry["path"]: entry for entry in manifest["files"]}, set(), 0
    with tarfile.open(archive_path, "r:xz") as tar:
        for member in tar:
            entry = expected.get(member.name)
            if entry is None or not member.isfile() or member.name in seen:
                raise ArchiveError(f"{archive_path}: unexpected member {member.name}")
            seen.add(member.name)
            destination = _inside(experiment_dir, member.name)
            if os.path.exists(destination):
                if sha256_of_file(destination) == entry["sha256"]:
                    continue                    # left by an earlier restore or pack that stopped part way
                if not any(destination.startswith(prefix) for prefix in rebuilt):
                    raise ArchiveError(f"{destination} exists and differs from its archived copy; move it aside "
                                       "and restore again")
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            temporary = destination + ".tmp"
            source = tar.extractfile(member)
            digest = hashlib.sha256()
            with open(temporary, "wb") as file:
                for chunk in iter(lambda: source.read(CHUNK_BYTES), b""):
                    digest.update(chunk)
                    file.write(chunk)
            if digest.hexdigest() != entry["sha256"]:
                os.remove(temporary)
                raise ArchiveError(f"{archive_path}: {member.name} does not match its manifest entry")
            os.utime(temporary, (member.mtime, member.mtime))
            os.replace(temporary, destination)
            restored += 1
    missing = sorted(set(expected) - seen)
    if missing:
        raise ArchiveError(f"{archive_path} is missing {len(missing)} files its manifest lists, {missing[0]} first")
    os.remove(archive_path)
    os.remove(manifest_path)
    log(f"archive: restored {restored} files and {len(manifest.get('sandboxes', {}))} sandboxes from {ARCHIVE_NAME}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("experiment", help="the experiment folder")
    parser.add_argument("--restore", action="store_true", help="unpack instead of pack")
    options = parser.parse_args(argv)
    experiment_dir = os.path.abspath(options.experiment)
    if not os.path.isfile(os.path.join(experiment_dir, "config.json")):
        raise SystemExit(f"{experiment_dir} is not an experiment folder (no config.json)")
    from rsi.rsi_experiment import LoopLock     # here, not at the top: rsi_experiment imports this module
    with LoopLock(os.path.join(experiment_dir, "loop.lock")):
        try:
            if options.restore:
                if not restore(experiment_dir):
                    print(f"nothing to restore: no {ARCHIVE_NAME} in {experiment_dir}")
            else:
                archive(experiment_dir)
        except ArchiveError as error:
            raise SystemExit(f"archive: {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
