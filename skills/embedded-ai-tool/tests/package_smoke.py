"""Build and exercise the installed wheel, independent of the source checkout.

For offline runs, supply cached dependency wheels with --wheelhouse and use
--offline (the current interpreter must already have the build requirements).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, timeout=300, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--wheelhouse", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="eat-package-") as folder:
        work = Path(folder).resolve()
        dist = work / "dist"
        command = [sys.executable, "-m", "build", "--outdir", str(dist)]
        if args.offline:
            command.append("--no-isolation")
        run(command, cwd=ROOT)
        wheel, = dist.glob("*.whl")
        # Check all maintained resources, not just the one used by doctor.
        with zipfile.ZipFile(wheel) as archive:
            for directory, suffixes in (("stub", {".c", ".h", ".md"}),
                                        ("references", {".md", ".json"})):
                for source in (ROOT / directory).rglob("*"):
                    if source.is_file() and source.suffix in suffixes:
                        member = f"embedded_ai_tool/{directory}/{source.relative_to(ROOT / directory).as_posix()}"
                        if archive.read(member) != source.read_bytes():
                            raise RuntimeError(f"Wheel resource differs: {member}")
        environment = work / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        bindir = environment / ("Scripts" if os.name == "nt" else "bin")
        python = bindir / ("python.exe" if os.name == "nt" else "python")
        eat = bindir / ("eat.exe" if os.name == "nt" else "eat")
        install = [str(python), "-m", "pip", "install", str(wheel)]
        if args.offline:
            install.append("--no-index")
        if args.wheelhouse:
            install.extend(["--find-links", str(args.wheelhouse.resolve())])
        # Ignore ambient Python paths so an editable install cannot hide a broken wheel.
        env = {key: value for key, value in os.environ.items()
               if key not in {"PYTHONPATH", "PYTHONHOME"}}
        run(install, cwd=work, env=env)
        doctor = json.loads(run([str(eat), "doctor"], cwd=work, env=env, capture_output=True).stdout)
        stub = doctor["result"]["stub_sources"]
        stub_path = Path(stub["path"]).resolve()
        if not doctor["ok"] or not stub["exists"] or not stub_path.is_relative_to(environment):
            raise RuntimeError(f"Doctor did not find installed stub sources: {doctor}")
        if not (stub_path / "eat_stub_core.c").is_file():
            raise RuntimeError("Installed eat_stub_core.c is missing")
        references = stub_path.parent / "references"
        profile = references / "examples" / "example-board.json"
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "package-smoke", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        response = run([str(eat), "--profile", str(profile), "mcp"], cwd=work, env=env,
                       input="".join(json.dumps(message) + "\n" for message in messages), capture_output=True)
        replies = {reply["id"]: reply for line in response.stdout.splitlines()
                   if (reply := json.loads(line)).get("id") is not None}
        if "tools" not in replies[1]["result"]["capabilities"]:
            raise RuntimeError(f"MCP initialization failed: {replies}")
        tools = replies[2]["result"]["tools"]
        if len(tools) < 14:
            raise RuntimeError(f"Expected at least 14 MCP tools, got {len(tools)}")
        print(f"Package smoke passed: installed stub sources, reference docs, MCP ({len(tools)} tools)")


if __name__ == "__main__":
    main()
