"""Exercise the copied skill outside its repository and any installed editable tool."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PortableSkillTests(unittest.TestCase):
    def test_launcher_and_imports_after_relocation(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scripts = root / "skill copy" / "scripts"
            shutil.copytree(source / "scripts", scripts, ignore=shutil.ignore_patterns("__pycache__"))
            work = root / "firmware project"
            work.mkdir()
            result = subprocess.run([sys.executable, str(scripts / "eat.py"), "doctor"], cwd=work,
                                    capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["ok"])
            self.assertTrue(Path(report["record"]).is_relative_to(work))
            self.assertFalse(report["result"]["hardware_tested"])
            probe = subprocess.run([sys.executable, "-c",
                                    ("import sys;sys.path.insert(0,sys.argv[1]);"
                                     "import embedded_ai_tool;print(embedded_ai_tool.__file__)"), str(scripts)],
                                   cwd=work, capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertTrue(Path(probe.stdout.strip()).is_relative_to(scripts))

    def test_launcher_initializes_profile_in_project(self):
        launcher = Path(__file__).resolve().parents[1] / "scripts" / "eat.py"
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, str(launcher), "init", "debug/board", "--name", "test-board"],
                                    cwd=folder, capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            profile = json.loads((Path(folder) / "debug/board/board.json").read_text())
            self.assertEqual(profile["name"], "test-board")
            self.assertEqual(profile["variables"], {})
            self.assertEqual(profile["identity"]["address"], "REPLACE_FROM_MCU_MANUAL")
