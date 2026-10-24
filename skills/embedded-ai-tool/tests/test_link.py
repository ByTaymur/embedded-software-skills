"""Serial transport tests: link.py against the real C stub core + serial link over simulated memory."""
import ctypes
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from embedded_ai_tool import link
from embedded_ai_tool.core import Profile
from embedded_ai_tool.live import WORD, Live, Pins
from host_cc import COMPILER, SKIP_REASON, STUB, build
from test_live import BOX, CLOCK, GPIO, LiveCase


class ProtocolSyncTests(unittest.TestCase):
    def test_c_header_matches_python(self):
        text = (STUB / "eat_link.h").read_text(encoding="utf-8")
        defines = {name: int(value, 0) for name, value in re.findall(r"#define (EAT_\w+) (0x[0-9a-fA-F]+|\d+)u?\b", text)}
        self.assertEqual(defines["EAT_LINK_PROTOCOL"], link.PROTOCOL)
        self.assertEqual(bytes([defines["EAT_LINK_SYNC0"], defines["EAT_LINK_SYNC1"]]), link.SYNC)
        for name, code in link.COMMAND.items():
            self.assertEqual(defines[f"EAT_CMD_{name.upper()}"], code, name)
        statuses = {"OK": 0, "BAD_REQUEST": 1, "IDENTITY": 2, "UNKNOWN": 3, "ALIGNMENT": 4}
        for name, code in statuses.items():
            self.assertEqual(defines[f"EAT_LINK_{name}"], code)
            self.assertIn(code, link.STATUS)

    def test_crc16_check_value(self):
        self.assertEqual(link.crc16(b"123456789"), 0x29B1)  # CRC-16/CCITT-FALSE reference value


class Wire:
    """Byte stream into the compiled target: what a UART would carry."""

    def __init__(self, lib):
        self.lib, self.written = lib, []

    def write(self, data):
        self.written.append(bytes(data))
        self.lib.t_feed(bytes(data), len(data))

    def read(self, count):
        buffer = ctypes.create_string_buffer(count)
        taken = self.lib.t_take(buffer, count)  # before reading .raw: it is a copy
        return buffer.raw[:taken]

    def close(self):
        pass


