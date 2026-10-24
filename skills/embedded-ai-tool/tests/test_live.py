"""Host-side tests for live RAM-only control. A fake RPC interprets the generated Tcl; this is
not a substitute for qualification on a real board and real OpenOCD."""
import argparse
import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from embedded_ai_tool import cli as cli_module
from embedded_ai_tool import core as core_module
from embedded_ai_tool.cli import parser, run, serve_request
from embedded_ai_tool.core import RPC, OpenOcdTarget, Profile
from embedded_ai_tool.live import (
    MAGIC,
    WORD,
    Live,
    Pins,
    Session,
    StepFailed,
    compile_steps,
    evaluate,
)
from embedded_ai_tool.svd import Device as SvdDevice

EXAMPLES = Path(__file__).resolve().parents[1] / "references" / "examples"
UID_ADDRESS, UID = 0x50FF0000, bytes.fromhex("a1b2c3d4")
GPIO, CLOCK, TIMER = 0x50000000, 0x50020000, 0x50010000
BOX = 0x20000000
READ = re.compile(r"read_memory (\d+) (\d+) (\d+)$")
WRITE = re.compile(r"write_memory (\d+) (\d+) \{([\d ]*)\}$")
RMW = re.compile(r"set __v \[lindex \[read_memory (\d+) (\d+) 1\] 0\]; write_memory \1 \2 "
                 r"\[expr \{\(\$__v & (\d+)\) \| (\d+)\}\]; set __v$")
BEAT = re.compile(r"if \{\[lindex \[read_memory (\d+) 32 1\] 0\] == (\d+)\} \{write_memory (\d+) 32 "
                  r"\[expr \{\(\[lindex \[read_memory \3 32 1\] 0\] \+ 1\) & 0xffffffff\}\]; set __hb 1\} "
                  r"else \{set __hb 0\}$")


