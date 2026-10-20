import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from embedded_ai_tool.cli import init_project, parser, run
from embedded_ai_tool.core import RPC, Device, Profile, rpc_script, tcl_string


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "board.json"
        self.data = {"schema_version": 1, "name": "fixture", "byte_order": "little",
                     "connection": {"host": "127.0.0.1", "port": 6666},
                     "identity": {"address": "0x1000", "size": 4, "expected_hex": "01020304"},
                     "read_ranges": [{"address": "0x1000", "size": "0x2000"}],
                     "variables": {"counter": {"address": "0x2000", "type": "u32", "writable": True,
                                               "min": 0, "max": 100}},
                     "build": {"argv": ["cmake", "--build", "build"]}}

    def profile(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        return Profile(self.path)

    def test_profile_range_and_limits(self):
        p = self.profile()
        d = Device(p, None)
        self.assertEqual(d.write_plan("counter", "42")["bytes_hex"], "2a000000")
        for bad in ("101", "-1"):
            with self.assertRaises(ValueError):
                d.write_plan("counter", bad)
        with self.assertRaises(ValueError):
            p.check_read(0x2fff, 4)

    def test_write_denied_without_whitelist(self):
        self.data["variables"]["counter"]["writable"] = False
        with self.assertRaises(ValueError):
            Device(self.profile(), None).write_plan("counter", "1")

    def test_invalid_uid_and_duplicate_keys(self):
        self.data["identity"]["expected_hex"] = "00000000"
        with self.assertRaises(ValueError):
            self.profile()
        self.path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaises(ValueError):
            Profile(self.path)

    def test_read_decodes_and_checks_identity_in_same_call(self):
        rpc = Mock()
        rpc.call.return_value = "0x2a"
        self.assertEqual(Device(self.profile(), rpc).snapshot(["counter"]), {"counter": 42})
        script = rpc.call.call_args.args[0]
        self.assertLess(script.index("IDENTITY_MISMATCH"), script.index("read_memory 8192"))
        self.assertIn("foreach", script)
        self.assertIn("read_memory 8192 32 1", script)

    def test_short_read_rejected(self):
        rpc = Mock()
        rpc.call.return_value = ""
        with self.assertRaises(ValueError):
            Device(self.profile(), rpc).snapshot(["counter"])

    def test_flash_verify_checks_every_byte(self):
        p = self.profile()
        p.data["flash_ranges"] = [{"address": 0x2000, "size": 300}]
        image = Mock(sha="test")
        image.regions.return_value = [(0x2000, b"a" * 300)]
        p.image = image
        d = Device(p, None)
        d.read = Mock(side_effect=[b"a" * 256, b"a" * 44])
        self.assertEqual(d.verify()["verified_bytes"], 300)
        self.assertEqual(d.read.call_args_list[1].args, (0x2100, 44))
        d.read = Mock(return_value=b"b" * 256)
        with self.assertRaises(ValueError):
            d.verify()

    def test_failed_build_verification_prevents_write(self):
        rpc = Mock()
        d = Device(self.profile(), rpc)
        plan = d.write_plan("counter", "1")
        d.verify = Mock(side_effect=ValueError("mismatch"))
        with self.assertRaises(ValueError):
            d.write(plan)
        rpc.call.assert_not_called()

    def test_mutation_timeout_never_retried(self):
        rpc = Mock()
        rpc.call.side_effect = TimeoutError("uncertain")
        d = Device(self.profile(), rpc)
        d.verify = Mock(return_value={})
        with self.assertRaises(TimeoutError):
            d.write(d.write_plan("counter", "1"))
        self.assertEqual(rpc.call.call_count, 1)
        self.assertIn("write_memory 8192 32 {1}", rpc.call.call_args.args[0])

    def test_dry_run_does_not_connect(self):
        self.profile()
        args = parser().parse_args(["--profile", str(self.path), "write", "counter", "7"])
        self.assertFalse(run(args)["executed"])
        args = parser().parse_args(["--profile", str(self.path), "build"])
        self.assertEqual(run(args)["plan"]["argv"], ["cmake", "--build", "build"])

    def test_offline_build_does_not_require_hardware_identity(self):
        self.data.pop("identity")
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        args = parser().parse_args(["--profile", str(self.path), "build"])
        self.assertFalse(run(args)["executed"])

    def test_bad_hash_is_not_cached_as_valid(self):
        self.data["artifact"] = {"path": "test.elf", "sha256": "expected"}
        p = self.profile()
        with patch("embedded_ai_tool.core.Image", return_value=Mock(sha="wrong")):
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "SHA256"):
                    p.artifact()
        self.assertIsNone(p.image)

    def test_nonfinite_measurement_returns_diagnostic_error(self):
        self.data["variables"]["counter"]["type"] = "f32"
        rpc = Mock()
        rpc.call.return_value = "0x7fc00000"
        with self.assertRaisesRegex(ValueError, "raw_hex=0000c07f"):
            Device(self.profile(), rpc).snapshot(["counter"])

    def test_openocd_failure_is_not_success_and_port_is_used(self):
        self.data["openocd"] = {"config_files": ["board.cfg"]}
        self.data["connection"]["port"] = 7666
        self.profile()
        args = parser().parse_args(["--profile", str(self.path), "openocd"])
        self.assertIn("tcl_port 7666", run(args)["plan"]["argv"])
        args.execute = True
        with patch("embedded_ai_tool.cli.subprocess.run", return_value=Mock(returncode=7)):
            with self.assertRaisesRegex(ValueError, "OpenOCD başarısız"):
                run(args)

    def test_symbol_read_verifies_running_image_before_measurement(self):
        self.data["variables"]["counter"] = {"symbol": "counter", "type": "u32"}
        self.profile()
        args = parser().parse_args(["--profile", str(self.path), "read", "counter"])
        with patch("embedded_ai_tool.cli.RPC"), patch("embedded_ai_tool.cli.Device") as device:
            device.return_value.verify.side_effect = ValueError("build mismatch")
            with self.assertRaisesRegex(ValueError, "build mismatch"):
                run(args)
            device.return_value.snapshot.assert_not_called()

    def test_flash_uses_pinned_bytes_even_if_original_changes(self):
        self.data["openocd"] = {"shared_filesystem": True}
        self.data["flash_ranges"] = [{"address": 0x2000, "size": 16}]
        self.profile()
        args = parser().parse_args(["--profile", str(self.path), "--session-dir", str(self.root), "flash", "--execute"])
        original = self.root / "original.elf"
        original.write_bytes(b"changed-after-approval")
        image = Mock(path=original, sha="pinned", raw=b"verified-build")
        with patch("embedded_ai_tool.cli.Profile.artifact", return_value=image), patch("embedded_ai_tool.cli.RPC") as rpc:
            rpc.return_value.call.return_value = ""
            result = run(args)
        self.assertEqual(Path(result["staged_image"]).read_bytes(), b"verified-build")
        self.assertNotIn(original.as_posix(), rpc.return_value.call.call_args.args[0])

    def test_template_never_overwrites(self):
        init_project(self.root / "new", "board")
        with self.assertRaises(FileExistsError):
            init_project(self.root / "new", "board")

    def test_tcl_paths_are_data(self):
        self.assertEqual(tcl_string('$x[exit];"\\'), '"\\$x\\[exit\\];\\"\\\\"')
        with self.assertRaises(ValueError):
            tcl_string("bad\x1apath")

    @unittest.skipUnless(shutil.which("openocd"), "OpenOCD bulunamadı; offline Jim testi atlandı")
    def test_real_openocd_interpreter_without_hardware(self):
        guard = Device(self.profile(), None).guard()
        script = ('proc read_memory {addr width count} {return {0x01 0x02 0x03 0x04}}; ' + guard +
                  'echo UID_GUARD_OK; echo ' + tcl_string('test/$x/[exit];file.elf') +
                  '; proc read_memory {addr width count} {return {9 9 9 9}}; '
                  'if {![catch {' + guard + '} why]} {error guard_failed}; echo $why')
        result = subprocess.run([shutil.which("openocd"), "-c", "noinit", "-c", script, "-c", "shutdown"],
                                capture_output=True, text=True, timeout=5, check=False)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("UID_GUARD_OK", output)
        self.assertIn("test/$x/[exit];file.elf", output)
        self.assertIn("IDENTITY_MISMATCH", output)

    @unittest.skipUnless(shutil.which("openocd"), "OpenOCD bulunamadı; offline Jim testi atlandı")
    def test_rpc_wrapper_preserves_unbalanced_braces_and_substitutions(self):
        # Use the actual wrapper and Jim interpreter; this used to fail with an
        # unmatched brace in an otherwise correctly quoted filename.
        for filename in ('unbalanced}file.elf', 'unbalanced{file.elf', '$x[error injected];"file.elf'):
            script = rpc_script("set filename " + tcl_string(filename))
            command = "echo [" + script + "]"
            result = subprocess.run([shutil.which("openocd"), "-c", "noinit", "-c", command, "-c", "shutdown"],
                                    capture_output=True, text=True, timeout=5, check=False)
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            self.assertIn("OK\n" + filename, output.replace("\r\n", "\n"))


class ProtocolTests(unittest.TestCase):
    def test_fragmented_frame_and_error(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        self.addCleanup(server.close)
        received = []

        def serve():
            conn, _ = server.accept()
            with conn:
                for response in (b"OK\n1 2\x1a", b"ERROR\nIDENTITY_MISMATCH\x1a"):
                    data = b""
                    while b"\x1a" not in data:
                        data += conn.recv(4096)
                    received.append(data)
                    conn.sendall(response[:3])
                    conn.sendall(response[3:])

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        rpc = RPC({"host": "127.0.0.1", "port": server.getsockname()[1], "timeout_s": 2})
        self.addCleanup(rpc.close)
        self.assertEqual(rpc.call("read_memory 4096 8 2"), "1 2")
        with self.assertRaisesRegex(ValueError, "IDENTITY_MISMATCH"):
            rpc.call("read_memory 4096 8 2")
        worker.join(2)
        self.assertEqual(len(received), 2)
        self.assertIn(b"catch", received[0])


if __name__ == "__main__":
    unittest.main()
