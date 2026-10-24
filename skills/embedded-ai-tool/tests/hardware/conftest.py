"""Opt-in hardware fixtures; never start a background heartbeat thread."""
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from embedded_ai_tool.cli import parser, run
from embedded_ai_tool.core import Profile, open_target
from embedded_ai_tool.live import Session


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    outcomes = getattr(item, "hw_outcomes", [])
    outcomes.append(report.outcome)
    item.hw_outcomes = outcomes
    if report.when == "teardown":
        profile = getattr(item, "hw_profile", None)
        print("EAT_HW " + json.dumps({
            "date": datetime.now(UTC).isoformat(),
            "probe_transport": os.environ.get("EAT_HW_PROBE", "unspecified") + "/" +
                (profile.transport if profile else "unconfigured"),
            "test": item.name,
            "result": "failed" if "failed" in outcomes else
                "skipped" if "skipped" in outcomes else "passed",
        }))


@pytest.fixture
def hardware(request):
    path = os.environ.get("EAT_HW_PROFILE")
    if not path:
        pytest.skip("optional: EAT_HW_PROFILE is not set; no hardware accessed")
    profile = Profile(Path(path))
    request.node.hw_profile = profile
    assert os.environ.get("EAT_HW_PROBE"), "Set EAT_HW_PROBE to the processor/probe description"
    target = open_target(profile)
    try:
        session = Session(profile, target)
        assert session.live.stub is not None, "Profile requires live.mailbox"
        assert not session.pins.state.claims, "Release existing claims before hardware acceptance"
        assert not session.live.stub.status()["armed"], "Disarm prior sessions before acceptance"

        def command(*argv):
            args = parser().parse_args(["--profile", str(profile.path), *map(str, argv)])
            args._session = session
            return run(args)

        yield session, command
    finally:
        target.close()


@pytest.fixture
def led(hardware):
    name = os.environ.get("EAT_HW_LED_PIN")
    if not name:
        pytest.skip("optional: EAT_HW_LED_PIN is not set")
    session, command = hardware
    # Plan and validate all accesses before changing hardware.
    session.pins.plan_apply(name, "gpio_out", {"level": 1})
    session.pins.plan_release(name)
    try:
        yield name
    finally:
        # Release even after an assertion failure; never retry an ambiguous transport write.
        if name in session.pins.state.claims and not session.target.closed:
            command("pin", "release", name, "--execute")
