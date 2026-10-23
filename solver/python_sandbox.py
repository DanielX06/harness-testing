"""The solver's Python sandbox: a folder on the host that a fresh Docker container mounts for every call.

Each call starts a new container with no network, 2 GB of memory and no host files except the folder, runs
one command, and stops it after CALL_TIME_LIMIT_S seconds (`timeout` runs inside the container, so the
container stops too). Files the command writes stay in the folder for the next call.

When Docker itself fails (the daemon is not running, the image is missing), `docker run` exits with 125 and the
call raises SandboxUnavailable instead of handing Docker's error to the agent as if its code had printed it.

LocalPythonSandbox runs the same commands with a local Python instead, for tests and machines without Docker.
"""
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

from common.harness_files import IGNORE_NON_CONTENT

DOCKER_EXECUTABLE = shutil.which("docker") or os.path.expanduser("~/.docker/bin/docker")
SANDBOX_IMAGE = "harness-v0-py"         # built from solver/Dockerfile: Python 3.12 with numpy, pandas, scipy, sympy
CALL_TIME_LIMIT_S = 120
CONTAINER_MEMORY = "2g"
TIMEOUT_EXIT_CODE = 124                 # what `timeout` returns when it stops the command
TIMED_OUT_MESSAGE = f"ERROR: timed out after {CALL_TIME_LIMIT_S} s"
DOCKER_FAILED_EXIT_CODE = 125           # `docker run` itself failed (or `timeout` did), before the command ran


class SandboxUnavailable(RuntimeError):
    """Docker could not run the command at all. Not the agent's doing: the run stops and can be resumed."""


@dataclass
class SandboxResult:
    output: str                         # stdout then stderr (the end of it, if a limit was given)
    timed_out: bool
    exit_code: int


def fill_sandbox_folder(folder, data_dir, harness_tools_dir, submission_parser_file):
    """A new sandbox folder: the recordings, the harness's tools, and the scorer's parser as tools/submission_parser.py."""
    shutil.copytree(data_dir, folder)
    shutil.copytree(harness_tools_dir, os.path.join(folder, "tools"), ignore=IGNORE_NON_CONTENT)
    shutil.copy(submission_parser_file, os.path.join(folder, "tools", "submission_parser.py"))


class DockerPythonSandbox:
    def __init__(self, folder, image=SANDBOX_IMAGE, time_limit_s=CALL_TIME_LIMIT_S, docker_executable=DOCKER_EXECUTABLE):
        self.folder = os.path.abspath(folder)
        self.image, self.time_limit_s, self.docker_executable = image, time_limit_s, docker_executable

    @classmethod
    def create(cls, folder, data_dir, harness_tools_dir, submission_parser_file):
        fill_sandbox_folder(folder, data_dir, harness_tools_dir, submission_parser_file)
        return cls(folder)

    def command_line(self, *command):
        """The full `docker run` command line for one command in the folder."""
        return [self.docker_executable, "run", "--rm", "--network", "none", "--memory", CONTAINER_MEMORY,
                "-v", f"{self.folder}:/work", "-w", "/work", self.image, "timeout", str(self.time_limit_s), *command]

    def run(self, *command, max_output_chars=None):
        result = _run_with_limit(self.command_line(*command), self.folder, self.time_limit_s, max_output_chars)
        if result.exit_code == DOCKER_FAILED_EXIT_CODE:
            raise SandboxUnavailable(f"docker run failed (exit {DOCKER_FAILED_EXIT_CODE}): {result.output.strip()[-500:]}")
        return result

    def run_python_code(self, code, max_output_chars=None):
        return self.run("python", "-c", code, max_output_chars=max_output_chars)

    def remove(self):
        shutil.rmtree(self.folder, ignore_errors=True)


class LocalPythonSandbox(DockerPythonSandbox):
    """The same folder and calls, run with a local Python (no isolation; for tests and checks only)."""

    def __init__(self, folder, python_executable=None, time_limit_s=CALL_TIME_LIMIT_S):
        super().__init__(folder, time_limit_s=time_limit_s)
        self.python_executable = python_executable or sys.executable

    @classmethod
    def create(cls, folder, data_dir, harness_tools_dir, submission_parser_file, python_executable=None):
        fill_sandbox_folder(folder, data_dir, harness_tools_dir, submission_parser_file)
        return cls(folder, python_executable)

    def command_line(self, *command):
        return [self.python_executable if command[0] == "python" else command[0], *command[1:]]

    def run(self, *command, max_output_chars=None):
        return _run_with_limit(self.command_line(*command), self.folder, self.time_limit_s, max_output_chars)


def _run_with_limit(command_line, working_dir, time_limit_s, max_output_chars):
    try:
        completed = subprocess.run(command_line, cwd=working_dir, capture_output=True, text=True,
                                   timeout=time_limit_s + 30)
    except subprocess.TimeoutExpired:
        return SandboxResult(TIMED_OUT_MESSAGE, True, TIMEOUT_EXIT_CODE)
    if completed.returncode == TIMEOUT_EXIT_CODE:
        return SandboxResult(TIMED_OUT_MESSAGE, True, TIMEOUT_EXIT_CODE)
    output = completed.stdout + completed.stderr
    return SandboxResult(output[-max_output_chars:] if max_output_chars else output, False, completed.returncode)
