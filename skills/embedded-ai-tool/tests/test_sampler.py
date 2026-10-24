"""Real C producer and Python consumer through both existing memory transports."""
import ctypes
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import test_link
from embedded_ai_tool.core import OpenOcdTarget, Profile
from embedded_ai_tool.link import SerialTarget
from embedded_ai_tool.live import Live
from embedded_ai_tool.sampler import (
    CHANNEL_BASE,
    DATA,
    MAGIC,
    ROW,
    WORD,
    Sampler,
    stats,
)
from host_cc import STUB, build
from test_link import Wire
from test_live import FakeRPC, LiveCase

BASE = 0x20001000
ADDRESS = 0x20000800
SIZE = (DATA + 4 * ROW) * 4


class SamplerTargetTests(LiveCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = build(cls, [Path(__file__).with_name("sampler_harness.c"), STUB / "eat_sampler.c",
                              STUB / "eat_stub_core.c", STUB / "eat_link.c"], "eat_sampler_test")
        cls.lib.t_peek.restype = ctypes.c_uint32
        cls.lib.s_reads.restype = ctypes.c_uint32

    def setUp(self):
        super().setUp()
        self.lib.s_init()
        self.edit(lambda d: d["read_ranges"].append({"address": ADDRESS, "size": 0x1000}))
        self.edit(lambda d: d["live"].update(samples={"address": BASE, "size": SIZE}))

    def get(self, word):
        return self.lib.t_peek(BASE + word * 4, 32)

    def put(self, word, value):
        self.lib.t_poke(BASE + word * 4, 32, value)

    def sampler(self, serial=False, symbol=False):
        lib = self.lib
        if symbol:
            self.edit(lambda d: (d["live"].update(samples={"symbol": "eat_samples"}),
                                 d.update(artifact={"path": "fw.elf", "sha256": "x"})))
        profile = Profile(self.path)
        profile.image = SimpleNamespace(object=Mock(return_value=(BASE, SIZE)))
        if serial:
            target = SerialTarget(profile, Wire(lib))
        else:
            class Probe(FakeRPC):
                def get(self, address, width=32):
                    return lib.t_peek(address, width)

                def put(self, address, width, value):
                    lib.t_poke(address, width, value)
            target = OpenOcdTarget(profile, Probe(stub=False))
        write = target.write

        def sync_write(address, width, values):
            write(address, width, values)
            # Models the independently scheduled producer acknowledging enable/stop.
            if address == BASE + 4 * WORD["enable"]:
                lib.s_sync()
        target.write = sync_write
        live = Live(profile, target)
        live.keepalive = Mock()
        sampler = Sampler(live)
        if symbol:
            profile.image.object.assert_called_once_with("eat_samples")
        else:
            profile.image.object.assert_not_called()
        return sampler

    def test_samples_address_and_symbol_both_transports(self):
        for symbol in (False, True):
            for serial in (False, True):
                with self.subTest(symbol=symbol, serial=serial):
                    self.lib.s_init()
                    s = self.sampler(serial, symbol)
                    self.assertEqual((s.address, s.size), (BASE, SIZE))
                    s.configure([hex(ADDRESS)], 10)
                    s.start()
                    self.lib.s_advance(10)
                    self.assertEqual(len(s.drain()), 1)
                    s.stop()

    def configured(self, serial=False):
        sampler = self.sampler(serial)
        sampler.configure([hex(ADDRESS)], 10)
        sampler.start()
        return sampler

    def test_wrap_overrun_and_measured_rate_both_transports(self):
        for serial in (False, True):
            with self.subTest(serial=serial):
                self.lib.s_init()
                s = self.configured(serial)
                for _ in range(6):
                    self.lib.s_advance(13)  # requested 100 Hz, actual tick rate is different
                self.assertEqual(self.get(WORD["overrun"]), 2)
                rows = s.drain()
                self.assertEqual([r["sequence"] for r in rows], [1, 2, 3, 4])
                for _ in range(3):
                    self.lib.s_advance(13)
                rows += s.drain()
                end = s.stop()
                result = stats(rows, s.baseline, end, 1)
                self.assertEqual(result["attempts"], 9)
                self.assertEqual(result["loss"], 2)
                self.assertEqual(result["sequence_gaps"], 2)
                self.assertEqual(result["rate_hz"], 9000 / result["target_elapsed_ms"])
                self.assertNotEqual(result["rate_hz"], 100)
                self.assertEqual(s.drain(), [])

    def test_invalid_allow_table_never_reads(self):
        s = self.configured()
        s.stop()
        self.put(WORD["allow_count"], 0)
        self.put(WORD["enable"], 1)
        self.lib.s_sync()
        self.lib.s_advance(100)
        self.assertEqual(self.get(WORD["state"]), 2)
        self.assertEqual(self.lib.s_reads(), 0)
        self.assertEqual(self.get(WORD["sequence"]), 0)

    def test_bad_configs_refused_before_any_channel_read(self):
        for word, value in ((WORD["count"], 9), (WORD["period"], 0), (CHANNEL_BASE, 7),
                            (CHANNEL_BASE + 2, 24), (CHANNEL_BASE + 1, ADDRESS + 1),
                            (WORD["allow_count"], 9)):
            with self.subTest(word=word):
                self.lib.s_init()
                s = self.configured()
                s.stop()
                self.put(word, value)
                self.put(WORD["enable"], 1)
                self.lib.s_sync()
                self.assertEqual(self.get(WORD["state"]), 2)
                self.assertEqual(self.lib.s_reads(), 0)

    def test_port_hook_and_external_push_share_format(self):
        s = self.configured()
        s.stop()
        self.put(CHANNEL_BASE, 1)
        self.put(CHANNEL_BASE + 1, 42)
        self.put(WORD["enable"], 1)
        self.lib.s_sync()
        self.lib.s_advance(10)
        self.assertEqual(s.drain()[0]["values"], [52])
        self.assertEqual(self.lib.s_push(123), 1)
        self.assertEqual(s.drain()[0]["values"], [123])

    def test_uint32_index_sequence_time_wrap(self):
        s = self.configured()
        s.stop()
        for name in ("write", "read", "sequence"):
            self.put(WORD[name], 0xFFFFFFFE)
        self.lib.s_advance(0xFFFFFFF0)
        s.start()
        self.lib.s_advance(10)
        self.lib.s_advance(10)
        rows = s.drain()
        self.assertEqual([r["sequence"] for r in rows], [0xFFFFFFFF, 0])
        result = stats(rows, s.baseline, s.stop(), 1)
        self.assertEqual((result["attempts"], result["target_elapsed_ms"], result["loss"]), (2, 20, 0))

    def test_policy_and_write_boundary(self):
        s = self.sampler()
        s.live.policy.side_effect = [(ADDRESS, ADDRESS + 4)]
        with self.assertRaisesRegex(ValueError, "Yan etkili"):
            s.configure([hex(ADDRESS)], 10)
        for channel in ("0x40000000", "0x100000000", "0x20000801", "0x20000800:24", hex(BASE)):
            with self.subTest(channel=channel), self.assertRaises(ValueError):
                s.configure([channel], 10)
        for word in (0, 6, 8, DATA, 10000):
            with self.assertRaises(ValueError):
                s.write(word, [1])
        self.assertEqual(self.get(WORD["magic"]), MAGIC)

    def test_torn_header_retries_and_bad_header_cannot_write(self):
        s = self.sampler()
        self.put(WORD["epoch"], 1)
        with self.assertRaises(TimeoutError):
            s.header()
        self.put(WORD["epoch"], 0)
        self.put(WORD["slots"], 5)
        with self.assertRaises(ValueError):
            self.sampler()

    def test_measure_cleanup_and_duration(self):
        s = self.sampler()
        original = s.drain

        def drain():
            self.lib.s_advance(10)
            return original()
        s.drain = drain
        result = s.measure([hex(ADDRESS)], 10, 0.025, [1])
        self.assertGreater(result["count"], 0)
        self.assertEqual(self.get(WORD["state"]), 0)
        with patch.object(s, "drain", side_effect=ValueError("read failed")):
            with self.assertRaisesRegex(ValueError, "read failed"):
                s.measure([hex(ADDRESS)], 10, 0.01)
        self.assertEqual(self.get(WORD["state"]), 0)
        for duration in (0, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                s.measure([hex(ADDRESS)], 10, duration)

    def test_idle_time_before_stop_is_in_measured_rate(self):
        s = self.configured()
        self.lib.s_advance(10)
        self.lib.s_clock(90)  # producer was delayed, then sees stop before another sample
        end = s.stop()
        result = stats(s.drain(), s.baseline, end, 1)
        self.assertEqual((result["rate_hz"], result["target_elapsed_ms"]), (10, 100))

    def test_multiple_memory_widths_and_failed_wrapped_read(self):
        s = self.sampler()
        s.configure([f"{ADDRESS}:8", f"{ADDRESS + 2}:16"], 10)
        s.start()
        self.lib.t_poke(ADDRESS, 32, 0xFEDCBA98)
        for _ in range(3):
            self.lib.s_advance(10)
        self.assertEqual(s.drain()[0]["values"], [0x98, 0xFEDC])
        for _ in range(3):
            self.lib.s_advance(10)
        read = self.get(WORD["read"])
        original = s.target.read

        def fail_second_segment(address, width, count):
            if address == BASE + DATA * 4:
                raise OSError("bulk read failed")
            return original(address, width, count)
        with patch.object(s.target, "read", side_effect=fail_second_segment):
            with self.assertRaisesRegex(OSError, "bulk read failed"):
                s.drain()
        self.assertEqual(self.get(WORD["read"]), read)
        self.assertEqual([r["sequence"] for r in s.drain()], [4, 5, 6])

    def test_sampling_faster_than_host_reads_preserves_start_and_rows(self):
        s = self.sampler()
        s.configure([hex(ADDRESS)], 10)
        original = s.target.read

        def slow_read(address, width, count):
            self.lib.s_advance(10)
            return original(address, width, count)
        with patch.object(s.target, "read", side_effect=slow_read):
            start = s.start()
            self.assertEqual(start["sequence"], 0)
            rows = s.drain()
            self.assertEqual([r["sequence"] for r in rows], [1, 2, 3])
            end = s.stop()
        rows += s.drain()
        result = stats(rows, start, end, 1)
        self.assertEqual(result["attempts"], len(rows) + result["overruns"])

    def test_missing_stop_ack_does_not_rewrite_configuration(self):
        s = self.configured()
        original = s.target.write
        writes = []

        def record(address, width, values):
            writes.append(address)
            original(address, width, values)
        with patch.object(s.target, "write", side_effect=record), patch.object(s, "wait_state", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                s.configure([hex(ADDRESS + 4)], 20)
        self.assertEqual(writes, [BASE + WORD["enable"] * 4])

    def test_cli_measure_dispatches_through_existing_target(self):
        from embedded_ai_tool.cli import parser, run
        from embedded_ai_tool.live import Session

        s = self.sampler()
        args = parser().parse_args(["--profile", str(self.path), "measure", "--channel", hex(ADDRESS),
                                    "--period-ms", "10", "--duration", "0.01"])
        session = Session(s.live.profile, s.target)
        args._session = session
        result = run(args)
        self.assertEqual((result["count"], result["attempts"], result["rate_hz"]), (0, 0, None))


class SamplerPolicyTests(LiveCase):
    def test_samples_readable_but_poke_and_pin_recipes_refused(self):
        self.edit(lambda d: (d["live"].update(samples={"address": BASE, "size": SIZE}),
                             d["live"]["write_ranges"].append({"address": BASE, "size": SIZE + 4})))
        live, pins = self.pins()
        self.assertEqual(live.peek(BASE)["values"], ["0x00000000"])
        for address in (BASE, BASE + SIZE - 4):
            with self.subTest(address=address), self.assertRaisesRegex(ValueError, "stub alanı"):
                live.poke_plan(address, 0)
        live.poke_plan(BASE + SIZE, 1)
        for op in ("write", "modify"):
            pins.db.recipes["gpio_out"]["steps"] = [
                {"op": op, "address": BASE, "value": 1, "mask": 1}]
            with self.subTest(op=op), self.assertRaisesRegex(ValueError, "stub alanı"):
                pins.plan_apply("LED", "gpio_out", {})
        self.assertNotIn("write_memory", "".join(self.rpc.scripts))

    def test_missing_samples_names_profile_field_before_target_access(self):
        live = self.live()
        with self.assertRaisesRegex(ValueError, r"live\.samples"):
            Sampler(live)
        self.assertEqual(self.rpc.scripts, [])


class SamplerStatsTests(unittest.TestCase):
    def test_stats_empty_and_crossings_with_gaps(self):
        start = {"sequence": 10, "time": 100, "overrun": 0}
        rows = [{"sequence": seq, "values": [value]} for seq, value in ((11, 0), (12, 10), (14, 0), (15, 10))]
        result = stats(rows, start, {"sequence": 16, "time": 200, "overrun": 2}, 1, [5])
        self.assertEqual(result["loss"], 2)  # includes tail loss
        self.assertEqual(result["channels"], [{"min": 0, "max": 10, "mean": 5, "threshold_crossings": 2}])
        self.assertIsNone(stats([], start, start, 1)["rate_hz"])

    def test_cli_and_mcp(self):
        from embedded_ai_tool.cli import parser
        from embedded_ai_tool.mcp_server import TOOLS
        tool = TOOLS["measure"]
        args = parser().parse_args(tool["argv"]({"channels": [hex(ADDRESS)], "period_ms": 10, "duration": 1}))
        self.assertEqual((args.channel, args.period_ms, args.duration), ([hex(ADDRESS)], 10, 1))
        self.assertTrue(tool["mutating"])

    def test_mcp_duration_cap_checked_before_connecting(self):
        from embedded_ai_tool.mcp_server import TOOLS, Bridge, check

        arguments = {"channels": [hex(ADDRESS)], "period_ms": 10, "duration": 60}
        check(TOOLS["measure"]["schema"], arguments)
        arguments["duration"] = 61
        with self.assertRaisesRegex(ValueError, "duration.*60"):
            check(TOOLS["measure"]["schema"], arguments)
        bridge = Bridge.__new__(Bridge)
        bridge.connect = Mock()
        self.assertTrue(bridge.call("measure", arguments)["isError"])
        bridge.connect.assert_not_called()

    def test_protocol_defines_match(self):
        text = (STUB / "eat_sampler.h").read_text()
        defines = {n: int(v, 0) for n, v in re.findall(r"#define (EAT_S_\w+) (0x[0-9a-fA-F]+|\d+)u", text)}
        for name, value in WORD.items():
            self.assertEqual(defines["EAT_S_" + name.upper()], value)


class SamplerPortabilityTests(unittest.TestCase):
    def test_sampler_and_enabled_embed_compile_for_each_family(self):
        with tempfile.TemporaryDirectory() as out:
            for name, flags in test_link.PortabilityTests.TARGETS:
                for source in ("eat_sampler.c", "eat_embed.c"):
                    with self.subTest(target=name, source=source):
                        result = subprocess.run([sys.executable, "-m", "ziglang", "cc", *flags, "-std=c99", "-Os",
                                                 "-Wall", "-Wextra", "-Werror", "-pedantic", f"-I{STUB}",
                                                 "-DEAT_SAMPLER_SLOTS=4", "-c", str(STUB / source),
                                                 "-o", str(Path(out) / "sampler.o")],
                                                capture_output=True, text=True, check=False)
                        self.assertEqual(result.returncode, 0, result.stderr)
