"""Run the real C stub core against the real Python host code over a bridged mailbox.

The C core is compiled for the host and the mailbox words live in a ctypes buffer; the fake RPC
ticks the stub after every host request, as the target's main loop would between SWD accesses.
This validates protocol agreement and dead-man logic, not any MCU port."""
import ctypes
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from embedded_ai_tool.live import HEADER_WORDS, MAGIC, PROTOCOL, SAFE_ENTRY_WORDS, WORD
from host_cc import COMPILER, SKIP_REASON, STUB, build
from test_live import BOX, CLOCK, GPIO, FakeRPC, LiveCase


class ProtocolSyncTests(unittest.TestCase):
    def test_c_header_matches_python_constants(self):
        text = (STUB / "eat_stub_core.h").read_text(encoding="utf-8")
        defines = {name: int(value, 0) for name, value in re.findall(r"#define (EAT_\w+) (0x[0-9a-fA-F]+|\d+)u?\b", text)}
        for name, index in WORD.items():
            self.assertEqual(defines[f"EAT_W_{name.upper()}"], index, name)
        self.assertEqual(defines["EAT_MAGIC"], MAGIC)
        self.assertEqual(defines["EAT_PROTOCOL"], PROTOCOL)
        self.assertEqual(defines["EAT_HEADER_WORDS"], HEADER_WORDS)
        self.assertEqual(defines["EAT_SAFE_ROW_WORDS"], SAFE_ENTRY_WORDS)


class BridgedRPC(FakeRPC):
    """FakeRPC whose mailbox words live in the C stub's buffer; the stub runs after every request."""

    def __init__(self, lib, buf):
        super().__init__(stub=False)
        self.lib, self.buf = lib, buf
        self.complete_calls = False

    @staticmethod
    def in_box(address):
        return BOX <= address < BOX + 0x200

    def get(self, address, width=32):
        if self.in_box(address):
            assert width == 32 and address % 4 == 0
            return self.buf[(address - BOX) // 4]
        return super().get(address, width)

    def put(self, address, width, value):
        if self.in_box(address):
            assert width == 32 and address % 4 == 0
            self.buf[(address - BOX) // 4] = value
        else:
            super().put(address, width, value)

    def call(self, script):
        result = super().call(script)
        self.lib.t_advance(5)
        return result


@unittest.skipUnless(COMPILER, SKIP_REASON)
class BridgedStubTests(LiveCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = build(cls, [Path(__file__).with_name("stub_harness.c"), STUB / "eat_stub_core.c"], "eat_stub_test")
        cls.lib.t_log_get.restype = ctypes.c_uint32
        cls.lib.t_last_entry.restype = ctypes.c_uint32

    def setUp(self):
        super().setUp()
        self.buf = (ctypes.c_uint32 * 128)()  # matches the example profile's 0x200-byte mailbox
        self.lib.t_init(self.buf, 128)
        self.rpc = BridgedRPC(self.lib, self.buf)

    def rows(self):
        return [[self.lib.t_log_get(i, f) for f in range(4)] for i in range(self.lib.t_log_count())]

    def idle(self, ticks):
        for _ in range(ticks):
            self.lib.t_advance(5)

    def test_host_sees_a_valid_live_stub(self):
        live = self.live()
        status = live.stub.require_alive()
        self.assertTrue(status["magic_ok"])
        self.assertEqual(status["status"], "idle")

    def test_ram_call_round_trip(self):
        result = self.live().ram_run(0x20000200, [3, 4], 1)
        self.assertEqual(result["result"], 7)
        self.assertEqual(self.lib.t_last_entry(), 0x20000201)

    def test_deadman_replays_safe_table_when_host_goes_silent(self):
        _, pins = self.pins()
        pins.apply(pins.plan_apply("LED", "gpio_out", {"level": 1}))
        self.assertTrue(self.buf[WORD["armed"]])
        self.idle(150)  # about 750 ms of silence: still inside the 1000 ms window
        self.assertEqual(self.rows(), [])
        self.idle(100)
        self.assertEqual(self.rows(), [[CLOCK, 32, 1, 1], [GPIO, 32, 0xC00, 0]])
        self.assertEqual(self.buf[WORD["status"]], 4)
        self.assertEqual(self.buf[WORD["deadman_count"]], 1)
        self.idle(400)
        self.assertEqual(len(self.rows()), 2, "dead-man must fire once, not repeatedly")

    def test_heartbeats_keep_the_pins_alive(self):
        live, pins = self.pins()
        pins.apply(pins.plan_apply("LED", "gpio_out", {"level": 1}))
        for _ in range(300):  # each host request advances the target by 5 ms: 1500 ms in total
            live.stub.heartbeat()
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.buf[WORD["deadman_count"]], 0)

    def test_host_recovers_after_deadman_and_flags_stale_claims(self):
        live, pins = self.pins()
        pins.apply(pins.plan_apply("LED", "gpio_out", {"level": 1}))
        self.idle(250)
        result = pins.apply(pins.plan_apply("TX", "uart_tx", {}))
        self.assertIn("dead-man", result["warnings"][0])
        self.assertEqual(pins.state.claims["LED"]["status"], "stale_after_deadman")
        live.stub.heartbeat()
        self.assertEqual(live.stub.status()["status"], "idle")

    def test_stub_reset_without_deadman_is_detected(self):
        _, pins = self.pins()
        pins.apply(pins.plan_apply("LED", "gpio_out", {"level": 1}))
        self.lib.t_init(self.buf, 128)  # target reset: mailbox zeroed, deadman_count back to 0
        result = pins.apply(pins.plan_apply("TX", "uart_tx", {}))
        self.assertIn("yeniden başlamış", result["warnings"][0])
        self.assertEqual(pins.state.claims["LED"]["status"], "stale_after_deadman")
        self.assertTrue(self.buf[WORD["armed"]])  # re-armed for the claims that remain

    def test_release_disarms_so_nothing_fires(self):
        _, pins = self.pins()
        pins.apply(pins.plan_apply("LED", "gpio_out", {"level": 1}))
        pins.finish("LED", pins.plan_release("LED"))
        self.assertFalse(self.buf[WORD["armed"]])
        self.idle(400)
        self.assertEqual(self.buf[WORD["deadman_count"]], 0)

    def test_fault_marks_call_failed_and_applies_safe_state(self):
        live, pins = self.pins()
        pins.apply(pins.plan_apply("LED", "gpio_out", {"level": 1}))
        with self.assertRaisesRegex(ValueError, "fault"):
            live.ram_run(0xDEAD0000, [], 1)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(live.stub.status()["status"], "fault")

    def test_fault_never_replays_a_disarmed_table(self):
        live, pins = self.pins()
        pins.apply(pins.plan_apply("LED", "gpio_out", {"level": 1}))
        self.buf[WORD["armed"]] = 0  # e.g. the host is mid re-arm; rows are stale or half written
        with self.assertRaisesRegex(ValueError, "fault"):
            live.ram_run(0xDEAD0000, [], 1)
        self.assertEqual(self.rows(), [])

    def test_safe_table_larger_than_capacity_is_clamped_by_the_stub(self):
        words = 18 + 4  # header plus a single safe row
        small = (ctypes.c_uint32 * words)()
        self.lib.t_init(small, words)
        small[WORD["armed"]], small[WORD["timeout_ms"]], small[WORD["safe_count"]] = 1, 100, 99
        for i in range(4):
            small[18 + i] = i + 1
        self.idle(60)
        self.assertEqual(self.rows(), [[1, 2, 3, 4]])


if __name__ == "__main__":
    unittest.main()
