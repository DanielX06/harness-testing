"""Every folder and file the code refers to, relative to the repository root (Harness_testing).

Modules import their paths from here instead of building them, so moving a folder means editing one line.
"""
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

SCORER_DIR = REPOSITORY_ROOT / "scorer"
SOLVER_DIR = REPOSITORY_ROOT / "solver"
RSI_DIR = REPOSITORY_ROOT / "rsi"
TEST_CASES_DIR = REPOSITORY_ROOT / "test_cases"

# every harness a person made (harnesses/<name>/harness/), with a README beside each
HARNESSES_DIR = REPOSITORY_ROOT / "harnesses"
# the starting harness: solver runs and the RSI loop use it unless told otherwise
STARTING_HARNESS_DIR = HARNESSES_DIR / "v0" / "harness"
# results of every study, one folder per study (results/README.md is the index)
RESULTS_DIR = REPOSITORY_ROOT / "results"
# where a new solver run or batch goes unless --out says otherwise; file it into a study folder afterwards
DEFAULT_RUNS_DIR = RESULTS_DIR / "unfiled"
# RSI loop experiments: their own git repository (harness-experiments), ignored by this one
DEFAULT_EXPERIMENTS_DIR = REPOSITORY_ROOT / "rsi_loops"

TASK_PROMPT_FILE = SOLVER_DIR / "task_prompt.md"
SOLVER_RUN_SCRIPT = SOLVER_DIR / "solver_run.py"
SCORER_SCRIPT = SCORER_DIR / "score_submission.py"
# the scorer's parser; the solver gets a copy of it as tools/submission_parser.py
SUBMISSION_PARSER_FILE = SCORER_DIR / "submission_parser.py"
UPDATER_PROMPT_FILE = RSI_DIR / "updater_prompt.md"

MIN_SCORER_CONFIG = SCORER_DIR / "config_min.json"
# config_min.json plus the hidden monitor grid M; used for the RSI loop and every batch compared with it
RSI_SCORER_CONFIG = SCORER_DIR / "config_rsi.json"

# grid A's recordings as the solver receives them, with and without measurement noise
SOLVER_DATA_DIRS = {
    "noisy": TEST_CASES_DIR / "grid_A" / "sandbox_data",
    "clean": TEST_CASES_DIR / "grid_A" / "sandbox_data_clean",
}