class FakeRPC:
    """Interprets exactly the Tcl shapes live.py generates, and simulates the stub mailbox."""

    closed = False

    def __init__(self, stub=True):
        self.mem, self.stuck, self.scripts, self.fail = {}, set(), [], None
        self.stub_alive, self.complete_calls, self.fault = stub, True, False
        for i, byte in enumerate(UID):
            self.mem[UID_ADDRESS + i] = byte
        if stub:
            self.put(BOX + 4 * WORD["magic"], 32, MAGIC)
            self.put(BOX + 4 * WORD["version"], 32, 1)

    def get(self, address, width=32):
        return int.from_bytes(bytes(self.mem.get(address + i, 0) for i in range(width // 8)), "little")

    def put(self, address, width, value):
        for i, byte in enumerate(value.to_bytes(width // 8, "little")):
            self.mem[address + i] = byte

    def store(self, address, width, value):
        if address not in self.stuck:
            self.put(address, width, value)

    def call(self, script):
        self.scripts.append(script)
        if self.fail:
            self.fail(script)
        _, guard, body = script.partition("{error IDENTITY_MISMATCH}}; ")
        if not guard:
            raise AssertionError(f"mutation/read without identity guard: {script}")
        if bytes(self.mem.get(UID_ADDRESS + i, 0) for i in range(4)) != UID:
            raise ValueError("OpenOCD: ERROR\nIDENTITY_MISMATCH")
        if match := RMW.match(body):
            address, width, keep, value = map(int, match.groups())
            old = self.get(address, width)
            self.store(address, width, old & keep | value)
            return str(old)
        if match := BEAT.match(body):
            base, magic, address = map(int, match.groups())
            if self.get(base) != magic:
                return "0"
            self.put(address, 32, (self.get(address) + 1) & 0xFFFFFFFF)
            return "1"
        if match := READ.match(body):
            address, width, count = map(int, match.groups())
            if self.stub_alive and address == BOX and count == 18:
                beat = BOX + 4 * WORD["stub_hb"]
                self.put(beat, 32, self.get(beat) + 1)
            return " ".join(f"{self.get(address + i * width // 8, width):#x}" for i in range(count))
        if match := WRITE.match(body):
            address, width = int(match.group(1)), int(match.group(2))
            for i, value in enumerate(int(v) for v in match.group(3).split()):
                self.store(address + i * width // 8, width, value)
            if address == BOX + 4 * WORD["call_seq"] and self.complete_calls:
                self.put(BOX + 4 * WORD["done_seq"], 32, int(match.group(3)))
                self.put(BOX + 4 * WORD["status"], 32, 3 if self.fault else 2)
                self.put(BOX + 4 * WORD["result"], 32, 42)
            return ""
        raise AssertionError(f"unhandled script: {body}")

    def close(self):
        pass


class LiveCase(unittest.TestCase):
    def setUp(self):
        sleep = patch("embedded_ai_tool.live.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ("example-board.json", "example-mcu.json"):
            shutil.copy(EXAMPLES / name, self.root / name)
        self.path = self.root / "example-board.json"
        self.rpc = FakeRPC()

    def edit(self, change):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        change(data)
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def live(self, rpc=None):
        return Live(Profile(self.path), self.openocd(rpc or self.rpc))

    def openocd(self, rpc):
        return OpenOcdTarget(Profile(self.path), rpc)

    def pins(self, rpc=None):
        live = self.live(rpc)
        return live, Pins(live, live.profile)


class ExpressionTests(unittest.TestCase):
    def test_arithmetic_and_names(self):
        self.assertEqual(evaluate("(1 << pin) | 0x10", {"pin": 5}), 0x30)
        self.assertEqual(evaluate("16000000 // freq - 1", {"freq": 1000}), 15999)
        self.assertEqual(evaluate("min(3, x) + max(1, 2)", {"x": 9}), 5)
        self.assertEqual(evaluate(7, {}), 7)

    def test_rejects_everything_else(self):
        for bad in ("__import__('os')", "(1).real", "a.b", "'x'", "1.5", "1 << 99", "1 // 0", "y + 1",
                    "[1]", "x if 1 else 2", "1 / 2", "9" * 300, "", True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                evaluate(bad, {"x": 1})


class PeekPokeTests(LiveCase):
    def test_peek_policy(self):
        live = self.live()
        self.rpc.put(GPIO + 4, 32, 0xDEADBEEF)
        self.assertEqual(live.peek(GPIO + 4)["values"], ["0xdeadbeef"])
        for address, kwargs in ((0x1000, {}), (GPIO + 2, {}), (0x50030008, {}), (GPIO, {"count": 0})):
            with self.subTest(address=address), self.assertRaises(ValueError):
                live.peek(address, **kwargs)

    def test_full_write_and_masked_write_preserve_other_bits(self):
        live = self.live()
        self.rpc.put(GPIO, 32, 0xFFFF0000)
        result = live.poke(live.poke_plan(GPIO, 0x5, mask=0xF))
        self.assertEqual(self.rpc.get(GPIO), 0xFFFF0005)
        self.assertEqual(result["step"]["before"], 0)
        self.assertEqual(result["step"]["after"], 5)
        live.poke(live.poke_plan(GPIO + 4, 0x12345678))
        self.assertEqual(self.rpc.get(GPIO + 4), 0x12345678)

    def test_denied_writes(self):
        live = self.live()
        cases = [(0x1000, 1, {}), (UID_ADDRESS, 1, {}), (GPIO + 1, 1, {"width": 32}),
                 (GPIO, 0x10, {"mask": 0x1}), (GPIO, 1 << 40, {})]
        for address, value, kwargs in cases:
            with self.subTest(address=address, value=value), self.assertRaises(ValueError):
                live.poke_plan(address, value, **kwargs)
        self.assertNotIn("write_memory", "".join(self.rpc.scripts))

    def test_stub_ram_is_readable_but_never_pokeable(self):
        live = self.live()
        self.assertEqual(live.peek(BOX)["values"], [f"{MAGIC:#010x}"])
        self.edit(lambda d: d["live"]["write_ranges"].append({"address": "0x20000000", "size": "0x10000"}))
        live = self.live()
        for address in (BOX + 4 * WORD["armed"], BOX + 4 * WORD["call_seq"], 0x20000200):
            with self.subTest(address=address), self.assertRaisesRegex(ValueError, "stub alanı"):
                live.poke_plan(address, 0)
        live.poke_plan(0x20001000, 1)  # ordinary RAM outside mailbox/scratch stays writable

    def test_long_steps_feed_the_deadman(self):
        live = self.live()
        live.run_steps([{"op": "delay_ms", "ms": 5}])
        self.assertEqual(self.rpc.get(BOX + 4 * WORD["host_hb"]), 2)

    def test_side_effect_register_is_written_blind(self):
        live = self.live()
        plan = live.poke_plan(0x50030008, 0x41)
        self.assertTrue(plan["step"]["blind"])
        self.assertFalse(plan["step"]["verify"])
        live.poke(plan)
        self.assertEqual(self.rpc.get(0x50030008), 0x41)
        self.assertEqual(len(self.rpc.scripts), 1)
        self.assertNotIn("read_memory 1345060872", self.rpc.scripts[0].partition("IDENTITY_MISMATCH}}; ")[2])
        with self.assertRaisesRegex(ValueError, "maskeli"):
            live.poke_plan(0x50030008, 1, mask=1)

    def test_readback_mismatch_is_reported_with_before_value(self):
        live = self.live()
        self.rpc.stuck.add(GPIO + 4)
        self.rpc.put(GPIO + 4, 32, 7)
        with self.assertRaises(StepFailed) as caught:
            live.poke(live.poke_plan(GPIO + 4, 9))
        self.assertIn("readback_mismatch", str(caught.exception))
        self.assertEqual(caught.exception.executed[0]["before"], 7)

    def test_no_verify_for_write_only_registers(self):
        live = self.live()
        self.rpc.stuck.add(GPIO + 4)
        result = live.poke(live.poke_plan(GPIO + 4, 9, verify=False))
        self.assertNotIn("after", result["step"])

    def test_no_verify_is_a_blind_write_that_never_writes_back_read_bits(self):
        live = self.live()
        self.rpc.put(GPIO + 4, 32, 0x9)  # W1C: bits 0 and 3 pending
        live.poke(live.poke_plan(GPIO + 4, 0x1, verify=False))
        body = self.rpc.scripts[-1].partition("IDENTITY_MISMATCH}}; ")[2]
        self.assertEqual(body, f"write_memory {GPIO + 4} 32 {{1}}")
        with self.assertRaisesRegex(ValueError, "maskeli"):
            live.poke_plan(GPIO + 4, 0x1, mask=0x1, verify=False)

    def test_status_does_not_decode_application_ram_as_a_stub(self):
        rpc = FakeRPC(stub=False)
        rpc.put(BOX + 4 * WORD["armed"], 32, 0x1234)  # leftover application data (seen on a real board)
        status = self.live(rpc).stub.status()
        self.assertFalse(status["magic_ok"])
        self.assertFalse(status["armed"])
        self.assertNotIn("status", status)

    def test_mailbox_and_scratch_from_elf_symbols(self):
        self.edit(lambda d: (d["live"].update(mailbox={"symbol": "eat_mailbox"}, scratch={"symbol": "eat_scratch"}),
                             d.update(artifact={"path": "fw.elf", "sha256": "x"})))
        image = unittest.mock.Mock()
        image.object.side_effect = {"eat_mailbox": (BOX, 0x200), "eat_scratch": (0x20000200, 0x800)}.get
        with patch.object(Profile, "artifact", return_value=image):
            live = self.live()
        self.assertEqual((live.stub.base, live.stub.capacity), (BOX, (0x200 // 4 - 18) // 4))
        self.assertEqual(live.scratch(), (0x20000200, 0x20000a00))
        self.assertEqual(live.peek(BOX)["values"], [f"{MAGIC:#010x}"])
        self.edit(lambda d: d.pop("artifact"))
        with self.assertRaisesRegex(ValueError, "artifact"):
            self.live()

    def test_heartbeat_never_writes_without_the_stub(self):
        rpc = FakeRPC(stub=False)
        live = self.live(rpc)
        self.assertFalse(live.stub.heartbeat())
        self.assertEqual(rpc.get(BOX + 4 * WORD["host_hb"]), 0)
        self.assertTrue(self.live().stub.heartbeat())

    def test_build_verification_feeds_the_deadman_between_chunks(self):
        live = self.live()
        live.config["verify_build"] = True

        def verify(tick):
            for _ in range(5):
                tick()
            return {}

        with patch.object(live.device, "verify", side_effect=verify):
            live.verify_build()
        self.assertEqual(self.rpc.get(BOX + 4 * WORD["host_hb"]), 1)  # throttled to one beat per timeout/6

    def test_uncertain_mutation_is_never_retried(self):
        live = self.live()
        plan = live.poke_plan(GPIO + 4, 1)

        def boom(_script):
            raise TimeoutError("uncertain")

        self.rpc.fail = boom
        with self.assertRaises(StepFailed) as caught:
            live.poke(plan)
        self.assertEqual(len(self.rpc.scripts), 1)
        self.assertEqual(caught.exception.executed[0]["outcome"], "unknown_if_sent")

    def test_identity_is_checked_in_the_same_request_and_blocks_write(self):
        live = self.live()
        plan = live.poke_plan(GPIO + 4, 1)
        self.rpc.put(UID_ADDRESS, 8, 0)  # wrong board attached
        with self.assertRaisesRegex(ValueError, "IDENTITY_MISMATCH"):
            live.poke(plan)
        self.assertEqual(self.rpc.get(GPIO + 4), 0)

    def test_failed_build_verification_prevents_write(self):
        live = self.live()
        live.config["verify_build"] = True
        with patch.object(live.device, "verify", side_effect=ValueError("mismatch")):
            with self.assertRaises(ValueError):
                live.poke(live.poke_plan(GPIO + 4, 1))
        self.assertEqual(self.rpc.scripts, [])


class PinTests(LiveCase):
    def test_profile_validation(self):
        _, pins = self.pins()
        names = {row["pin"]: row for row in pins.listing()}
        self.assertTrue(names["SWDIO"]["protected"])
        self.assertEqual(names["LED"]["functions"], ["gpio_out", "gpio_read", "pwm"])
        self.assertFalse(names["LED"]["measured"])

        self.edit(lambda d: d["pins"]["LED"].update(mcu_pin="P9.9"))
        with self.assertRaisesRegex(ValueError, "mcu_pin"):
            self.pins()

    def test_v1_profile_cannot_carry_live_sections(self):
        self.edit(lambda d: d.update(schema_version=1))
        with self.assertRaisesRegex(ValueError, "schema_version 2"):
            Profile(self.path)

    def test_pwm_plan_values_and_limits(self):
        _, pins = self.pins()
        plan = pins.plan_apply("LED", "pwm", {"freq": 1000, "duty_permille": 250})
        by_address = {s["address"]: s["value"] for s in plan["steps"] if s["op"] == "write"}
        self.assertEqual(by_address[TIMER + 0x08], 15999)
        self.assertEqual(by_address[TIMER + 0x0C], 4000)
        self.assertEqual(plan["resources"], ["TIM0_CH1"])
        bad = [{"freq": 1000, "duty_permille": 600}, {"freq": 30000}, {"freq": 100}, {},
               {"freq": 1000, "gpio_base": 1}, {"freq": "1000"}]
        for user in bad:
            with self.subTest(user=user), self.assertRaises(ValueError):
                pins.plan_apply("LED", "pwm", user)

    def test_pin_policy(self):
        _, pins = self.pins()
        for name, function in (("SWDIO", "gpio_in"), ("LED", "uart_tx"), ("NOPE", "gpio_in"), ("TX", "gpio_out")):
            with self.subTest(pin=name), self.assertRaises(ValueError):
                pins.plan_apply(name, function, {})
        with self.assertRaisesRegex(ValueError, "debug"):
            pins.plan_apply("SWDIO", "gpio_in", {})

    def test_apply_arms_deadman_before_writing_and_records_undo(self):
        live, pins = self.pins()
        pins.apply(pins.plan_apply("LED", "gpio_out", {"level": 1}))
        self.assertEqual(self.rpc.get(GPIO + 4) >> 5 & 1, 1)
        self.assertEqual(self.rpc.get(GPIO) >> 10 & 3, 1)
        self.assertEqual(self.rpc.get(BOX + 4 * WORD["armed"]), 1)
        self.assertEqual(self.rpc.get(BOX + 4 * WORD["safe_count"]), 2)
        first_row = [self.rpc.get(BOX + 4 * (18 + i)) for i in range(4)]
        self.assertEqual(first_row, [CLOCK, 32, 1, 1])
        arm_index = next(i for i, s in enumerate(self.rpc.scripts) if f"write_memory {BOX + 4 * WORD['armed']} 32 {{1}}" in s)
        write_index = next(i for i, s in enumerate(self.rpc.scripts) if f"write_memory {GPIO + 4} 32 [expr" in s)
        self.assertLess(arm_index, write_index)
        claim = pins.state.claims["LED"]
        self.assertEqual((claim["function"], claim["status"]), ("gpio_out", "applied"))
        self.assertTrue(claim["undo_complete"])
        self.assertTrue(live.stub.deadman)

    def test_release_drops_claim_and_disarms(self):
        _, pins = self.pins()
        pins.apply(pins.plan_apply("LED", "gpio_out", {"level": 1}))
        pins.finish("LED", pins.plan_release("LED"))
        self.assertEqual(self.rpc.get(GPIO) >> 10 & 3, 0)
        self.assertEqual(pins.state.claims, {})
        self.assertEqual(self.rpc.get(BOX + 4 * WORD["armed"]), 0)
        self.assertEqual(self.rpc.get(BOX + 4 * WORD["safe_count"]), 0)  # nothing left for a fault to replay

    def test_restore_returns_registers_to_original_values(self):
        _, pins = self.pins()
        initial = {GPIO: 0xAAAA5555, GPIO + 0x0C: 0x13579BDF, CLOCK: 0x80000000, TIMER: 0x10,
                   TIMER + 4: 0x77, TIMER + 8: 0x1234, TIMER + 0x0C: 0x4321}
        for address, value in initial.items():
            self.rpc.put(address, 32, value)
        pins.apply(pins.plan_apply("LED", "pwm", {"freq": 1000, "duty_permille": 250}))
        self.assertNotEqual(self.rpc.get(TIMER + 8), initial[TIMER + 8])
        pins.finish("LED", pins.plan_restore("LED"))
        self.assertEqual({a: self.rpc.get(a) for a in initial}, initial)
        self.assertNotIn("LED", pins.state.claims)

    def test_switching_function_keeps_the_original_undo(self):
        _, pins = self.pins()
        self.rpc.put(GPIO, 32, 0xC00)  # pin 5 mode bits originally 0b11
        pins.apply(pins.plan_apply("LED", "gpio_out", {"level": 1}))
        pins.apply(pins.plan_apply("LED", "pwm", {"freq": 1000}))
        pins.finish("LED", pins.plan_restore("LED"))
        self.assertEqual(self.rpc.get(GPIO) >> 10 & 3, 3)

    def test_partial_failure_is_saved_and_not_retried(self):
        _, pins = self.pins()
        self.rpc.stuck.add(TIMER + 0x08)
        with self.assertRaises(StepFailed):
            pins.apply(pins.plan_apply("LED", "pwm", {"freq": 1000}))
        claim = pins.state.claims["LED"]
        self.assertEqual(claim["status"], "partial")
        self.assertTrue(any(row["address"] == CLOCK for row in claim["undo"]))
        self.assertEqual(self.rpc.get(GPIO) >> 10 & 3, 0)  # pin was never switched to alt function

    def test_resource_conflict(self):
        _, pins = self.pins()
        pins.state.claims["LED"] = {"resources": ["UART0"], "safe_entries": []}
        with self.assertRaisesRegex(ValueError, "UART0"):
            pins.plan_apply("TX", "uart_tx", {})

    def test_safe_continues_after_a_failure_and_reports_it(self):
        _, pins = self.pins()
        pins.apply(pins.plan_apply("LED", "gpio_out", {"level": 1}))
        pins.apply(pins.plan_apply("TX", "uart_tx", {}))
        calls = {"n": 0}

        def flaky(script):
            if "write_memory" in script and calls["n"] == 0:
                calls["n"] += 1
                raise ConnectionError("link lost")

        self.rpc.fail = flaky
        results = pins.safe_all(["LED", "TX"])
        self.assertEqual([r["ok"] for r in results], [False, True])
        self.assertIn("LED", pins.state.claims)
        self.assertNotIn("TX", pins.state.claims)

    def test_claim_state_belongs_to_one_board(self):
        _, pins = self.pins()
        pins.apply(pins.plan_apply("LED", "gpio_out", {}))
        state = json.loads(pins.state.path.read_text(encoding="utf-8"))
        state["uid_hex"] = "00ff00ff"
        pins.state.path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "başka karta"):
            self.pins()

    def test_deadman_requires_replayable_safe_recipe(self):
        self.edit(lambda d: d["pins"]["LED"].update(safe_function="gpio_read"))
        with self.assertRaisesRegex(ValueError, "write/modify"):
            self.pins()
        self.edit(lambda d: d["live"].pop("mailbox"))  # without a stub there is no replay
        self.pins()

    def test_without_stub_pins_work_but_nothing_is_armed(self):
        self.edit(lambda d: d["live"].pop("mailbox"))
        rpc = FakeRPC(stub=False)
        live, pins = self.pins(rpc)
        self.assertIsNone(live.stub)
        pins.apply(pins.plan_apply("LED", "gpio_out", {"level": 1}))
        self.assertEqual(rpc.get(GPIO + 4) >> 5 & 1, 1)

    def test_stale_claims_after_deadman(self):
        _, pins = self.pins()
        pins.apply(pins.plan_apply("LED", "gpio_out", {}))
        self.rpc.put(BOX + 4 * WORD["deadman_count"], 32, 1)
        result = pins.apply(pins.plan_apply("TX", "uart_tx", {}))
        self.assertIn("dead-man", result["warnings"][0])
        self.assertEqual(pins.state.claims["LED"]["status"], "stale_after_deadman")

    def test_gpio_read_outputs(self):
        _, pins = self.pins()
        self.rpc.put(GPIO + 8, 32, 1 << 5)
        result = pins.apply(pins.plan_apply("LED", "gpio_read", {}))
        self.assertEqual(result["outputs"], {"raw_pin_bit": 32})


class StubAndRamTests(LiveCase):
    def test_status_and_liveness(self):
        live = self.live()
        self.assertTrue(live.stub.status()["magic_ok"])
        self.assertEqual(live.stub.require_alive()["version"], 1)
        self.rpc.stub_alive = False
        with self.assertRaisesRegex(ValueError, "heartbeat"):
            live.stub.require_alive()
        self.rpc.put(BOX, 32, 0)
        with self.assertRaisesRegex(ValueError, "Stub bulunamadı"):
            live.stub.require_alive()

    def test_overlap_and_capacity_validation(self):
        self.edit(lambda d: d["live"].update(scratch={"address": "0x20000100", "size": "0x100"}))
        with self.assertRaisesRegex(ValueError, "çakışamaz"):
            self.live()
        self.edit(lambda d: d["live"].update(scratch={"address": "0x20000200", "size": "0x800"},
                                              heartbeat_timeout_ms=5))
        with self.assertRaisesRegex(ValueError, "heartbeat_timeout_ms"):
            self.live()

    def test_ram_load_verifies_and_pads(self):
        live = self.live()
        result = live.ram_load(b"\x01\x02\x03\x04\x05")
        self.assertEqual(result["size"], 5)
        self.assertEqual(self.rpc.get(0x20000200), 0x04030201)
        self.assertEqual(self.rpc.get(0x20000204), 0x05)
        self.assertTrue(result["readback_verified"])

    def test_ram_load_bounds_and_readback(self):
        live = self.live()
        for data, address in ((b"", None), (b"x" * 4, 0x20000201), (b"x" * 4, 0x20000000),
                              (b"x" * 4, 0x20000A00), (b"x" * 0x801, None)):
            with self.subTest(size=len(data), address=address), self.assertRaises(ValueError):
                live.ram_load(data, address)
        self.rpc.stuck.add(0x20000200)
        with self.assertRaisesRegex(ValueError, "readback"):
            live.ram_load(b"abcd")

    def test_ram_load_in_chunks(self):
        live = self.live()
        data = bytes(range(256)) * 4  # 1024 bytes = 256 words = two chunks
        live.ram_load(data)
        self.assertEqual(self.rpc.get(0x20000200 + 1020), 0xFFFEFDFC)
        self.assertEqual(sum("write_memory 536871424" in s or "write_memory 536871936" in s for s in self.rpc.scripts), 2)

    def test_ram_run_applies_profile_entry_bits_and_returns_result(self):
        live = self.live()
        result = live.ram_run(0x20000200, [7, 8], 1)
        self.assertEqual(result["result"], 42)
        self.assertEqual(self.rpc.get(BOX + 4 * WORD["entry"]), 0x20000201)
        self.assertEqual([self.rpc.get(BOX + 4 * (WORD["args"] + i)) for i in range(3)], [7, 8, 0])
        self.assertGreater(self.rpc.get(BOX + 4 * WORD["host_hb"]), 0)

    def test_ram_run_fault_and_timeout(self):
        live = self.live()
        self.rpc.fault = True
        with self.assertRaisesRegex(ValueError, "fault"):
            live.ram_run(0x20000200, [], 1)
        self.rpc.fault, self.rpc.complete_calls = False, False
        before = len(self.rpc.scripts)
        with self.assertRaisesRegex(TimeoutError, "tekrar denenmedi"):
            live.ram_run(0x20000200, [], 0.05)
        calls = [s for s in self.rpc.scripts[before:] if f"write_memory {BOX + 4 * WORD['call_seq']} 32" in s]
        self.assertEqual(len(calls), 1)
        with self.assertRaisesRegex(ValueError, "argüman"):
            live.ram_run(0x20000200, [1] * 5, 1)

    def test_ram_run_needs_mailbox(self):
        self.edit(lambda d: d["live"].pop("mailbox"))
        with self.assertRaisesRegex(ValueError, "mailbox"):
            self.live(FakeRPC(stub=False)).ram_run(0x20000200, [], 1)


class CliTests(LiveCase):
    def args(self, *argv):
        return parser().parse_args(["--profile", str(self.path), "--session-dir", str(self.root / "s"), *argv])

    def test_mutations_are_plans_and_never_connect(self):
        with patch.object(core_module, "RPC", side_effect=AssertionError("connected")):
            for argv in (["poke", "0x50000004", "1"], ["pin", "apply", "LED", "gpio_out", "--param", "level=1"],
                         ["pin", "release", "LED"], ["safe", "--all"]):
                with self.subTest(argv=argv):
                    result = run(self.args(*argv))
                    self.assertFalse(result["executed"])
            listing = run(self.args("pin", "list"))
            self.assertEqual(len(listing["pins"]), 3)

    def test_safe_all_plan_lists_every_unprotected_pin(self):
        self.assertEqual(run(self.args("safe", "--all"))["plan"]["pins"], ["LED", "TX"])
        self.assertEqual(run(self.args("safe"))["plan"]["pins"], [])

    def test_execute_paths_use_one_connection_and_clean_up(self):
        with patch.object(core_module, "RPC", return_value=self.rpc):
            self.assertEqual(run(self.args("peek", "0x50FF0000", "--width", "8"))["values"], ["0xa1"])
            result = run(self.args("poke", "0x50000004", "0x20", "--execute"))
            self.assertEqual(result["step"]["after"], 0x20)
            self.assertTrue(run(self.args("stub", "status"))["magic_ok"])
            run(self.args("pin", "apply", "LED", "gpio_out", "--param", "level=1", "--execute"))
            self.assertIn("LED", json.loads((self.root / "example-board.pins.local.json").read_text())["claims"])
            self.assertTrue(run(self.args("safe", "--execute"))["ok"])

    def test_ram_run_requires_a_recorded_load_and_entry_inside_it(self):
        with self.assertRaisesRegex(ValueError, "ram load"):
            run(self.args("ram", "run"))
        (self.root / "snippet.bin").write_bytes(b"\x00\xbf" * 8)
        plan = run(self.args("ram", "load", "--file", "snippet.bin"))["plan"]
        self.assertEqual((plan["address"], plan["size"]), (0x20000200, 16))
        with patch.object(core_module, "RPC", return_value=self.rpc):
            run(self.args("ram", "load", "--file", "snippet.bin", "--execute"))
            for entry in ("0x20000000", "0x20000210"):
                with self.subTest(entry=entry), self.assertRaisesRegex(ValueError, "içinde"):
                    run(self.args("ram", "run", "--entry", entry))
            self.assertFalse(run(self.args("ram", "run", "--arg", "3"))["executed"])
            self.assertEqual(run(self.args("ram", "run", "--arg", "3", "--execute"))["result"], 42)

    def test_ram_files_must_stay_inside_the_project(self):
        outside = self.root.parent / "outside.bin"
        outside.write_bytes(b"\x00" * 4)
        self.addCleanup(outside.unlink)
        with self.assertRaisesRegex(ValueError, "proje kökü"):
            run(self.args("ram", "load", "--file", "../outside.bin"))

    def test_ram_build_is_an_argv_plan(self):
        self.edit(lambda d: d["live"].update(ram_build={"argv": ["make", "snippet"], "output": "snippet.bin"}))
        plan = run(self.args("ram", "build"))["plan"]
        self.assertEqual(plan["argv"], ["make", "snippet"])

    def session(self):
        return Session(Profile(self.path), self.openocd(self.rpc))

    def test_serve_request_shares_the_connection_and_audits(self):
        base = argparse.Namespace(profile=self.path, session_dir=self.root / "s")
        session = self.session()
        result = serve_request(json.dumps({"argv": ["peek", "0x50FF0000", "--width", "8"]}), base, session)
        self.assertTrue(result["ok"])
        self.assertTrue(Path(result["record"]).exists())
        self.assertNotIn("_session", result["arguments"])
        for line in ("not json", '{"argv": ["flash", "--execute"]}', '{"argv": ["serve"]}', '{"argv": []}',
                     '{"argv": ["peek"]}'):
            with self.subTest(line=line), contextlib.redirect_stderr(io.StringIO()):
                self.assertFalse(serve_request(line, base, session)["ok"])

    def test_serve_request_keeps_argparse_text_off_stdout(self):
        base = argparse.Namespace(profile=self.path, session_dir=self.root / "s")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            result = serve_request('{"argv": ["peek", "--help"]}', base, self.session())
        self.assertEqual(out.getvalue(), "")
        self.assertFalse(result["ok"])
        self.assertIn("usage", result["output"])

    def test_serve_session_verifies_the_build_once(self):
        base = argparse.Namespace(profile=self.path, session_dir=self.root / "s")
        session = self.session()
        session.live.config["verify_build"] = True
        with patch.object(session.live.device, "verify", return_value={"verified_bytes": 4}) as verify:
            for value in ("0x1", "0x2"):
                line = json.dumps({"argv": ["poke", "0x50000004", value, "--execute"]})
                self.assertTrue(serve_request(line, base, session)["ok"])
        self.assertEqual(verify.call_count, 1)

    def test_ctrl_c_during_a_request_ends_serve(self):
        base = argparse.Namespace(profile=self.path, session_dir=self.root / "s")
        requests = '{"argv": ["stub", "status"]}\n{"argv": ["stub", "status"]}\n'
        with patch.object(core_module, "RPC", return_value=self.rpc), \
                patch.object(cli_module, "run_live", side_effect=KeyboardInterrupt), \
                patch.object(sys, "stdin", io.StringIO(requests)), \
                contextlib.redirect_stdout(io.StringIO()):
            result = cli_module.serve(base, Profile(self.path))
        self.assertEqual((result["requests"], result["stopped_by"]), (1, "Ctrl+C"))

    def test_serve_never_heartbeats_without_the_stub(self):
        base = argparse.Namespace(profile=self.path, session_dir=self.root / "s")
        rpc = FakeRPC(stub=False)
        with patch.object(core_module, "RPC", return_value=rpc), \
                patch.object(sys, "stdin", io.StringIO('{"argv": ["peek", "0x50FF0000", "--width", "8"]}\n')), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            cli_module.serve(base, Profile(self.path))
        self.assertIn('"stub": false', out.getvalue())
        self.assertFalse(any("__hb" in s for s in rpc.scripts))
        self.assertEqual(rpc.get(BOX + 4 * WORD["host_hb"]), 0)

    def test_ram_run_refuses_changed_or_half_loaded_ram(self):
        (self.root / "a.bin").write_bytes(b"\x00\xbf" * 8)
        (self.root / "b.bin").write_bytes(b"\x01\xbf" * 600)
        with patch.object(core_module, "RPC", return_value=self.rpc):
            run(self.args("ram", "load", "--file", "a.bin", "--execute"))
            self.rpc.put(0x20000204, 32, 0xFFFFFFFF)  # reset or stray write changed scratch
            with self.assertRaisesRegex(ValueError, "uyuşmuyor"):
                run(self.args("ram", "run", "--execute"))
            run(self.args("ram", "load", "--file", "a.bin", "--execute"))
            self.rpc.stuck.add(0x20000200 + 512)  # second chunk fails its readback
            with self.assertRaisesRegex(ValueError, "readback"):
                run(self.args("ram", "load", "--file", "b.bin", "--execute"))
            with self.assertRaisesRegex(ValueError, "ram load"):
                run(self.args("ram", "run", "--execute"))

    def test_ram_build_argv_is_validated_like_build(self):
        self.edit(lambda d: d["live"].update(ram_build={"argv": ["gcc", 5], "output": "snippet.bin"}))
        with self.assertRaisesRegex(ValueError, "argv"):
            run(self.args("ram", "build"))


class RpcTests(unittest.TestCase):
    def test_failed_call_closes_the_stream_instead_of_desynchronising(self):
        class Sock:
            def sendall(self, _data):
                pass

            def recv(self, _size):
                raise TimeoutError("late")

            def close(self):
                self.closed = True

        rpc = object.__new__(RPC)
        rpc.sock, rpc.buffer = Sock(), b""
        sock = rpc.sock
        with self.assertRaises(TimeoutError):
            rpc.call("peek")
        self.assertTrue(rpc.closed and sock.closed)
        with self.assertRaisesRegex(ConnectionError, "kapatıldı"):
            rpc.call("peek")


if __name__ == "__main__":
    unittest.main()


class NamedRecipeTests(LiveCase):
    def setUp(self):
        super().setUp()
        self.svd_path = self.root / "device.svd"
        shutil.copy(Path(__file__).parent / "fixtures" / "svd" / "fictional.svd", self.svd_path)
        self.svd = SvdDevice.load(self.svd_path)
        self.map_path = self.root / "map.json"
        shutil.copy(EXAMPLES / "example-pin-map.json", self.map_path)
        self.out = self.root / "new.json"

    def scaffold(self):
        return run(parser().parse_args(["mcu-db", "scaffold", "--svd", str(self.svd_path),
                                       "--map", str(self.map_path), "--out", str(self.out)]))

    def use_scaffold(self):
        self.edit(lambda d: (d["live"].update(svd="device.svd", mcu_db="new.json"),
                             d.update(pins={"PIN": {"mcu_pin": "P0.0", "safe_function": "gpio_in",
                                                    "functions": ["gpio_out", "gpio_in", "gpio_read"]}})))
        return self.pins()

    def test_named_and_numeric_steps_are_identical(self):
        named = {"steps": [
            {"op": "modify", "address": "PORT.MODE", "mask": 'field_mask("FLAG{pin}")',
             "value": 'field_value("FLAG{pin}", level)'},
            {"op": "write", "address": "PORT.DATA{pin}", "value": 12},
            {"op": "read", "address": "PORT.THIRD", "mask": 'field_mask("STATE")', "name": "raw"},
            {"op": "poll", "address": "PORT.MODE", "mask": 'field_mask("COPY")',
             "value": 'field_value("COPY", 2)'},
        ]}
        numeric = {"steps": [
            {"op": "modify", "address": GPIO, "mask": 64, "value": 64},
            {"op": "write", "address": GPIO + 16, "value": 12},
            {"op": "read", "address": GPIO + 8, "width": 16, "mask": 7, "name": "raw"},
            {"op": "poll", "address": GPIO, "mask": 56, "value": 16},
        ]}
        self.assertEqual(compile_steps(named, {"pin": 0, "level": 1}, self.svd),
                         compile_steps(numeric, {}))
        with self.assertRaisesRegex(ValueError, "live.svd"):
            compile_steps(named, {"pin": 0, "level": 1})

    def test_bad_register_field_expression_and_overflow(self):
        expressions = ['field_mask("ABSENT")', 'field_mask("PORT.SECOND.STATE")',
                       'field_value("STATE", 8)', 'field_value("STATE", -1)',
                       'field_mask("{pin.__class__}")', 'field_mask("STATE", 1)',
                       'field_value("STATE", x=1)', 'field_mask(__import__("os"))',
                       'field_mask("STATE").real', 'other("STATE")']
        for expression in expressions:
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                compile_steps({"steps": [{"op": "write", "address": "PORT.MODE", "value": expression}]},
                              {}, self.svd)
        for address in ("PORT.ABSENT", "PORT.MODE.STATE", "PORT.{missing}", "PORT.{pin.real}"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                compile_steps({"steps": [{"op": "write", "address": address, "value": 0}]}, {}, self.svd)
        with self.assertRaises(ValueError):
            compile_steps({"steps": [{"op": "write", "address": "PORT.THIRD", "width": 32, "value": 0}]},
                          {}, self.svd)

    def test_scaffold_round_trip_and_policy(self):
        self.assertEqual(self.scaffold()["pins"], ["P0.0"])
        data = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(set(data["pins"]["P0.0"]["functions"]), {"gpio_in", "gpio_out", "gpio_read"})
        self.assertTrue(all(isinstance(s["address"], str) and s["address"].startswith("PORT.")
                            for r in data["recipes"].values() for s in r["steps"]))
        _, pins = self.use_scaffold()
        for level in (0, 1):
            plan = pins.plan_apply("PIN", "gpio_out", {"level": level})
            self.assertEqual(plan["steps"][0]["value"], level << 6)
        self.assertEqual(pins.plan_apply("PIN", "gpio_read", {})["steps"][0]["shift"], 6)
        self.edit(lambda d: d["live"].update(write_ranges=[]))
        with self.assertRaisesRegex(ValueError, "write_ranges"):
            self.pins()
        self.assertEqual(self.rpc.scripts, [])

    def test_scaffold_never_overwrites(self):
        self.scaffold()
        before = self.out.read_bytes()
        with self.assertRaises(FileExistsError):
            self.scaffold()
        self.assertEqual(self.out.read_bytes(), before)

    def test_scaffold_validates_mapping_before_creating_output(self):
        original = self.map_path.read_text(encoding="utf-8")
        for old, new in (("FLAG0", "MISSING"), ('"high": 1', '"high": 2'),
                         ('"PORT.THIRD"', '"PORT.FIELD_HAZARD"')):
            self.map_path.write_text(original.replace(old, new), encoding="utf-8")
            with self.subTest(new=new), self.assertRaises(ValueError):
                self.scaffold()
            self.assertFalse(self.out.exists())

    def test_explicit_atomic_set_clear_mapping(self):
        mapping = json.loads(self.map_path.read_text(encoding="utf-8"))
        mapping["pins"]["P0.0"]["atomic"] = {
            "set": {"register": "PORT.SECOND", "field": "FLAG0", "value": 1},
            "clear": {"register": "PORT.SECOND", "field": "FLAG1", "value": 1}}
        self.map_path.write_text(json.dumps(mapping), encoding="utf-8")
        self.scaffold()
        _, pins = self.use_scaffold()
        for level in (0, 1):
            step = pins.plan_apply("PIN", "gpio_out", {"level": level})["steps"][0]
            self.assertEqual(step["value"], 64 if level else 128)
            self.assertTrue(step["blind"])
            self.assertFalse(step["verify"])

    def test_svd_read_actions_and_protection_remain_enforced(self):
        self.edit(lambda d: d["live"].update(svd="device.svd"))
        live = self.live()
        for register in ("PORT.HAZARD", "PORT.FIELD_HAZARD"):
            for op in ("read", "poll", "modify"):
                raw = {"op": op, "address": register, "mask": 1, "value": 1, "name": "raw"}
                with self.subTest(register=register, op=op), self.assertRaises(ValueError):
                    live.prepare(compile_steps({"steps": [raw]}, {}, self.svd))
            step = live.prepare(compile_steps({"steps": [{"op": "write", "address": register,
                                                         "value": 1}]}, {}, self.svd))[0]
            self.assertTrue(step["blind"])
        for register in ("PORT.OUTSIDE", "PORT.MODE"):
            if register == "PORT.MODE":
                live.policy.protected.append((GPIO, GPIO + 4))
            with self.subTest(register=register), self.assertRaises(ValueError):
                live.prepare(compile_steps({"steps": [{"op": "write", "address": register,
                                                       "value": 1}]}, {}, self.svd))
