"""JSON CLI; planning is offline and mutations require explicit --execute."""
import argparse
import contextlib
import io
import json
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .core import (
    RPC,
    Device,
    Image,
    Profile,
    argv_plan,
    digest,
    open_target,
    openocd_only,
    run_plan,
    tcl_string,
    utcnow,
)
from .live import Session, run_live

LIVE = {"peek", "poke", "pin", "safe", "ram", "stub", "reg", "fault", "watch-variables", "program"}
SERVE_ALLOWED = LIVE | {"identity", "verify", "read"}


def emit(value, stream=None):
    print(json.dumps(value, ensure_ascii=True, allow_nan=False), file=stream or sys.stdout, flush=True)


def audit(folder, entry):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex + ".json")
    path.write_text(json.dumps(entry, ensure_ascii=True, indent=2, allow_nan=False), encoding="utf-8")
    return str(path)


def parser():
    p = argparse.ArgumentParser(description="Embedded AI Tool — OpenOCD Tcl RPC / JSON")
    p.add_argument("--profile", type=Path)
    p.add_argument("--session-dir", type=Path, default=Path("sessions"))
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    init = sub.add_parser("init")
    init.add_argument("directory", type=Path)
    init.add_argument("--name", default="my-board")
    probe = sub.add_parser("probe-uid", help="MCU belgesinden doğrulanmış UID alanını oku")
    probe.add_argument("address", type=lambda s: int(s, 0))
    probe.add_argument("size", type=int)
    probe.add_argument("--host", default="127.0.0.1")
    probe.add_argument("--port", type=int, default=6666)
    syms = sub.add_parser("symbols")
    syms.add_argument("elf", type=Path)
    syms.add_argument("--filter", default="")
    sub.add_parser("identity")
    sub.add_parser("verify")
    sub.add_parser("fault", help="Mimariye özel fault kanıtını oku")
    sampling = sub.add_parser("watch-variables", help="Sınırlı değişken tablosu oku")
    sampling.add_argument("names", nargs="+")
    sampling.add_argument("--samples", type=int, default=20)
    sampling.add_argument("--interval-ms", type=int, default=200)
    read = sub.add_parser("read")
    read.add_argument("names", nargs="+")
    watch = sub.add_parser("watch")
    watch.add_argument("names", nargs="+")
    watch.add_argument("--interval", type=float, default=0.25)
    watch.add_argument("--duration", type=float, default=10)
    write = sub.add_parser("write")
    write.add_argument("name")
    write.add_argument("value")
    for cmd in ("build", "flash", "openocd", "control"):
        child = sub.add_parser(cmd)
        if cmd == "control":
            child.add_argument("action", choices=("halt", "resume", "reset-run", "reset-halt"))
        child.add_argument("--execute", action="store_true")
    write.add_argument("--execute", action="store_true")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=30)
    live_parser(sub)
    return p


