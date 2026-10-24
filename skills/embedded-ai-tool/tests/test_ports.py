"""Compile architecture examples, including assembly, without linking board hooks.

ESP-IDF is excluded: its SDK, FreeRTOS headers and Xtensa toolchain are not in this repo.
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STUB = Path(__file__).resolve().parents[1] / "stub"


@unittest.skipUnless(importlib.util.find_spec("ziglang"), "optional: ziglang cross compiler unavailable")
class ExamplePortCompileTests(unittest.TestCase):
    def test_freestanding_ports(self):
        ports = (
            ("cortex-m", "eat_port_cortex_m.c", ("-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0")),
            ("cortex-m", "main_example.c", ("-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0")),
            ("riscv", "eat_port_riscv.c", ("-target", "riscv32-freestanding-none")),
            ("riscv", "eat_port_riscv.c", ("-target", "riscv32-freestanding-none", "-DEAT_RISCV_USE_TIME")),
            ("pic32", "eat_port_pic32.c", ("-target", "mipsel-freestanding-none")),
        )
        with tempfile.TemporaryDirectory() as folder:
            for arch, source, flags in ports:
                with self.subTest(arch=arch, source=source, flags=flags):
                    result = subprocess.run(
                        [sys.executable, "-m", "ziglang", "cc", *flags, "-std=c99", "-ffreestanding",
                         "-Os", "-Wall", "-Wextra", "-Werror", f"-I{STUB}", "-c",
                         str(STUB / "ports" / arch / source), "-o", str(Path(folder) / "port.o")],
                        capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
