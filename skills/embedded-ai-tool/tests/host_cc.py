"""Host C compiler for the stub tests: gcc/cc on PATH, else the pip `ziglang` package (zig cc)."""
import ctypes
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

STUB = Path(__file__).resolve().parents[1] / "stub"


def compiler():
    if sys.platform == "win32" and importlib.util.find_spec("ziglang"):
        return [sys.executable, "-m", "ziglang", "cc"]
    found = shutil.which("gcc") or shutil.which("cc")
    if found:
        return [found]
    if importlib.util.find_spec("ziglang"):
        return [sys.executable, "-m", "ziglang", "cc"]
    return None


COMPILER = compiler()
SKIP_REASON = "C derleyici yok (gcc/cc veya `pip install ziglang`); stub testi atlandı"


def build(test_class, sources, name, flags=()):
    """Compile sources with the stub headers into a shared library owned by the test class."""
    folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # Windows keeps the DLL locked
    test_class.addClassCleanup(folder.cleanup)
    library = Path(folder.name) / (name + (".dll" if sys.platform == "win32" else ".so"))
    command = [*COMPILER, "-shared", "-O1", "-Wall", "-Wextra", "-Werror", "-fPIC", f"-I{STUB}", *flags,
               *map(str, sources), "-o", str(library)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    return ctypes.CDLL(str(library))
