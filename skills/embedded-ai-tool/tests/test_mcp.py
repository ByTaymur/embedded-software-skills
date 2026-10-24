"""MCP bridge tests: JSON-RPC over stdio driven end to end against the fake OpenOCD of test_live."""
import argparse
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from embedded_ai_tool import core as core_module
from embedded_ai_tool import mcp_server
from embedded_ai_tool.core import Profile
from embedded_ai_tool.live import WORD
from test_live import BOX, GPIO, FakeRPC, LiveCase

INIT = {"jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}


def call(mid, name, arguments=None):
    return {"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}}


class McpTests(LiveCase):
    def converse(self, *messages, rpc=None, connect_error=None):
        """Run one server lifetime; returns {id: response} and the RPC constructor mock."""
        base = argparse.Namespace(profile=self.path, session_dir=self.root / "s")
        stdin = io.StringIO("".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in messages))
        stdout = io.StringIO()
        target = rpc or self.rpc
        with patch.object(core_module, "RPC", side_effect=connect_error, return_value=target) as factory, \
                contextlib.redirect_stderr(io.StringIO()):
            self.summary = mcp_server.serve_mcp(base, Profile(self.path), stdin, stdout)
        lines = stdout.getvalue().splitlines()
        replies = [json.loads(line) for line in lines]  # stdout must be pure JSON-RPC
        return {r.get("id"): r for r in replies}, factory

    def payload(self, response):
        return json.loads(response["result"]["content"][0]["text"])

    def test_handshake_and_tool_list_need_no_board(self):
        replies, factory = self.converse(INIT, {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                         {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                         {"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", replies[0]["result"]["capabilities"])
        tools = {t["name"]: t for t in replies[1]["result"]["tools"]}
        self.assertTrue({"peek", "poke", "pin_apply", "safe_state", "ram_run"} <= set(tools))
        self.assertTrue(tools["peek"]["annotations"]["readOnlyHint"])
        self.assertTrue(tools["pin_apply"]["annotations"]["destructiveHint"])
        self.assertEqual(replies[2]["result"], {})
        self.assertEqual(len(replies), 3)  # the notification got no answer
        factory.assert_not_called()

    def test_plans_stay_offline_and_execute_reaches_the_target(self):
        replies, factory = self.converse(
            INIT,
            call(1, "pin_apply", {"pin": "LED", "function": "gpio_out", "params": {"level": 1}}),
            call(2, "pin_list"),
            call(3, "peek", {"address": "0x50FF0000", "width": 8}),
            call(4, "pin_apply", {"pin": "LED", "function": "gpio_out", "params": {"level": 1}, "execute": True}),
            call(5, "stub_status"))
        plan = self.payload(replies[1])
        self.assertTrue(plan["ok"])
        self.assertFalse(plan["result"]["executed"])
        self.assertTrue(self.payload(replies[2])["ok"])
        self.assertEqual(self.payload(replies[3])["result"]["values"], ["0xa1"])
        applied = self.payload(replies[4])
        self.assertTrue(applied["ok"], applied)
        self.assertEqual(self.rpc.get(GPIO) >> 10 & 3, 1)
        self.assertTrue(self.rpc.get(BOX + 4 * WORD["armed"]))
        self.assertTrue(self.payload(replies[5])["result"]["armed"])
        self.assertEqual(factory.call_count, 1)  # one connection, opened by the first board access
        self.assertTrue(Path(applied["record"]).exists())

    def test_errors_are_reported_to_the_model(self):
        replies, _ = self.converse(
            INIT,
            call(1, "no_such_tool"),
            call(2, "peek", {"address": "0x50FF0000", "bogus": 1}),
            call(3, "peek", {"address": True}),
            call(4, "poke", {"address": "0x1000", "value": 1, "execute": True}),
            '{"jsonrpc": "2.0", "id": 5, "method": "resources/list"}',
            "not json")
        self.assertEqual(replies[1]["error"]["code"], -32602)
        for mid in (2, 3, 4):
            with self.subTest(mid=mid):
                self.assertTrue(replies[mid]["result"]["isError"])
        self.assertIn("Yazma izni yok", self.payload(replies[4])["error"])
        self.assertEqual(replies[5]["error"]["code"], -32601)
        self.assertEqual(replies[None]["error"]["code"], -32700)

    def test_missing_openocd_is_a_tool_error_not_a_crash(self):
        replies, _ = self.converse(INIT, call(1, "target_identity"),
                                   connect_error=ConnectionRefusedError("refused"))
        result = self.payload(replies[1])
        self.assertFalse(result["ok"])
        self.assertIn("OpenOCD'ye bağlanılamadı", result["error"])

    def test_reconnects_after_a_broken_connection(self):
        first, second = FakeRPC(), FakeRPC()
        first.closed = True  # e.g. a timeout closed the stream during an earlier call
        base = argparse.Namespace(profile=self.path, session_dir=self.root / "s")
        bridge = mcp_server.Bridge(base, Profile(self.path), io.StringIO())
        bridge.session.attach(self.openocd(first))
        with patch.object(core_module, "RPC", return_value=second):
            result = self.payload({"result": bridge.call("peek", {"address": "0x50FF0000", "width": 8})})
        self.assertTrue(result["ok"])
        self.assertIs(bridge.session.target.rpc, second)

    def test_heartbeat_only_after_connecting_and_only_with_the_stub(self):
        base = argparse.Namespace(profile=self.path, session_dir=self.root / "s")
        bridge = mcp_server.Bridge(base, Profile(self.path), io.StringIO())
        bridge.beat()  # not connected yet: nothing to do, no connection opened
        rpc = FakeRPC(stub=False)
        bridge.session.attach(self.openocd(rpc))
        with contextlib.redirect_stderr(io.StringIO()) as err:
            bridge.beat()
        self.assertIn("stub_missing", err.getvalue())
        self.assertEqual(rpc.get(BOX + 4 * WORD["host_hb"]), 0)
        bridge.session.attach(self.openocd(self.rpc))
        bridge.beat()
        self.assertEqual(self.rpc.get(BOX + 4 * WORD["host_hb"]), 1)

    def test_openocd_autostart_only_when_the_profile_opts_in(self):
        base = argparse.Namespace(profile=self.path, session_dir=self.root / "s")
        refused = ConnectionRefusedError("refused")
        bridge = mcp_server.Bridge(base, Profile(self.path), io.StringIO())
        with patch.object(core_module, "RPC", side_effect=refused), \
                patch.object(mcp_server.subprocess, "Popen") as popen, self.assertRaises(OSError):
            bridge.connect()
        popen.assert_not_called()

        self.edit(lambda d: d.update(openocd={"executable": "openocd", "autostart": True,
                                              "config_files": ["interface/stlink.cfg", "target/stm32f7x.cfg"]}))
        bridge = mcp_server.Bridge(base, Profile(self.path), io.StringIO())
        with patch.object(core_module, "RPC", side_effect=[refused, refused, self.rpc]), \
                patch.object(mcp_server.subprocess, "Popen") as popen, patch.object(mcp_server.time, "sleep"), \
                contextlib.redirect_stderr(io.StringIO()):
            popen.return_value.poll.return_value = None
            bridge.connect()
            bridge.stop_openocd()
        argv = popen.call_args.args[0]
        self.assertEqual(argv[:5], ["openocd", "-f", "interface/stlink.cfg", "-f", "target/stm32f7x.cfg"])
        self.assertIs(bridge.session.target.rpc, self.rpc)
        popen.return_value.terminate.assert_called_once()

    def test_watch_table_heartbeat_and_clean_stdout(self):
        self.edit(lambda d: (d.update(variables={"counter": {"address": "0x50000004", "type": "u32"}}),
                             d["read_ranges"].append({"address": "0x50000000", "size": "0x100"})))
        now = [0.0]

        def sleep(seconds):
            now[0] += seconds
            self.rpc.put(GPIO + 4, 32, round(now[0] * 100))

        out = io.StringIO()
        with patch("embedded_ai_tool.live.time.monotonic", side_effect=lambda: now[0]), \
                patch("embedded_ai_tool.live.time.sleep", side_effect=sleep), contextlib.redirect_stdout(out):
            replies, _ = self.converse(INIT, call(1, "watch_variables",
                                                {"names": ["counter"], "samples": 3, "interval_ms": 500}))
        result = self.payload(replies[1])["result"]
        self.assertEqual(result["columns"], ["t_ms", "counter"])
        self.assertEqual([r[0] for r in result["rows"]], [0, 500, 1000])
        self.assertEqual(result["min_max"]["counter"], {"min": 0, "max": 100})
        self.assertGreater(self.rpc.get(BOX + 4 * WORD["host_hb"]), 2)
        self.assertEqual(out.getvalue(), "")
        self.assertTrue(result["complete"])

    def test_watch_limits_policy_and_fault_tool(self):
        self.edit(lambda d: (d.update(variables={"counter": {"address": "0x50000004", "type": "u32"}}),
                             d["read_ranges"].append({"address": "0x50000000", "size": "0x100"})))
        invalid = ({"samples": 0}, {"samples": 201}, {"interval_ms": 9}, {"interval_ms": 5001},
                   {"samples": 200, "interval_ms": 5000}, {"samples": True}, {"names": []})
        for extra in invalid:
            with self.subTest(extra=extra):
                replies, _ = self.converse(INIT, call(1, "watch_variables", {"names": ["counter"], **extra}))
                self.assertTrue(replies[1]["result"]["isError"])
        self.edit(lambda d: d["live"].update(side_effect_ranges=[{"address": "0x50000004", "size": 4}]))
        replies, _ = self.converse(INIT, call(1, "watch_variables", {"names": ["counter"], "samples": 1}),
                                   call(2, "fault_evidence"))
        self.assertIn("Okuma izni", self.payload(replies[1])["error"])
        self.assertIn("desteklenmiyor", self.payload(replies[2])["result"]["note"])
        self.assertFalse(any("halt" in s or "reset" in s for s in self.rpc.scripts))
        self.assertFalse(mcp_server.TOOLS["fault_evidence"]["mutating"])
        self.assertFalse(mcp_server.TOOLS["watch_variables"]["mutating"])

    def test_unknown_fault_arch_stays_offline(self):
        replies, factory = self.converse(INIT, call(1, "fault_evidence"),
                                         connect_error=ConnectionRefusedError("refused"))
        self.assertFalse(self.payload(replies[1])["result"]["supported"])
        factory.assert_not_called()

    def test_watch_stops_at_deadline(self):
        self.edit(lambda d: (d.update(variables={"counter": {"address": "0x50000004", "type": "u32"}}),
                             d["read_ranges"].append({"address": "0x50000000", "size": "0x100"})))
        live = self.live()
        now = [0.0]
        original = live.device.snapshot

        def read(names):
            values = original(names)
            now[0] += 20
            return values

        with patch("embedded_ai_tool.live.time.monotonic", side_effect=lambda: now[0]), \
                patch.object(live.device, "snapshot", side_effect=read):
            result = live.watch_variables(["counter"], 4, 10)
        self.assertFalse(result["complete"])
        self.assertLess(result["samples"], 4)
        self.assertLessEqual(now[0], 60)

    def test_param_and_argument_translation(self):
        argv = mcp_server.TOOLS["pin_apply"]["argv"]({"pin": "LED", "function": "pwm",
                                                      "params": {"freq": 1000, "duty_permille": 250},
                                                      "execute": True})
        self.assertEqual(argv, ["pin", "apply", "LED", "pwm", "--param", "freq=1000",
                                "--param", "duty_permille=250", "--execute"])
        argv = mcp_server.TOOLS["poke"]["argv"]({"address": 0x50000004, "value": 1, "verify": False})
        self.assertEqual(argv, ["poke", str(0x50000004), "1", "--width", "32", "--no-verify"])
        argv = mcp_server.TOOLS["ram_run"]["argv"]({"args": [3, "0x10"], "execute": True})
        self.assertEqual(argv, ["ram", "run", "--arg", "3", "--arg", "0x10", "--timeout", "10", "--execute"])


if __name__ == "__main__":
    unittest.main()