def live_parser(sub):
    """RAM-only live control commands; mutations stay plans until --execute."""
    program = sub.add_parser("program", help="Hedefte canlı program yorumlayıcısı")
    actions = program.add_subparsers(dest="action", required=True)
    actions.add_parser("get")
    setting = actions.add_parser("set")
    source = setting.add_mutually_exclusive_group(required=True)
    source.add_argument("--file")
    source.add_argument("--json")
    setting.add_argument("--expected-generation", type=int)
    setting.add_argument("--execute", action="store_true")
    for name in ("stop", "param", "message", "task-add", "task-remove"):
        child = actions.add_parser(name)
        child.add_argument("--expected-generation", type=int, required=True)
        child.add_argument("--execute", action="store_true")
        if name in ("param", "message"):
            child.add_argument("item")
            child.add_argument("value", type=lambda s: int(s, 0))
        elif name == "task-add":
            child.add_argument("--json", required=True)
        elif name == "task-remove":
            child.add_argument("task_id")
    events = actions.add_parser("events")
    events.add_argument("--limit", type=int, default=32)
    events.add_argument("--cursor", type=int)
    events.add_argument("--boot-id", type=lambda s: int(s, 0))
    events.add_argument("--consume", action="store_true")
    events.add_argument("--execute", action="store_true")
    reg = sub.add_parser("reg", help="SVD register adlarını listele veya oku")
    actions = reg.add_subparsers(dest="action", required=True)
    read = actions.add_parser("read")
    read.add_argument("names", nargs="+")
    listing = actions.add_parser("list")
    listing.add_argument("peripheral", nargs="?")
    listing.add_argument("--filter", default="")
    peek = sub.add_parser("peek", help="İzinli adresten bellek/register oku")
    peek.add_argument("address")
    peek.add_argument("--count", type=int, default=1)
    peek.add_argument("--width", type=int, choices=(8, 16, 32), default=32)
    poke = sub.add_parser("poke", help="write_ranges içinde bellek/register yaz ve geri oku")
    poke.add_argument("address")
    poke.add_argument("value")
    poke.add_argument("--width", type=int, choices=(8, 16, 32), default=32)
    poke.add_argument("--mask", help="Yalnız bu bitleri değiştir (oku-değiştir-yaz)")
    poke.add_argument("--no-verify", action="store_true", help="Yazma-only/W1C register: geri okuma yapma")
    poke.add_argument("--execute", action="store_true")
    pin = sub.add_parser("pin", help="Profildeki pinlerin işlevini tarifle değiştir")
    actions = pin.add_subparsers(dest="action", required=True)
    actions.add_parser("list")
    apply = actions.add_parser("apply")
    apply.add_argument("pin")
    apply.add_argument("function")
    apply.add_argument("--param", action="append", default=[], metavar="ad=değer")
    apply.add_argument("--execute", action="store_true")
    for name in ("release", "restore"):
        child = actions.add_parser(name)
        child.add_argument("pin")
        child.add_argument("--execute", action="store_true")
    safe = sub.add_parser("safe", help="Talep edilen (veya --all) pinleri güvenli duruma al")
    safe.add_argument("--all", action="store_true")
    safe.add_argument("--execute", action="store_true")
    ram = sub.add_parser("ram", help="Flash'a yazmadan RAM'e küçük parça derle/yükle/çalıştır")
    actions = ram.add_subparsers(dest="action", required=True)
    build = actions.add_parser("build")
    build.add_argument("--execute", action="store_true")
    load = actions.add_parser("load")
    load.add_argument("--file")
    load.add_argument("--address")
    load.add_argument("--execute", action="store_true")
    run_ram = actions.add_parser("run")
    run_ram.add_argument("--entry")
    run_ram.add_argument("--arg", action="append", default=[])
    run_ram.add_argument("--timeout", type=float, default=10)
    run_ram.add_argument("--execute", action="store_true")
    stub = sub.add_parser("stub", help="Hedefteki stub mailbox durumu")
    stub.add_subparsers(dest="action", required=True).add_parser("status")
    sub.add_parser("serve", help="JSON satırı oturumu: açık RPC, stub heartbeat, dead-man beslemesi")
    sub.add_parser("mcp", help="MCP (stdio) sunucusu: yapay zekâ araçları -> OpenOCD -> hedef RAM")


