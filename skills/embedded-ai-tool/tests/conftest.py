"""Fail on unexpected skips, including unittest and collection-time skips."""
import os

import pytest

_unexpected_skips = []
_OPENOCD_TESTS = {
    "test_real_openocd_interpreter_without_hardware",
    "test_rpc_wrapper_preserves_unbalanced_braces_and_substitutions",
}


def pytest_sessionstart(session):
    _unexpected_skips.clear()


def pytest_collection_modifyitems(items):
    # An explicit opt-out keeps the Windows job independent of OpenOCD.
    if os.environ.get("EAT_OPENOCD_TESTS") == "0":
        marker = pytest.mark.skip(reason="optional: EAT_OPENOCD_TESTS=0")
        for item in items:
            if item.path.name == "test_tool.py" and item.name in _OPENOCD_TESTS:
                item.add_marker(marker)


def _check_skip(report):
    if report.skipped:
        reason = report.longrepr
        if isinstance(reason, tuple):
            reason = reason[2]
        reason = str(reason).removeprefix("Skipped: ")
        if not reason.startswith("optional:"):
            _unexpected_skips.append(f"{report.nodeid}: {reason}")


pytest_runtest_logreport = _check_skip
pytest_collectreport = _check_skip


def pytest_sessionfinish(session):
    if _unexpected_skips and session.exitstatus in {pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED}:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter):
    if _unexpected_skips:
        terminalreporter.write_sep("=", "Unexpected skips (suite failed)", red=True)
        for skip in _unexpected_skips:
            terminalreporter.write_line(skip)