@unittest.skipUnless(COMPILER, SKIP_REASON)
class SerialTargetTests(LiveCase):
    @classmethod
    def setUpClass(cls):
        sources = [Path(__file__).with_name("link_harness.c"), STUB / "eat_stub_core.c", STUB / "eat_link.c"]
        cls.lib = build(cls, sources, "eat_link_test")
        cls.lib.t_peek.restype = ctypes.c_uint32
        cls.lib.t_crc.restype = ctypes.c_uint32

    def setUp(self):
        super().setUp()
        self.edit(lambda d: d.update(connection={"transport": "serial", "port": "TEST", "timeout_s": 0.2}))
        self.lib.t_init(1)
        self.wire = Wire(self.lib)

    def target(self):
        return link.SerialTarget(Profile(self.path), self.wire)

    def serial_live(self):
        live = Live(Profile(self.path), self.target())
        return live, Pins(live, live.profile)

    def test_c_and_python_crc_agree(self):
        data = bytes(range(200))
        self.assertEqual(self.lib.t_crc(data, len(data)), link.crc16(data))

    def test_info_reports_the_stub_mailbox(self):
        target = self.target()
        self.assertEqual((target.mailbox_address, target.mailbox_words), (BOX, 128))
        self.assertEqual(target.max_payload, 1024)

    def test_peek_poke_masked_and_chunked_over_serial(self):
        live, _ = self.serial_live()
        self.lib.t_poke(GPIO, 32, 0xFFFF0000)
        step = live.poke(live.poke_plan(GPIO, 0x5, mask=0xF))["step"]
        self.assertEqual((step["before"], step["after"]), (0, 5))
        self.assertEqual(self.lib.t_peek(GPIO, 32), 0xFFFF0005)
        live.poke(live.poke_plan(GPIO + 4, 0xAB, width=8))
        self.assertEqual(self.lib.t_peek(GPIO + 4, 32), 0xAB)
        words = list(range(400))  # more than one frame each way
        live.target.write(0x20001000, 32, words)
        self.assertEqual(live.target.read(0x20001000, 32, 400), words)
        self.assertGreater(len(self.wire.written), 4)

    def test_wrong_board_changes_nothing(self):
        target = self.target()
        target.guard = target.guard[:-1] + b"\x00"  # expected UID differs from the attached board
        with self.assertRaisesRegex(ValueError, "IDENTITY_MISMATCH"):
            target.write(GPIO, 32, [0x1234])
        self.assertEqual(self.lib.t_peek(GPIO, 32), 0)

    def test_pin_apply_arms_the_deadman_over_serial(self):
        _, pins = self.serial_live()
        pins.apply(pins.plan_apply("LED", "gpio_out", {"level": 1}))
        self.assertEqual(self.lib.t_peek(GPIO, 32) >> 10 & 3, 1)
        self.assertEqual(self.lib.t_peek(BOX + 4 * WORD["armed"], 32), 1)
        self.lib.t_idle(1500)  # host silent longer than heartbeat_timeout_ms
        self.assertEqual(self.lib.t_peek(GPIO, 32) >> 10 & 3, 0, "dead-man must apply the safe state")
        self.assertEqual(self.lib.t_peek(BOX + 4 * WORD["deadman_count"], 32), 1)
        self.assertEqual(self.lib.t_peek(CLOCK, 32) & 1, 1)

    def test_heartbeat_needs_the_stub(self):
        live, _ = self.serial_live()
        self.assertTrue(live.stub.heartbeat())
        self.lib.t_init(0)  # link only, no stub core: mailbox RAM is application data
        live = Live(Profile(self.path), self.target())
        self.assertFalse(live.stub.heartbeat())
        self.assertEqual(self.lib.t_peek(BOX + 4 * WORD["host_hb"], 32), 0)

    def test_garbled_answer_closes_the_link(self):
        target = self.target()
        target.stream.read = lambda count: b"\xea\x7e\x02\x00\x01\x00\x00\x00"[:count]  # bad CRC
        with self.assertRaises((ConnectionError, TimeoutError)):
            target.read(GPIO, 32, 1)
        self.assertTrue(target.closed)
        with self.assertRaisesRegex(ConnectionError, "kapatıldı"):
            target.read(GPIO, 32, 1)

    def test_corrupt_request_gets_no_answer(self):
        target = self.target()
        sent = link.frame(bytes([9, 2]) + target.guard + b"\x00" * 7)
        self.wire.write(sent[:-1] + bytes([sent[-1] ^ 0xFF]))
        self.assertEqual(self.wire.read(64), b"")

    def test_cli_runs_over_serial(self):
        from unittest.mock import patch

        from embedded_ai_tool.cli import parser, run

        args = parser().parse_args(["--profile", str(self.path), "--session-dir", str(self.root / "s"),
                                    "peek", "0x50FF0000", "--width", "8"])
        with patch.object(link.SerialTarget, "__init__", lambda s, p: SerialTargetTests.init(s, p, self.wire)):
            self.assertEqual(run(args)["values"], ["0xa1"])
            for command in (["control", "halt", "--execute"],):
                args = parser().parse_args(["--profile", str(self.path), *command])
                with self.assertRaisesRegex(ValueError, "yalnız OpenOCD"):
                    run(args)

    def test_svd_register_read_over_serial_keeps_identity_guard(self):
        from unittest.mock import patch

        from embedded_ai_tool.cli import parser, run

        svd = Path(__file__).parent / "fixtures" / "svd" / "fictional.svd"
        self.edit(lambda d: d["live"].update(svd=str(svd)))
        self.lib.t_poke(GPIO, 32, 2)
        args = parser().parse_args(["--profile", str(self.path), "reg", "read", "PORT.MODE.STATE"])
        target = self.target()
        with patch("embedded_ai_tool.live.open_target", return_value=target) as opened:
            result = run(args)["registers"][0]
            self.assertEqual(result["raw_value"], "0x00000002")
            self.assertEqual(result["fields"][0]["enum_name"], "TWO")
            target = self.target()
            opened.return_value = target
            target.guard = target.guard[:-1] + b"\x00"
            with self.assertRaisesRegex(ValueError, "IDENTITY_MISMATCH"):
                run(args)

    @staticmethod
    def init(target, profile, wire, original=link.SerialTarget.__init__):
        original(target, profile, wire)


@unittest.skipUnless(importlib.util.find_spec("ziglang"), "çapraz derleme için `pip install ziglang`")
class PortabilityTests(unittest.TestCase):
    """The stub sources must stay warning-free C99 on every 32-bit family, not just one MCU."""

    TARGETS = (("arm-cortex-m0", ("-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0")),
               ("riscv32", ("-target", "riscv32-freestanding-none")),
               ("mips32 (PIC32)", ("-target", "mipsel-freestanding-none")),
               ("host-64bit", ()))

    def test_stub_sources_compile_for_each_family(self):
        with tempfile.TemporaryDirectory() as out:
            for name, flags in self.TARGETS:
                for source in ("eat_stub_core.c", "eat_link.c", "eat_embed.c"):
                    with self.subTest(target=name, source=source):
                        command = [sys.executable, "-m", "ziglang", "cc", *flags, "-std=c99", "-Os", "-Wall",
                                   "-Wextra", "-Werror", "-pedantic", f"-I{STUB}", "-DEAT_SCRATCH_BYTES=256",
                                   "-c", str(STUB / source), "-o", str(Path(out) / "x.o")]
                        result = subprocess.run(command, capture_output=True, text=True, check=False)
                        self.assertEqual(result.returncode, 0, result.stderr)


class SerialProfileTests(LiveCase):
    def test_serial_connection_validation(self):
        for connection in ({"transport": "serial"}, {"transport": "serial", "port": "COM3", "baud": 10},
                           {"transport": "usb"}):
            with self.subTest(connection=connection):
                self.edit(lambda d, c=connection: d.update(connection=c))
                with self.assertRaises(ValueError):
                    Profile(self.path)
        self.edit(lambda d: d.update(connection={"transport": "serial", "port": "COM3", "baud": 921600}))
        self.assertEqual(Profile(self.path).transport, "serial")
        self.assertIn('"transport": "serial"', json.dumps(json.loads(self.path.read_text())))


if __name__ == "__main__":
    unittest.main()