def init_project(directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    profile = {
        "schema_version": 1, "name": name, "project_root": ".", "byte_order": "little",
        "connection": {"host": "127.0.0.1", "port": 6666, "timeout_s": 10},
        "identity": {"address": "REPLACE_FROM_MCU_MANUAL", "size": "REPLACE_FROM_MCU_MANUAL", "expected_hex": "REPLACE_FROM_REAL_BOARD"},
        "read_ranges": [], "flash_ranges": [],
        "artifact": {"path": "build/firmware.elf", "sha256": "REPLACE_FROM_SYMBOLS_OUTPUT"},
        "variables": {}, "build": {"argv": [], "timeout_s": 120},
        "openocd": {"executable": "openocd", "config_files": [], "shared_filesystem": False},
    }
    path = directory / "board.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(profile, stream, ensure_ascii=True, indent=2)
    return {"profile": str(path.resolve()), "status": "template_requires_hardware_data"}


def command_plan(profile, command):
    if command == "build":
        config = profile.data["build"]
        argv = config["argv"]
    else:
        config = profile.data["openocd"]
        if not config["config_files"]:
            raise ValueError("Kart/probe için incelenmiş OpenOCD config_files gerekli")
        argv = [config.get("executable", "openocd")]
        for cfg in config["config_files"]:
            argv += ["-f", cfg]
        connection = profile.data.get("connection", {})
        if connection.get("host", "127.0.0.1") not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("openocd yalnız yerel sunucu başlatır; uzak sunucuyu kendi bilgisayarında başlatın")
        port = connection.get("port", 6666)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Geçersiz Tcl portu")
        argv += ["-c", f"tcl_port {port}"]
    return argv_plan(argv, profile.root, config.get("timeout_s", 120))


def search_sources(profile, query, limit):
    if not query or not 1 <= limit <= 1000:
        raise ValueError("Arama sorgusu ve 1..1000 limit gerekli")
    skipped = {".git", ".venv", "node_modules", "sessions", "__pycache__", "build", "dist"}
    results = []
    for path in sorted(profile.root.rglob("*")):
        if any(x in skipped for x in path.relative_to(profile.root).parts):
            continue
        if path.suffix.lower() not in {".c", ".h", ".cpp", ".hpp", ".md", ".ioc", ".ld", ".txt"}:
            continue
        if not path.is_file() or not path.resolve().is_relative_to(profile.root) or path.stat().st_size > 2_000_000:
            continue
        raw = path.read_bytes()
        for line_no, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
            if query.casefold() in line.casefold():
                results.append({"file": str(path.relative_to(profile.root)), "line": line_no,
                                "text": line[:2000], "sha256": digest(raw)})
                if len(results) >= limit:
                    return {"matches": results, "limit_reached": True}
    return {"matches": results, "limit_reached": False}


def stub_sources():
    """Installed wheel: package-local stub/; source checkout: the skill's stub/ directory."""
    here = Path(__file__).resolve()
    stub = next((p for p in (here.parent / "stub", here.parents[2] / "stub") if p.is_dir()), here.parent / "stub")
    return {"path": str(stub), "exists": stub.is_dir()}


def run(args):
    if args.command == "doctor":
        return {"python": sys.version, "openocd": shutil.which("openocd"),
                "stub_sources": stub_sources(),
                "transport": "openocd: OpenOCD Tcl RPC (default 6666), the debug probe is OpenOCD's adapter; serial: stub link over UART/USB (pyserial)",
                "hardware_tested": False}
    if args.command == "init":
        return init_project(args.directory, args.name)
    if args.command == "probe-uid":
        if args.address < 0 or not 1 <= args.size <= 256 or not 1 <= args.port <= 65535:
            raise ValueError("Geçersiz UID adresi/boyutu/portu")
        rpc = RPC({"host": args.host, "port": args.port, "timeout_s": 10})
        try:
            raw = bytes(int(x, 0) for x in rpc.call(f"read_memory {args.address} 8 {args.size}").split())
            if len(raw) != args.size:
                raise ValueError("Eksik UID cevabı")
            return {"uid_hex": raw.hex(), "verified_device": False,
                    "note": "Fiziksel hedefi teyit edip bu bayt sırasını expected_hex alanına kaydedin"}
        finally:
            rpc.close()
    if args.command == "symbols":
        image = Image(args.elf)
        return {"sha256": image.sha, "byte_order": "little" if image.little else "big",
                "symbols": [{"name": s.name, "address": hex(s["st_value"]), "size": s["st_size"]}
                            for s in image.symbols() if args.filter in s.name]}
    if args.profile is None:
        raise ValueError("Bu komut için --profile gerekli")
    session = getattr(args, "_session", None)
    offline = args.command in {"build", "search", "openocd"} or (args.command == "reg" and args.action == "list")
    profile = session.profile if session else Profile(args.profile, require_target=not offline)
    args.profile_context = {"name": profile.name, "profile_sha256": profile.sha,
                            "expected_identity": profile.data.get("identity"),
                            "connection": profile.data.get("connection"),
                            "expected_artifact": profile.data.get("artifact")}
    if args.command == "search":
        return search_sources(profile, args.query, args.limit)
    if args.command in {"build", "openocd"}:
        plan = command_plan(profile, args.command)
        if not args.execute:
            return {"plan": plan, "executed": False}
        if args.command == "openocd":
            # Foreground process: Ctrl+C terminates only the server started by this command.
            completed = subprocess.run(plan["argv"], cwd=plan["cwd"], stdout=sys.stderr, check=False)
            if completed.returncode:
                raise ValueError(f"OpenOCD başarısız ({completed.returncode})")
            return {"returncode": completed.returncode}
        result = run_plan(plan, "Derleme")
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
                "note": "Yeni ELF SHA256 ve profil bilgileri ayrıca doğrulanmalı"}
    if args.command in LIVE:
        if args.command == "program":
            from .interp import run_program

            return run_program(args, profile)
        return run_live(args, profile)
    if args.command == "serve":
        return serve(args, profile)
    if args.command == "mcp":
        from .mcp_server import serve_mcp  # imports this module; load only when needed

        return serve_mcp(args, profile)
    device = session.live.device if session else Device(profile, None)
    # Inside serve, long flash reads must keep feeding the stub dead-man.
    tick = (lambda: session.live.keepalive(throttle=True)) if session else None
    plan = None
    if args.command == "write":
        plan = device.write_plan(args.name, args.value)
    elif args.command == "control":
        plan = {"action": args.action}
    elif args.command == "flash":
        if profile.data["openocd"].get("shared_filesystem") is not True:
            raise ValueError("Flash için aynı dosya sistemindeki yerel OpenOCD gerekli; shared_filesystem=true ayarlayın")
        image = profile.artifact()
        image.regions(profile.data["flash_ranges"])
        plan = {"image": str(image.path), "sha256": image.sha,
                "effect": "halt, flash erase/write, verify_image, reset run"}
    if plan is not None and not args.execute:
        return {"plan": plan, "executed": False}
    if args.command == "watch" and (not 0.01 <= args.interval <= 60 or not 0 < args.duration <= 86400):
        raise ValueError("interval 0.01..60; duration 0..86400 gerekli")
    target = session.target if session else open_target(profile)
    device.target = target
    try:
        if args.command == "identity":
            actual = device.read(profile.uid_address, profile.uid_size)
            return {"uid_hex": actual.hex(), "matches": actual == profile.expected, "profile": profile.name}
        if args.command == "verify":
            return device.verify(tick)
        if args.command == "read":
            verification = device.verify(tick) if any("symbol" in profile.variables[name] for name in args.names) else None
            start = utcnow()
            values = device.snapshot(args.names)
            return {"started_at": start, "ended_at": utcnow(), "values": values,
                    "build_verification": verification, "atomic": False}
        if args.command == "watch":
            verification = device.verify() if any("symbol" in profile.variables[name] for name in args.names) else None
            until = time.monotonic() + args.duration
            count = 0
            with (args.session_dir / (uuid.uuid4().hex + "_trace.jsonl")).open("x", encoding="utf-8") as stream:
                while time.monotonic() < until:
                    started = time.monotonic()
                    sample = {"started_at": utcnow(), "values": device.snapshot(args.names), "ended_at": utcnow(),
                              "profile_sha256": profile.sha, "expected_uid_hex": profile.expected.hex()}
                    stream.write(json.dumps(sample, allow_nan=False) + "\n")
                    stream.flush()
                    emit({"sample": sample})
                    count += 1
                    time.sleep(max(0, args.interval - (time.monotonic() - started)))
                return {"samples": count, "trace": stream.name, "build_verification": verification, "atomic": False}
        if args.command == "write":
            return device.write(plan)
        if args.command == "control":
            action = {"halt": "halt", "resume": "resume", "reset-run": "reset run", "reset-halt": "reset halt"}[args.action]
            return {"command_response": openocd_only(target, "control").script(action), "action": args.action}
        if args.command == "flash":
            # OpenOCD reads a file by path. Freeze the already hashed bytes so a
            # concurrent rebuild cannot replace the file between validation and flash.
            staged = args.session_dir / (uuid.uuid4().hex + "_firmware.elf")
            with staged.open("xb") as stream:
                stream.write(profile.artifact().raw)
            path = tcl_string(staged.resolve().as_posix())
            response = openocd_only(target, "flash").script(f"halt; flash write_image erase {path}; verify_image {path}; reset run")
            return {"plan": plan, "staged_image": str(staged), "response": response, "verified": True}
    finally:
        if session is None:
            target.close()
    raise ValueError("Bilinmeyen komut")


