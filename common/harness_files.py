"""What counts as a harness's content, and its fingerprint.

A harness is a folder with system.md, method.md and tools/. Caches (__pycache__) and dotfiles (Finder's
.DS_Store) are not content: they are never copied into the solver's sandbox, never shown to the updater,
and never change the fingerprint. Every solver run records the fingerprint of its harness in meta.json
(as harness_sha), so every score traces back to the exact files that produced it.
"""
import hashlib
import os
import shutil

# for shutil.copytree(..., ignore=...): leave out caches and dotfiles
IGNORE_NON_CONTENT = shutil.ignore_patterns("__pycache__", ".*")


def harness_fingerprint(harness_dir):
    """sha256 over every content file's relative path and bytes, first 16 hex digits.
    (The algorithm is unchanged from run_harness.py's harness_hash, so older runs' harness_sha still match.)"""
    harness_dir = os.fspath(harness_dir)
    digest = hashlib.sha256()
    for folder, _, file_names in sorted(os.walk(harness_dir)):
        relative_folder = os.path.relpath(folder, harness_dir)
        hidden_folder = any(part.startswith(".") for part in relative_folder.split(os.sep) if part != ".")
        if "__pycache__" in folder or hidden_folder:
            continue
        for file_name in sorted(file_names):
            if file_name.startswith("."):
                continue
            path = os.path.join(folder, file_name)
            digest.update(os.path.relpath(path, harness_dir).encode())
            with open(path, "rb") as file:
                digest.update(file.read())
    return digest.hexdigest()[:16]


def list_harness_files(harness_dir):
    """Relative paths (forward slashes) of every content file in the harness, sorted."""
    harness_dir = os.fspath(harness_dir)
    paths = []
    for folder, sub_folders, file_names in os.walk(harness_dir):
        sub_folders[:] = sorted(name for name in sub_folders if name != "__pycache__" and not name.startswith("."))
        paths += [os.path.relpath(os.path.join(folder, name), harness_dir).replace(os.sep, "/")
                  for name in sorted(file_names) if not name.startswith(".")]
    return sorted(paths)


def copy_harness(source_dir, target_dir):
    """Copy a harness's content, made writable (the starting harness may be read-only)."""
    shutil.copytree(source_dir, target_dir, ignore=IGNORE_NON_CONTENT)
    for folder, _, file_names in os.walk(target_dir):
        os.chmod(folder, 0o755)
        for file_name in file_names:
            os.chmod(os.path.join(folder, file_name), 0o644)
