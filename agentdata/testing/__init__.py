"""Testing support: test runner detection, execution, process tree management, and result normalization."""
from .detect import detect_all, detect_runner, TestRunnerInfo
from .kill import kill_tree
from .runner import run_tests

__all__ = ["detect_runner", "detect_all", "TestRunnerInfo", "run_tests", "kill_tree"]
