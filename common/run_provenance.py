"""Where a run came from: the git commit of this repository and the Docker image the solver used."""
import os
import subprocess

from common.project_paths import REPOSITORY_ROOT


def git_commit(repository_dir=REPOSITORY_ROOT):
    """`git describe --always --dirty` (a commit id, ending in -dirty if anything was uncommitted), or 'unknown'."""
    try:
        result = subprocess.run(["git", "describe", "--always", "--dirty"], cwd=repository_dir, capture_output=True,
                                text=True, timeout=30, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "unknown"


def docker_image_id(docker_executable, image):
    """The local image id (sha256:...), or None if Docker or the image is not available."""
    try:
        result = subprocess.run([docker_executable, "image", "inspect", "--format", "{{.Id}}", image],
                                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None
