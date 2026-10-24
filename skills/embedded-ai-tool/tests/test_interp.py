"""Real C interpreter, compiler and both memory transports; no hardware evidence."""
import ctypes
import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from embedded_ai_tool import interp, link
from embedded_ai_tool.cli import parser, run
from embedded_ai_tool.core import Profile
from embedded_ai_tool.live import Live, Session
from host_cc import COMPILER, SKIP_REASON, STUB, build

BASE = 0x20000000


def instruction(op, a=0, b=0, c=0, k=0):
    return struct.pack("<BBBBI", op, a, b, c, k)


def image(code, variables=(), params=(), events=(), allow=(), safe=(), tasks=None):
    tasks = [[1, 1, 0, len(code), 0, len(variables), (1 << len(allow)) - 1, 0, 0, 0, 16, 0]] if tasks is None else tasks
    payloads = [interp.pack_rows(tasks), b"".join(code), interp.pack_rows(variables), interp.pack_rows(params),
                interp.pack_rows(events), interp.pack_rows(allow), interp.pack_rows(safe)]
    body, descriptors = bytearray(), []
    for kind, data in enumerate(payloads, 1):
        body.extend(b"\0" * (-(136 + len(body)) % 8))
        descriptors.append([kind, 136 + len(body), len(data), len(data) // interp.ROW_BYTES[kind]])
        body.extend(data)
    return bytes(struct.pack("<4sHHIIII", b"EATI", 1, 136, 136 + len(body), 1, 123, 7)
                 + interp.pack_rows(descriptors) + body)


ALLOW = [1, 1, 1, 1, 0x50000004, 4, 32, 1, 0, 1, 0, 0]
SAFE = [0x50000004, 32, 1, 0]


class MemoryTarget:
    """Same public target interface; each transaction lets the real C poll run."""
    closed = False

    def __init__(self, lib):
        self.lib, self.writes = lib, []

    def read(self, address, width, count):
        result = [self.lib.i_read(address + i * width // 8, width) for i in range(count)]
        self.lib.i_tick(0)
        return result

    def write(self, address, width, values):
        self.writes.append((address, width, list(values)))
        for i, value in enumerate(values):
            self.lib.i_write(address + i * width // 8, width, value)
        self.lib.i_tick(1)

    def increment_if(self, check, expected, address):
        if self.read(check, 32, 1)[0] != expected:
            return False
        self.write(address, 32, [(self.read(address, 32, 1)[0] + 1) & interp.U32])
        return True

    def close(self):
        self.closed = True


class Wire:
    def __init__(self, lib):
        self.lib = lib

    def write(self, data):
        self.lib.t_feed(data, len(data))

    def read(self, count):
        data = ctypes.create_string_buffer(count)
        n = self.lib.t_take(data, count)
        return data.raw[:n]

    def close(self):
        pass


@unittest.skipUnless(COMPILER, SKIP_REASON)
class InterpreterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = build(cls, [STUB / "eat_interp.c", STUB / "eat_ring.c", STUB / "eat_link.c", STUB / "eat_stub_core.c",
                              Path(__file__).with_name("interp_harness.c")], "interp_test", ["-DEAT_INTERP_ENABLE=1"])
        cls.lib.i_memory.restype = ctypes.POINTER(ctypes.c_uint32)
        for name in ("i_read", "i_crc", "i_pin", "i_var", "i_reg", "i_param"):
            getattr(cls.lib, name).restype = ctypes.c_uint32

    def setUp(self):
        self.lib.i_init()
        self.mb = self.lib.i_memory()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        mcu = {"schema_version": 1, "pins": {}, "recipes": {}}
        pins, catalog = {}, {}
        for name, resource, function in (("sense", 0, "adc"), ("load", 1, "gpio_out")):
            address = 0x50000000 + resource * 4
            mcu["pins"][name] = {"functions": {function: {"recipe": name}, "safe": {"recipe": name + "_safe"}}}
            mcu["recipes"][name] = {"steps": [{"op": "write", "address": address, "value": 0}]}
            mcu["recipes"][name + "_safe"] = {"steps": [{"op": "modify", "address": address, "mask": 1, "value": 0}]}
            pins[name] = {"mcu_pin": name, "functions": [function], "safe_function": "safe"}
            catalog[name] = {"id": resource, "address": address, "mask": 1,
                             "functions": {function: 1 if function == "gpio_out" else 2}}
        (self.root / "mcu.json").write_text(json.dumps(mcu))
        self.path = self.root / "profile.json"
        self.data = {"schema_version": 2, "name": "host-test", "byte_order": "little", "project_root": ".",
            "connection": {"port": 6666}, "identity": {"address": 0x50FF0000, "size": 4, "expected_hex": "a1b2c3d4"},
            "read_ranges": [{"address": 0x50FF0000, "size": 4}], "pins": pins,
            "live": {"mailbox": {"address": BASE, "size": 5664}, "mcu_db": "mcu.json",
                     "write_ranges": [{"address": 0x50000000, "size": 64}],
                     "interpreter": {"capability_hash": 123, "resources": catalog}}}
        self.path.write_text(json.dumps(self.data))
        self.live = Live(Profile(self.path), MemoryTarget(self.lib))
        self.program = interp.Program(self.live)
        self.program.boot = 1

    def request(self, command, args):
        return self.program.request(command, args)

    def upload(self, data, crc=None):
        head = self.request("begin", [self.mb[40], len(data), zlib.crc32(data) if crc is None else crc, 1])
        upload = head[46]
        bank = self.mb[22] if self.mb[40] and self.mb[41] == 0 else self.mb[21]
        for offset in range(0, len(data), 128):
            chunk = data[offset:offset + 128]
            self.program.write(bank + offset, 8, list(chunk))
            self.request("chunk", [upload, offset, len(chunk), zlib.crc32(chunk)])
        self.request("verify", [upload])
        for _ in range(200):
            if self.mb[48] != 2:
                break
            self.lib.i_tick(0)
        return upload

    def activate(self, data):
        upload = self.upload(data)
        self.assertEqual(self.mb[48], 3, f"verify error {self.mb[38]}")
        return self.request("commit", [upload, self.mb[40]])

    def ticks(self, count):
        for _ in range(count):
            self.mb[3] += 1
            self.lib.i_tick(1)

    def source(self, tasks=None):
        return {"schema_version": 1, "expected_generation": self.mb[40],
                "params": {"threshold": {"type": "u32", "value": 1800, "min": 50, "max": 4095}},
                "tasks": tasks if tasks is not None else [{"id": "sample", "resources": ["sense"],
                    "trigger": {"kind": "periodic", "period_ms": 10},
                    "steps": [{"op": "analog_read", "pin": "sense", "dst": "value"},
                              {"op": "emit", "channel": "sense", "value": "value"}]}]}

    def compile(self, source):
        return interp.Compiler(self.live).compile(source)

    def test_crc_reference_and_verifier_rejections(self):
        self.assertEqual(self.lib.i_crc(b"123456789", 9), 0xCBF43926)
        cases = [(instruction(0xFF), 3), (instruction(0x26), 8), (instruction(0x41), 8),
                 (instruction(0, a=1), 4), (instruction(1, a=8), 5), (instruction(18, k=99), 6),
                 (instruction(3, k=0), 5), (instruction(33, k=0), 7)]
        for code, error in cases:
            with self.subTest(error=error, code=code):
                self.lib.i_init()
                self.upload(image([code]))
                self.assertEqual((self.mb[48], self.mb[38]), (4, error))
        self.lib.i_init()
        self.upload(image([instruction(127)], allow=[[*ALLOW[:2], 99, *ALLOW[3:]]]))
        self.assertEqual(self.mb[38], 7)

    def test_arithmetic_comparison_branches_and_division_fault(self):
        code = [instruction(1, 0, k=7), instruction(1, 1, k=3), instruction(6, 2, 0, 1),
                instruction(7, 3, 0, 1), instruction(8, 4, 0, 1), instruction(9, 5, 0, 1),
                instruction(10, 6, 0, 1), instruction(11, 7, 0, 1, 2), instruction(52),
                instruction(16, 0, 0, 1, 4), instruction(17, 0, k=12), instruction(1, 2, k=99),
                instruction(52), instruction(18, k=12)]
        self.activate(image(code))
        self.assertEqual([self.lib.i_reg(0, i) for i in range(2, 8)], [10, 4, 21, 2, 1, 4])
        self.ticks(1)
        self.assertEqual((self.lib.i_reg(0, 0), self.lib.i_reg(0, 2)), (1, 10))
        self.lib.i_init()
        self.activate(image([instruction(9, 0, 0, 1)]))
        self.assertEqual((self.mb[13], self.mb[42]), (16, 3))

    def test_timer_set_wait_and_adc_pending_deadline(self):
        self.activate(image([instruction(1, k=5), instruction(48), instruction(49), instruction(1, 1, k=99),
                             instruction(52), instruction(18, k=4)]))
        self.ticks(4)
        self.assertEqual(self.lib.i_reg(0, 1), 0)
        self.ticks(1)
        self.assertEqual(self.lib.i_reg(0, 1), 99)
        self.lib.i_init()
        adc = [1, 2, 0, 2, 0x50000000, 4, 32, 1, 0, 4095, 0, 0]
        self.lib.i_pending(1)
        self.activate(image([instruction(35), instruction(36, 0, 1), instruction(52), instruction(18, k=1)], allow=[adc]))
        self.ticks(100)
        self.assertEqual((self.mb[13], self.mb[42]), (15, 3))

    def test_adc_rate_limit_is_enforced_on_target_without_host_compiler(self):
        adc = [1, 2, 0, 2, 0x50000000, 4, 32, 1, 0, 4095, 10, 100]
        self.activate(image([instruction(35), instruction(36, 0, 1), instruction(52), instruction(18)], allow=[adc]))
        self.ticks(1)
        self.assertEqual((self.mb[13], self.mb[42]), (7, 3))

    def test_pwm_bounds_are_checked_before_port_and_stop_is_safe(self):
        pwm = [1, 3, 1, 3, 0x50000004, 4, 32, 1, 0, 500, 100, 20000]
        code = [instruction(1, 0, k=250), instruction(1, 1, k=1000), instruction(37, 0, 1),
                instruction(52), instruction(18, k=3)]
        self.activate(image(code, allow=[pwm], safe=[SAFE]))
        self.assertEqual(self.lib.i_pwm(1), 250)
        self.request("stop", [1])
        self.assertEqual(self.lib.i_pwm(1), 0)
        self.lib.i_init()
        code[0] = instruction(1, 0, k=501)
        self.activate(image(code, allow=[pwm], safe=[SAFE]))
        self.assertEqual((self.mb[13], self.lib.i_pwm(1)), (7, 0))

    def test_overlap_capacity_and_safe_envelope(self):
        data = bytearray(image([instruction(127)]))
        struct.pack_into("<I", data, 24 + 16 + 4, 136)  # code overlaps tasks
        self.upload(data)
        self.assertEqual(self.mb[38], 1)
        self.upload(image([instruction(127)], safe=[[0x60000000, 32, 1, 0]]))
        self.assertEqual(self.mb[38], 7)
        self.upload(image([instruction(127)], params=[[i, 0, 0, 1, 1] for i in range(9)]))
        self.assertEqual(self.mb[38], 2)

    def test_budget_exceed_and_runtime_double_check(self):
        self.activate(image([instruction(1, k=1), instruction(33), instruction(18, k=2)], allow=[ALLOW], safe=[SAFE]))
        self.assertEqual((self.mb[42], self.mb[13], self.lib.i_pin(1)), (3, 12, 0))
        self.lib.i_init()
        self.activate(image([instruction(52), instruction(1, k=1), instruction(33), instruction(52), instruction(18, k=3)],
                            allow=[ALLOW], safe=[SAFE]))
        self.lib.i_deny(1)
        self.ticks(1)
        self.assertEqual((self.mb[13], self.lib.i_writes(), self.lib.i_pin(1)), (7, 0, 0))

    def test_delay_timer_and_end_safe(self):
        self.activate(image([instruction(1, k=1), instruction(33), instruction(1, k=10), instruction(50),
                             instruction(127)], allow=[ALLOW], safe=[SAFE]))
        self.assertEqual(self.lib.i_pin(1), 1)
        self.ticks(9)
        self.assertEqual(self.lib.i_pin(1), 1)
        self.ticks(1)
        self.assertEqual(self.lib.i_pin(1), 0)

    def test_deadman_is_latched_and_uses_private_safe(self):
        self.activate(image([instruction(1, k=1), instruction(33), instruction(52), instruction(18, k=2)],
                            allow=[ALLOW], safe=[SAFE]))
        self.mb[16] = 0
        self.lib.i_tick(1001)
        self.assertEqual((self.mb[42], self.mb[17], self.lib.i_pin(1)), (2, 1, 0))
        self.assertGreater(self.lib.i_stops(), 1)
        self.mb[3] += 1
        self.lib.i_tick(1)
        self.assertEqual((self.mb[42], self.mb[17]), (2, 1))

    def test_trap_publishes_stopped_snapshot_without_another_poll(self):
        self.activate(image([instruction(1, k=1), instruction(33), instruction(52), instruction(18, k=2)],
                            allow=[ALLOW], safe=[SAFE]))
        self.lib.i_fault(1234)
        self.assertEqual((self.mb[13], self.mb[42], self.mb[45] % 2, self.lib.i_pin(1)), (1234, 3, 0, 0))

    def test_event_overflow_and_message_payload(self):
        self.activate(image([instruction(51, a=0, b=1), instruction(52), instruction(18)],
                            events=[[99, 5, 99, 1, 0, 0]]))
        self.request("message", [1, 99, 1234])
        self.assertEqual(self.lib.i_reg(0, 0), 1234)
        for _ in range(17):
            self.lib.i_event(99, 0)
        self.lib.i_tick(1)
        self.assertEqual((self.mb[42], self.mb[13]), (3, 13))

    def test_crc_failure_and_stale_generation_keep_active(self):
        old = image([instruction(52), instruction(18)])
        self.activate(old)
        crc = self.mb[43]
        self.upload(old, crc=42)
        self.assertEqual((self.mb[48], self.mb[38], self.mb[40], self.mb[43]), (4, 9, 1, crc))
        with self.assertRaisesRegex(ValueError, "STALE_GENERATION"):
            self.request("begin", [0, len(old), zlib.crc32(old), 1])
        self.assertEqual(self.mb[42], 1)

    def test_commit_rechecks_generation_after_parameter_mutation(self):
        old = image([instruction(52), instruction(18)], params=[[99, 10, 0, 100, 1]])
        self.activate(old)
        upload = self.upload(old)
        self.request("param", [1, 99, 20])
        with self.assertRaisesRegex(ValueError, "STALE_GENERATION"):
            self.request("commit", [upload, 1])
        self.assertEqual((self.mb[40], self.mb[43], self.lib.i_param(0)), (2, zlib.crc32(old), 20))
        self.request("abort", [upload])
        self.assertEqual((self.mb[48], self.mb[42]), (0, 1))

    def test_param_set_tick_atomicity_and_bounds(self):
        self.activate(image([instruction(52), instruction(5), instruction(18)], params=[[99, 10, 0, 100, 1]]))
        generation = self.mb[40]
        # Publish without advancing time: ack must wait for the next tick.
        self.mb[28], self.mb[29], self.mb[30] = generation, 99, 20
        self.mb[27], self.mb[26] = 0x16, self.mb[26] + 1
        seq = self.mb[26]
        self.lib.i_tick(0)
        self.assertNotEqual(self.mb[36], seq)
        self.assertEqual((self.lib.i_param(0), self.mb[40]), (10, generation))
        self.ticks(1)
        self.assertEqual((self.mb[36], self.lib.i_param(0), self.mb[40]), (seq, 20, generation + 1))
        with self.assertRaisesRegex(ValueError, "RANGE"):
            self.request("param", [generation + 1, 99, 101])
        self.assertEqual((self.lib.i_param(0), self.mb[40]), (20, generation + 1))

    def test_migration_preserves_vars_and_unchanged_task_wait(self):
        variables = [[1, 10, 1, 1, 0, 0, 100, 1]]
        code = [instruction(1, k=42), instruction(4), instruction(1, k=100), instruction(50), instruction(18, k=2)]
        old = image(code, variables=variables, params=[[99, 10, 0, 100, 1]])
        self.activate(old)
        self.request("param", [1, 99, 20])
        self.activate(old)
        self.assertEqual((self.lib.i_var(0, 0), self.lib.i_param(0)), (42, 10))
        changed = image([instruction(52), instruction(18)], variables=variables)
        self.activate(changed)
        self.assertEqual(self.lib.i_var(0, 0), 42)

    def test_transition_failure_applies_old_and_new_safe_without_generation(self):
        self.activate(image([instruction(1, k=1), instruction(33), instruction(52), instruction(18, k=2)],
                            allow=[ALLOW], safe=[SAFE]))
        candidate = image([instruction(52), instruction(18)], allow=[ALLOW], safe=[SAFE])
        upload = self.upload(candidate)
        self.lib.i_prepare_fail(1)
        with self.assertRaisesRegex(ValueError, "PORT"):
            self.request("commit", [upload, 1])
        self.assertEqual((self.mb[40], self.mb[42], self.lib.i_pin(1)), (1, 3, 0))

    def test_unchanged_task_survives_append_and_delete_with_own_timer(self):
        code = [instruction(1, k=100), instruction(50), instruction(1, 1, k=99), instruction(52), instruction(18, k=3)]
        old = image(code)
        self.activate(old)
        self.ticks(10)
        tasks = [[1, 1, 0, 5, 0, 0, 0, 0, 0, 0, 16, 0], [2, 1, 5, 2, 0, 0, 0, 0, 0, 0, 16, 0]]
        self.activate(image([*code, instruction(52), instruction(18, k=5)], tasks=tasks))
        self.ticks(10)
        self.activate(old)
        self.assertEqual(self.lib.i_reg(0, 1), 0)
        # Upload/verify uses less than 100 simulated ms; the original timer must expire without reset.
        self.ticks(100)
        self.assertEqual(self.lib.i_reg(0, 1), 99)

    def test_commit_keeps_queued_event_for_unchanged_waiter(self):
        data = image([instruction(51, 0, 1), instruction(52), instruction(18)], events=[[99, 5, 99, 1, 0, 0]])
        self.activate(data)
        upload = self.upload(data)
        self.lib.i_event(99, 1234)
        # Publish directly so no intervening transport transaction can drain the event first.
        self.mb[28], self.mb[29] = upload, 1
        self.mb[27], self.mb[26] = 0x13, self.mb[26] + 1
        self.lib.i_tick(1)
        self.assertEqual((self.mb[40], self.mb[37], self.lib.i_reg(0, 0)), (2, 0, 1234))

    def test_event_ring_drops_new_records_and_validates_cursor(self):
        self.activate(image([instruction(1, k=42), instruction(64), instruction(52), instruction(18, k=1)],
                            events=[[1, 1, 1, 1, 0, 0]]))
        first = self.program.events_read()["events"][0]
        self.ticks(100)
        result = self.program.events_read()
        self.assertEqual(result["events"][0], first)
        self.assertGreater(result["dropped"], 0)
        self.assertEqual((self.mb[42], self.mb[13]), (1, 0))
        consumed = self.program.events_read(5, consume=True, execute=True)
        with self.assertRaisesRegex(ValueError, "cursor"):
            self.program.events_read(cursor=consumed["cursor"] - 1)

    def test_event_timestamp_wrap_is_extended_across_cli_connections(self):
        self.activate(image([instruction(1, k=42), instruction(64), instruction(52), instruction(18, k=1)],
                            events=[[1, 1, 1, 1, 0, 0]]))
        for _ in range(2):
            self.mb[3] += 1
            self.lib.i_tick(0x7FFFFF00)
        before = self.program.events_read(32, consume=True, execute=True)
        previous = before["events"][-1]["timestamp_extended"]
        self.mb[3] += 1
        self.lib.i_tick(600)
        reconnect = interp.Program(Live(Profile(self.path), MemoryTarget(self.lib)))
        after = reconnect.events_read(32, cursor=before["cursor"], boot_id=before["boot_id"])
        extended = [row["timestamp_extended"] for row in after["events"]]
        self.assertTrue(all(value >= previous for value in extended))
        self.assertGreater(extended[-1], 2**32)

    def test_old_boot_cursor_is_refused_and_default_read_resets_epoch(self):
        old = self.program.events_read()
        self.lib.i_init()
        self.mb[44] = 2  # the port supplies a different id on reset
        with self.assertRaisesRegex(ValueError, "boot_id"):
            self.program.events_read(cursor=old["cursor"])
        self.assertEqual(self.program.events_read()["boot_id"], 2)
        with self.assertRaisesRegex(ValueError, "boot_id"):
            self.program.events_read(cursor=0, boot_id=1)

    def test_v2_heartbeat_and_legacy_mutation_guards(self):
        self.program.set(self.compile(self.source()))
        self.assertFalse(self.live.stub.heartbeat())
        self.assertTrue(self.live.heartbeat())
        with self.assertRaisesRegex(ValueError, "BUSY_PROGRAM"):
            self.live.poke(self.live.poke_plan(0x50000004, 1))
        with self.assertRaisesRegex(ValueError, "BUSY_PROGRAM"):
            self.live.stub.arm([SAFE])

    def test_timeout_does_not_resend_mutation(self):
        self.program.boot = 1
        target = self.live.target
        original_write = target.write

        def fail(address, width, values):
            original_write(address, width, values)
            if address == BASE + 104:
                raise TimeoutError("uncertain")

        target.write = fail
        with self.assertRaises(TimeoutError):
            self.program.request("stop", [0])
        self.assertEqual(sum(address == BASE + 104 for address, _, _ in target.writes), 1)

    def test_compiler_upload_sampling_param_threshold_pulse_and_removal(self):
        compiled = self.compile(self.source())
        self.assertEqual(self.program.get()["generation"], 0)
        self.program.set(compiled)
        self.lib.i_adc(0, 1000)
        self.ticks(40)
        records = self.program.events_read(32, consume=True, execute=True)
        self.assertTrue(any(r["kind"] == 1 and r["value"] == 1000 for r in records["events"]))
        self.program.mutate("param", 1, "threshold", 1700)
        source = self.source()
        source["params"]["threshold"]["value"] = 1700
        source["tasks"][0]["resources"].append("load")
        source["tasks"][0]["steps"].append({"op": "on_rising_threshold", "value": "value", "param": "threshold",
            "hysteresis": 50, "actions": [{"op": "pulse", "pin": "load", "duration_ms": 3000}]})
        self.program.set(self.compile(source))
        self.lib.i_adc(0, 1900)
        self.ticks(40)
        self.assertEqual(self.lib.i_pin(1), 1)
        self.lib.i_adc(0, 1680)  # above lower bound: no reset
        self.ticks(3010)
        self.assertEqual(self.lib.i_pin(1), 0)
        self.lib.i_adc(0, 1900)
        self.ticks(40)
        self.assertEqual(self.lib.i_pin(1), 0)
        self.lib.i_adc(0, 1600)
        self.ticks(40)
        self.lib.i_adc(0, 1900)
        self.ticks(40)
        self.assertEqual(self.lib.i_pin(1), 1)
        self.program.set(self.compile(self.source()))
        self.assertEqual(self.lib.i_pin(1), 0)
        self.ticks(20)
        self.assertEqual(self.mb[42], 1)

    def test_serial_upload_uses_same_c_mailbox(self):
        self.data["connection"] = {"transport": "serial", "port": "TEST", "timeout_s": 1}
        self.path.write_text(json.dumps(self.data))
        profile = Profile(self.path)
        target = link.SerialTarget(profile, Wire(self.lib))
        live = Live(profile, target)
        compiled = interp.Compiler(live).compile(self.source())
        program = interp.Program(live)
        self.assertEqual(program.set(compiled)["active_crc"], compiled.crc)
        self.assertEqual(program.get()["tasks"][0][0], interp.ident("sample"))

    def test_cli_and_mcp_plans_are_offline(self):
        source = self.source()
        args = parser().parse_args(["--profile", str(self.path), "program", "set", "--json", json.dumps(source)])
        with patch("embedded_ai_tool.core.open_target", side_effect=AssertionError("offline")):
            self.assertFalse(run(args)["executed"])
        from embedded_ai_tool.mcp_server import TOOLS

        for name in ("program_get", "program_set", "task_add", "task_remove", "param_set", "events_read"):
            self.assertIn(name, TOOLS)
        args._session = Session(Profile(self.path), self.live.target)
        args.execute = True
        self.assertTrue(run(args)["executed"])
        args = parser().parse_args(["--profile", str(self.path), "program", "task-remove", "sample",
                                    "--expected-generation", "1", "--execute"])
        args._session = Session(Profile(self.path), self.live.target)
        self.assertTrue(run(args)["executed"])

    def test_host_rejects_schema_limits_ownership_and_unknown_fields(self):
        for modify in (lambda s: s.update(deadman=False), lambda s: s.update(unknown=1),
                       lambda s: s["tasks"][0]["trigger"].update(period_ms=0),
                       lambda s: s["tasks"].append(s["tasks"][0]),
                       lambda s: s["tasks"][0]["steps"].append({"op": "irq_bind"})):
            source = self.source()
            modify(source)
            with self.assertRaises(ValueError):
                self.compile(source)
        source = self.source([{"id": "a", "resources": ["load"], "steps": [{"op": "gpio_write", "pin": "load", "value": 2}]}])
        with self.assertRaises(ValueError):
            self.compile(source)


@unittest.skipUnless(importlib.util.find_spec("ziglang"), "optional: ziglang çapraz derleyicisi yok")
class InterpreterPortabilityTests(unittest.TestCase):
    def test_c99_sources_on_three_architectures_and_feature_configs(self):
        targets = [("-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0"),
                   ("-target", "riscv32-freestanding-none"), ("-target", "mipsel-freestanding-none")]
        with tempfile.TemporaryDirectory() as output:
            for target in targets:
                for config in ([], ["-DEAT_INTERP_ADC=0", "-DEAT_INTERP_PWM=0", "-DEAT_INTERP_DIV=0",
                                    "-DEAT_INTERP_TASKS=2", "-DEAT_INTERP_VARS=8", "-DEAT_INTERP_RING_RECORDS=0"]):
                    for source in ("eat_interp.c", "eat_ring.c", "eat_stub_core.c", "eat_embed.c"):
                        result = subprocess.run([sys.executable, "-m", "ziglang", "cc", *target, *config,
                            "-DEAT_INTERP_ENABLE=1", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", f"-I{STUB}", "-c",
                            str(STUB / source), "-o", str(Path(output) / "check.o")], capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(COMPILER, SKIP_REASON)
class BudgetDeferralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = build(cls, [STUB / "eat_interp.c", STUB / "eat_ring.c", STUB / "eat_link.c", STUB / "eat_stub_core.c",
                              Path(__file__).with_name("interp_harness.c")], "interp_budget_test",
                        ["-DEAT_INTERP_ENABLE=1", "-DEAT_INTERP_BUDGET=4"])
        cls.lib.i_memory.restype = ctypes.POINTER(ctypes.c_uint32)

    def test_total_budget_defers_without_fault_and_round_robin_advances(self):
        self.lib.i_init()
        mb = self.lib.i_memory()
        target = MemoryTarget(self.lib)

        def request(command, args):
            for index, value in enumerate([*args, *([0] * (8 - len(args)))]):
                mb[28 + index] = value
            mb[27] = interp.COMMAND[command]
            mb[26] += 1
            self.lib.i_tick(1)
            self.assertEqual((mb[36], mb[37]), (mb[26], 0), f"error {mb[38]}")

        tasks, code = [], []
        for index in range(4):
            start = len(code)
            tasks.append([index + 1, 1, start, 3, 0, 0, 0, 0, 0, 0, 16, 0])
            code += [instruction(1, k=index + 1), instruction(52), instruction(18, k=start)]
        data = image(code, tasks=tasks)
        request("begin", [0, len(data), zlib.crc32(data), 1])
        upload = mb[46]
        for offset in range(0, len(data), 128):
            chunk = data[offset:offset + 128]
            target.write(BASE + mb[21] + offset, 8, list(chunk))
            request("chunk", [upload, offset, len(chunk), zlib.crc32(chunk)])
        request("verify", [upload])
        for _ in range(200):
            if mb[48] != 2:
                break
            self.lib.i_tick(0)
        self.assertEqual(mb[48], 3)
        request("commit", [upload, 0])
        self.assertEqual([self.lib.i_reg(i, 0) for i in range(4)], [1, 2, 0, 0])
        for _ in range(10):
            self.lib.i_tick(1)
        self.assertEqual([self.lib.i_reg(i, 0) for i in range(4)], [1, 2, 3, 4])
        self.assertEqual((mb[42], mb[13]), (1, 0))
