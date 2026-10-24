"""Real target acceptance. An explicit local profile opts into RAM/register writes."""
import os
import time

import pytest


def test_stub_status_alive(hardware):
    session, command = hardware
    status = command("stub", "status")
    assert status["magic_ok"]
    session.live.stub.require_alive()


def test_uid_identity(hardware):
    _, command = hardware
    assert command("identity")["matches"]


def test_led_apply_release(hardware, led):
    session, command = hardware
    applied = command("pin", "apply", led, "gpio_out", "--param", "level=1", "--execute")
    assert session.pins.state.claims[led]["status"] == "applied"
    assert any(s.get("after") is not None for s in applied["steps"])
    command("pin", "release", led, "--execute")
    assert led not in session.pins.state.claims


def test_serial_round_trip(hardware):
    session, command = hardware
    if session.profile.transport != "serial":
        pytest.skip("optional: serial round-trip requires a serial profile")
    # INFO was exchanged on connect; READ/INCREMENT_IF/READ proves a guarded round-trip.
    before = command("stub", "status")["host_heartbeat"]
    assert session.live.stub.heartbeat()
    after = command("stub", "status")["host_heartbeat"]
    assert after == (before + 1) & 0xFFFFFFFF


def test_ram_load_run(hardware):
    _, command = hardware
    snippet = os.environ.get("EAT_HW_SNIPPET")
    if not snippet:
        pytest.skip("optional: EAT_HW_SNIPPET is not set; user-supplied code required")
    # Contract: entry at byte zero, no arguments, returns uint32_t 42 promptly.
    loaded = command("ram", "load", "--file", snippet, "--execute")
    assert loaded["readback_verified"]
    result = command("ram", "run", "--timeout", "2", "--execute")
    assert result["status"] == "ok"
    assert result["result"] == 42


def test_deadman_safe_readback(hardware, led):
    session, command = hardware
    stub = session.live.stub
    assert stub.deadman, "Acceptance requires live.deadman=true"
    stub.require_alive()
    # Validate that each safe register can be read without side effects before applying LED.
    from embedded_ai_tool.live import safe_entries

    rows = safe_entries(session.pins.plan_release(led)["steps"])
    assert rows, "LED requires a nonempty safe-state recipe"
    for address, width, _, _ in rows:
        session.live.peek(address, width=width)
    command("pin", "apply", led, "gpio_out", "--param", "level=1", "--execute")
    status = command("stub", "status")
    assert status["armed"] and status["safe_count"] > 0
    assert any(int(session.live.peek(address, width=width)["values"][0], 0) & mask != value & mask
               for address, width, mask, value in rows), "Active and safe states must differ"
    assert stub.heartbeat()
    # No serve process, heartbeat worker, keepalive, or pin command during this interval.
    time.sleep(stub.timeout_ms / 1000 + max(0.25, stub.timeout_ms / 2000))
    expired = command("stub", "status")
    assert expired["deadman_fired"]
    assert expired["deadman_count"] == (status["deadman_count"] + 1) & 0xFFFFFFFF
    for address, width, mask, value in rows:
        actual = int(command("peek", hex(address), "--width", width)["values"][0], 0)
        assert actual & mask == value & mask, f"safe readback mismatch at {address:#x}"
    # led fixture releases only AFTER the measured dead-man/readback assertions.
