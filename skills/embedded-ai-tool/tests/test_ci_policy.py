"""Exercise skip enforcement in isolated pytest sessions."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.mark.parametrize(("source", "expected"), [
    ("def test_ok(): pass", 0),
    ('import pytest\ndef test_skip(): pytest.skip("missing dependency")', 1),
    (('import unittest\nclass Case(unittest.TestCase):\n'
      '    @unittest.skip("missing compiler")\n    def test_skip(self): pass'), 1),
    ('import pytest\npytest.skip("missing dependency", allow_module_level=True)', 1),
    (('import os, pytest\ndef test_optional():\n'
      '    if os.environ["EAT_POLICY_OPTIONAL"] == "0": pytest.skip("optional: EAT_POLICY_OPTIONAL=0")'), 0),
])
def test_skip_policy(source, expected):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        shutil.copyfile(Path(__file__).with_name("conftest.py"), root / "conftest.py")
        (root / "test_sample.py").write_text(source, encoding="utf-8")
        env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "EAT_POLICY_OPTIONAL": "0"}
        env.pop("PYTEST_ADDOPTS", None)
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                cwd=root, env=env, capture_output=True, text=True, timeout=30, check=False)
        assert result.returncode == expected, result.stdout + result.stderr
        assert ("Unexpected skips" in result.stdout) == (expected == 1), result.stdout
