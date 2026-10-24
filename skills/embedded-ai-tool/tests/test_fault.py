"""Recorded SCB and exception-frame evidence, without hardware."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from embedded_ai_tool.arch import fault_evidence
from embedded_ai_tool.arch.cortex_m import REGISTERS, exception_return
from embedded_ai_tool.cli import parser, run
from embedded_ai_tool.core import Profile
from test_live import UID_ADDRESS, LiveCase


class FaultTests(LiveCase):
    def setUp(self):
        super().setUp()
        self.edit(lambda d: (d["live"].update(arch="cortex-m"),
                             d["read_ranges"].extend([{ "address": "0x20001000", "size": "0x2000"},
                                                      {"address": "0xE000ED00", "size": "0x100"}])))
        self.rpc.halted = False
        self.rpc.registers = {"sp": 0x20001000, "msp": 0x20001000, "psp": 0x20002000,
                              "lr": 0xFFFFFFF9, "pc": 0x10000080, "xpsr": 0x01000003}
        original = self.rpc.call

        def call(script):
            body = script.partition("{error IDENTITY_MISMATCH}}; ")[2]
            if "curstate" in body:
                # Exercise the real guarded target helpers with recorded RPC replies.
                original(self.openocd(self.rpc).guard + f"read_memory {UID_ADDRESS} 8 4")
                self.rpc.scripts.append(script)
                if "get_reg" in body:
                    return " ".join(hex(self.rpc.registers[n]) for n in ("sp", "lr", "pc", "xpsr", "msp", "psp")) if self.rpc.halted else ""
                if not self.rpc.halted:
                    raise ValueError("CORE_NOT_HALTED")
                return original(self.openocd(self.rpc).guard + body.split("; ", 1)[1])
            return original(script)

        self.rpc.call = call

    def collect(self):
        return fault_evidence(self.openocd(self.rpc), Profile(self.path))

    def test_each_fault_flag_and_address_validity(self):
        flags = {0: "IACCVIOL", 1: "DACCVIOL", 3: "MUNSTKERR", 4: "MSTKERR", 5: "MLSPERR",
                 7: "MMARVALID", 8: "IBUSERR", 9: "PRECISERR", 10: "IMPRECISERR", 11: "UNSTKERR",
                 12: "STKERR", 13: "LSPERR", 15: "BFARVALID", 16: "UNDEFINSTR", 17: "INVSTATE",
                 18: "INVPC", 19: "NOCP", 20: "STKOF", 24: "UNALIGNED", 25: "DIVBYZERO"}
        for register, cases in (("CFSR", flags), ("HFSR", {1: "VECTTBL", 30: "FORCED", 31: "DEBUGEVT"})):
            for bit, flag in cases.items():
                with self.subTest(register=register, bit=bit):
                    self.rpc.put(REGISTERS[register], 32, 1 << bit)
                    self.assertEqual(self.collect()["flags"][register], [flag])
            self.rpc.put(REGISTERS[register], 32, 0)
        for valid in (0, 1 << 7, 1 << 15, (1 << 7) | (1 << 15)):
            self.rpc.put(REGISTERS["CFSR"], 32, valid)
            for name, bit in (("MMFAR", 7), ("BFAR", 15)):
                self.rpc.put(REGISTERS[name], 32, 0x20000044)
                evidence = self.collect()["fault_addresses"][name]
                self.assertEqual(evidence["valid"], bool(valid & (1 << bit)))
                self.assertEqual(evidence["address"], 0x20000044 if valid & (1 << bit) else None)
        self.assertFalse(any("write_memory" in s for s in self.rpc.scripts))

    def test_all_exception_return_variants(self):
        self.rpc.halted = True
        for value in (0xFFFFFFF1, 0xFFFFFFF9, 0xFFFFFFFD, 0xFFFFFFE1, 0xFFFFFFE9, 0xFFFFFFED):
            with self.subTest(value=hex(value)):
                self.rpc.registers["lr"] = value
                decoded = exception_return(value)
                address = self.rpc.registers[decoded["stack"]]
                for i, word in enumerate([1, 2, 3, 4, 12, 0x10000001, 0x10000040, 0x01000000]):
                    self.rpc.put(address + 4 * i, 32, word)
                if decoded["extended"]:
                    self.rpc.put(address + 72 + 24, 32, 0xBAD00000)
                frame = self.collect()["frame"]
                self.assertTrue(frame["available"], frame)
                self.assertEqual(frame["address"], address)
                self.assertEqual((frame["stacked_lr"], frame["stacked_pc"]), (0x10000001, 0x10000040))
        self.rpc.registers["lr"] = 0x10000001
        self.assertFalse(self.collect()["frame"]["available"])
        self.rpc.registers["lr"], self.rpc.registers["xpsr"] = 0xFFFFFFF9, 0x01000000
        self.assertFalse(self.collect()["frame"]["available"])

    def test_running_serial_policy_and_unknown_arch(self):
        self.assertIn("halt", self.collect()["frame"]["note"])
        target = self.openocd(self.rpc)
        target.kind = "serial"
        self.assertIn("halt", fault_evidence(target, Profile(self.path))["frame"]["note"])
        self.edit(lambda d: d["read_ranges"].pop())
        with self.assertRaisesRegex(ValueError, "0xE000ED00"):
            self.collect()
        self.edit(lambda d: d["live"].update(arch="unknown"))
        self.assertIn("desteklenmiyor", self.collect()["note"])
        self.edit(lambda d: d["live"].pop("arch"))
        self.assertFalse(self.collect()["supported"])

    def test_frame_policy_and_scb_side_effect_refusal(self):
        self.rpc.halted = True
        self.rpc.registers["msp"] = 0x60000000
        self.assertIn("Okuma izni", self.collect()["frame"]["error"])
        self.edit(lambda d: d["live"].update(side_effect_ranges=[{"address": "0xE000ED28", "size": 4}]))
        self.rpc.scripts.clear()
        with self.assertRaisesRegex(ValueError, "SCB okuma reddedildi"):
            self.collect()
        self.assertEqual(self.rpc.scripts, [])

    def test_cli_and_automatic_ram_fault_evidence(self):
        from embedded_ai_tool import core

        with patch.object(core, "RPC", return_value=self.rpc):
            args = parser().parse_args(["--profile", str(self.path), "fault"])
            self.assertTrue(run(args)["supported"])
        self.rpc.fault = True
        with self.assertRaisesRegex(ValueError, "fault") as caught:
            self.live().ram_run(0x20000200, [], 1)
        message, evidence = str(caught.exception).split("; fault_evidence=", 1)
        self.assertTrue(message.startswith("RAM parçası hata verdi: fault, error=0x"))
        self.assertTrue(json.loads(evidence)["supported"])
        self.assertEqual(evidence, json.dumps(json.loads(evidence), separators=(",", ":")))
        self.edit(lambda d: d["read_ranges"].pop())
        with self.assertRaisesRegex(ValueError, "fault") as caught:
            self.live().ram_run(0x20000200, [], 1)
        evidence = json.loads(str(caught.exception).split("; fault_evidence=", 1)[1])
        self.assertIn("0xE000ED00", evidence["error"])


if __name__ == "__main__":
    unittest.main()