def serve(args, profile):
    """Line-delimited JSON requests ({"argv": [...]}) over one connection; feeds the stub dead-man heartbeat."""
    target = open_target(profile)
    try:
        session = Session(profile, target)
        stub = session.live.stub
        present = bool(stub is not None and (stub.status()["magic_ok"] or (
            session.live.config.get("interpreter") and target.read(stub.base, 32, 2) == [0x32544145, 2])))
    except BaseException:
        target.close()
        raise
    # Never heartbeat into a mailbox the stub has not claimed: that RAM may be application data.
    period = stub.timeout_ms / 3000 if present and stub.deadman else None
    lines = queue.Queue()

    def pump():
        for line in sys.stdin:
            lines.put(line)
        lines.put(None)

    def beat():
        if period is None or target.closed:
            return
        try:
            if not session.live.heartbeat():
                emit({"event": "stub_missing", "error": "Mailbox magic yok; heartbeat yazılmadı"})
        except (ValueError, OSError) as exc:
            emit({"event": "heartbeat_failed", "error": str(exc)})

    threading.Thread(target=pump, daemon=True).start()
    emit({"event": "ready", "stub": present, "heartbeat_period_s": period})
    handled, reason = 0, "stdin kapandı"
    try:
        while True:
            try:
                line = lines.get(timeout=period)
            except queue.Empty:
                beat()
                continue
            if line is None:
                break
            if line.strip():
                response = serve_request(line, args, session)
                emit(response)
                handled += 1
                if response.get("error_type") == "KeyboardInterrupt":
                    reason = "Ctrl+C"
                    break
                beat()
            if target.closed:
                reason = "Hedef bağlantısı hata sonrası kapatıldı"
                break
    except KeyboardInterrupt:
        reason = "Ctrl+C"
    finally:
        target.close()
    return {"requests": handled, "stopped_by": reason,
            "note": "Heartbeat durdu; stub dead-man süresi sonunda pinleri güvenli duruma alır"}


def serve_request(line, base, session):
    try:
        argv = json.loads(line)["argv"]
    except (ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "error": f"Geçersiz istek: {exc}", "output": ""}
    return dispatch(argv, base, session)


def dispatch(argv, base, session):
    """Run one session request through the CLI parser, policy and audit (shared by serve and mcp)."""
    captured = io.StringIO()
    try:
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
            raise ValueError('{"argv": ["komut", ...]} gerekli')
        if argv[0] not in SERVE_ALLOWED:
            raise ValueError(f"serve içinde desteklenmeyen komut: {argv[0]}")
        # argparse prints help/usage itself; keep stdout a pure JSON-lines stream.
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            args = parser().parse_args(["--profile", str(base.profile), "--session-dir", str(base.session_dir), *argv])
    except (ValueError, KeyError, TypeError, SystemExit) as exc:
        return {"ok": False, "error": f"Geçersiz istek: {exc}", "output": captured.getvalue()}
    args.session_dir = args.session_dir.resolve()
    args._session = session
    return execute(args)[0]


def execute(args):
    entry = {"started_at": utcnow(), "command": args.command,
             "profile": str(args.profile.resolve()) if args.profile else None,
             "arguments": {key: str(value) if isinstance(value, Path) else value
                           for key, value in vars(args).items() if not key.startswith("_")}}
    # Persist intent before any connection or mutation, including interrupted/ambiguous writes.
    intent = audit(args.session_dir, {**entry, "status": "started"})
    try:
        result = run(args)
        entry.update(ok=True, result=result)
        code = 0
    except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 -- CLI boundary must audit every failure.
        entry.update(ok=False, error=str(exc) or "İptal edildi", error_type=type(exc).__name__,
                     mutation_outcome="unknown_if_sent; never automatically retry")
        code = 1
    entry.update(ended_at=utcnow(), intent=intent, profile_context=getattr(args, "profile_context", None))
    record = audit(args.session_dir, entry)
    return {**entry, "record": record}, code


def main():
    args = parser().parse_args()
    args.session_dir = args.session_dir.resolve()
    result, code = execute(args)
    # Under mcp, stdout carries only JSON-RPC; the session summary goes to stderr.
    emit(result, sys.stderr if args.command == "mcp" else None)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
