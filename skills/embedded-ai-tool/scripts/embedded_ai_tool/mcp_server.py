"""MCP (stdio) bridge: an AI client's tool calls reach the target's RAM through one live session.

    AI client --MCP JSON-RPC--> eat mcp --Tcl RPC--> OpenOCD --debug probe (SWD/JTAG)--> MCU registers / RAM / stub

Every tool call becomes the argv the CLI accepts and goes through `cli.dispatch`: parser, audit
record, profile policy, UID guard inside each Tcl request, dead-man. Mutating tools return a plan
unless execute=true; the MCP client's permission prompt is the human approval for that call.
Between calls the stub heartbeat keeps claimed pins alive; when the client goes away the beats
stop and the stub returns the pins to their safe state.

With `openocd.autostart: true` in the profile, a refused connection starts the profile's reviewed
OpenOCD command (same argv as `eat openocd`) and stops it again when the bridge exits.

No MCP SDK dependency: stdio MCP is newline-delimited JSON-RPC 2.0 and only tools are served.
"""
import json
import queue
import subprocess
import sys
import threading
import time

from . import __version__
from .cli import command_plan, dispatch
from .core import open_target
from .live import Session

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Bu sunucu bir mikrodenetleyicinin register ve RAM'ine OpenOCD ve debug probu üzerinden canlı erişim verir; "
    "flash'a yazmaz. pin_list hangi pinlerin ve işlevlerin izinli olduğunu gösterir. Değiştiren araçlar "
    "(poke, pin_apply, pin_release, pin_restore, safe_state, ram_*, program_set, task_add, task_remove, "
    "param_set ve olay tüketimi) execute=false ile yalnız plan döndürür; "
    "planı kullanıcıya göster, sonra execute=true ile uygula. Sonuçlar register geri okumasıdır, fiziksel "
    "ölçüm değildir. outcome=unknown_if_sent olan bir yazmayı asla otomatik tekrarlama; önce durumu oku. "
    "Sunucu kapanınca stub, dead-man süresi sonunda pinleri güvenli duruma alır."
)
TYPES = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}
ADDRESS = {"type": ["string", "integer"], "description": "Adres: '0x40020014' gibi metin veya tam sayı"}
EXECUTE = {"type": "boolean", "default": False,
           "description": "false: yalnız plan döner, karta dokunulmaz. true: uygular (kullanıcı onayıyla)"}
TOOLS = {}


def tool(name, description, argv, properties=None, required=(), online=lambda a: True, mutating=False):
    TOOLS[name] = {"description": description, "argv": argv, "online": online, "mutating": mutating,
                   "schema": {"type": "object", "properties": properties or {}, "required": list(required),
                              "additionalProperties": False}}


def executing(arguments):
    return bool(arguments.get("execute"))


def execute_flag(arguments):
    return ["--execute"] if arguments.get("execute") else []


def optional(flag, arguments, key):
    return [flag, str(arguments[key])] if key in arguments else []


def repeated(flag, values):
    return [item for value in values for item in (flag, str(value))]


tool("target_identity", "Bağlı kartın UID'sini okur ve profildeki kartla karşılaştırır.", lambda a: ["identity"])
tool("read_register", "SVD adlarıyla izinli register ve bit alanlarını okur; yan etkili okumalar reddedilir.",
     lambda a: ["reg", "read", *a["names"]],
     {"names": {"type": "array", "items": {"type": "string"}, "minItems": 1}}, ["names"])
tool("list_registers", "SVD register adlarını bağlantı açmadan listeler.",
     lambda a: ["reg", "list", *([a["peripheral"]] if "peripheral" in a else []), *optional("--filter", a, "filter")],
     {"peripheral": {"type": "string"}, "filter": {"type": "string"}}, online=lambda a: False)
tool("verify_build", "Flash'taki imajı profildeki ELF ile karşılaştırır (doğru stub/firmware yüklü mü).",
     lambda a: ["verify"])
tool("read_variables", "Profilde tanımlı değişkenleri okur. Ardışık okumadır, atomik anlık görüntü değildir.",
     lambda a: ["read", *a["names"]],
     {"names": {"type": "array", "items": {"type": "string"}, "minItems": 1}}, ["names"])
tool("watch_variables", "CPU durdurulmadan değişken tablosu ve min/max okur; en fazla 60 saniye.",
     lambda a: ["watch-variables", *a["names"], "--samples", str(a.get("samples", 20)),
                "--interval-ms", str(a.get("interval_ms", 200))],
     {"names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
      "samples": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
      "interval_ms": {"type": "integer", "minimum": 10, "maximum": 5000, "default": 200}}, ["names"])
tool("fault_evidence", "Profil live.arch mimarisinin fault kanıtını okur; hedef durdurulmaz.",
     lambda a: ["fault"])
tool("peek", "İzinli bir adresten register/bellek okur. Okuması yan etkili registerlar reddedilir.",
     lambda a: ["peek", str(a["address"]), "--count", str(a.get("count", 1)), "--width", str(a.get("width", 32))],
     {"address": ADDRESS, "count": {"type": "integer", "minimum": 1, "maximum": 256, "default": 1},
      "width": {"type": "integer", "enum": [8, 16, 32], "default": 32}}, ["address"])
tool("poke", "write_ranges içindeki bir register/RAM adresine yazar ve geri okur. mask verilirse yalnız o bitler "
     "değişir. verify=false yazma-only/W1C registerlar içindir: kör, tam genişlikte yazar, maske alamaz.",
     lambda a: ["poke", str(a["address"]), str(a["value"]), "--width", str(a.get("width", 32)),
                *optional("--mask", a, "mask"), *([] if a.get("verify", True) else ["--no-verify"]), *execute_flag(a)],
     {"address": ADDRESS, "value": {"type": ["string", "integer"]},
      "width": {"type": "integer", "enum": [8, 16, 32], "default": 32}, "mask": {"type": ["string", "integer"]},
      "verify": {"type": "boolean", "default": True}, "execute": EXECUTE},
     ["address", "value"], executing, True)
tool("pin_list", "Profildeki pinler, izinli işlevleri, güvenli işlevi ve kayıtlı talepler (donanımdan ölçülmez).",
     lambda a: ["pin", "list"], online=lambda a: False)
tool("pin_apply", "Bir pine izinli işlevi (gpio_out, pwm, uart_tx, adc...) MCU tarifiyle uygular. Önce dead-man "
     "güvenli durum tablosu kurulur, sonra registerlar yazılır ve geri okunur.",
     lambda a: ["pin", "apply", a["pin"], a["function"],
                *[x for k, v in a.get("params", {}).items() for x in ("--param", f"{k}={v}")], *execute_flag(a)],
     {"pin": {"type": "string"}, "function": {"type": "string"},
      "params": {"type": "object", "additionalProperties": {"type": ["integer", "string"]},
                 "description": "Tarif girdileri, örn. {\"freq\": 1000, \"duty_permille\": 250}"},
      "execute": EXECUTE},
     ["pin", "function"], executing, True)
tool("pin_release", "Pini profildeki güvenli işlevine alır ve talebi bırakır.",
     lambda a: ["pin", "release", a["pin"], *execute_flag(a)],
     {"pin": {"type": "string"}, "execute": EXECUTE}, ["pin"], executing, True)
tool("pin_restore", "Pinin registerlarını ilk uygulamadan önceki değerlerine geri yazar.",
     lambda a: ["pin", "restore", a["pin"], *execute_flag(a)],
     {"pin": {"type": "string"}, "execute": EXECUTE}, ["pin"], executing, True)
tool("safe_state", "Talep edilen pinleri (all=true ise profildeki bütün korumasız pinleri) güvenli duruma alır.",
     lambda a: ["safe", *(["--all"] if a.get("all") else []), *execute_flag(a)],
     {"all": {"type": "boolean", "default": False}, "execute": EXECUTE}, (), executing, True)
tool("stub_status", "Stub mailbox: canlılık, heartbeat, dead-man sayacı, son RAM çağrısı.", lambda a: ["stub", "status"])
tool("ram_build", "Profildeki live.ram_build komutuyla RAM parçasını derler (ana makinede; karta dokunmaz).",
     lambda a: ["ram", "build", *execute_flag(a)], {"execute": EXECUTE}, online=lambda a: False, mutating=True)
tool("ram_load", "Proje içindeki bir ikili dosyayı scratch RAM'e yükler ve geri okuyarak doğrular.",
     lambda a: ["ram", "load", *optional("--file", a, "file"), *optional("--address", a, "address"), *execute_flag(a)],
     {"file": {"type": "string"}, "address": ADDRESS, "execute": EXECUTE}, (), executing, True)
tool("ram_run", "Yüklenen RAM parçasını stub üzerinden çağırır (en çok 4 argüman). RAM içeriği yüklemeyle "
     "uyuşmazsa çalıştırmaz. Zaman aşımında kod hâlâ çalışıyor olabilir; tekrar denenmez.",
     lambda a: ["ram", "run", *optional("--entry", a, "entry"), *repeated("--arg", a.get("args", [])),
                "--timeout", str(a.get("timeout_s", 10)), *execute_flag(a)],
     {"entry": ADDRESS, "args": {"type": "array", "items": {"type": ["integer", "string"]}, "maxItems": 4},
      "timeout_s": {"type": "number", "default": 10}, "execute": EXECUTE},
     (), executing, True)

GENERATION = {"type": "integer", "minimum": 0, "maximum": 4294967294}
tool("program_get", "Yorumlayıcı v2 durumu, aktif görüntü ve görev revizyonlarını okur.",
     lambda a: ["program", "get"])
tool("program_set", "JSON programını derler; varsayılan plan, execute=true ile RAM upload/commit.",
     lambda a: ["program", "set", "--json", json.dumps(a["program"]),
                "--expected-generation", str(a["expected_generation"]), *execute_flag(a)],
     {"program": {"type": "object"}, "expected_generation": GENERATION, "execute": EXECUTE},
     ("program", "expected_generation"), executing, True)
tool("task_add", "Doğrulanmış host kaynak kaydındaki programa görev ekler/değiştirir.",
     lambda a: ["program", "task-add", "--json", json.dumps(a["task"]),
                "--expected-generation", str(a["expected_generation"]), *execute_flag(a)],
     {"task": {"type": "object"}, "expected_generation": GENERATION, "execute": EXECUTE},
     ("task", "expected_generation"), executing, True)
tool("task_remove", "Görevi aynı iki bankalı transaction ile siler; kaynakları safe bırakır.",
     lambda a: ["program", "task-remove", a["task_id"], "--expected-generation", str(a["expected_generation"]),
                *execute_flag(a)],
     {"task_id": {"type": "string"}, "expected_generation": GENERATION, "execute": EXECUTE},
     ("task_id", "expected_generation"), executing, True)
tool("param_set", "Parametreyi sınır denetimiyle tick sınırında atomik günceller.",
     lambda a: ["program", "param", a["param_id"], str(a["value"]),
                "--expected-generation", str(a["expected_generation"]), *execute_flag(a)],
     {"param_id": {"type": "string"}, "value": {"type": "integer", "minimum": 0, "maximum": 4294967295},
      "expected_generation": GENERATION, "execute": EXECUTE},
     ("param_id", "value", "expected_generation"), executing, True)
tool("events_read", "Ayrı 32 bayt olay halkasını kayıp sayacıyla okur; tüketim execute=true ister.",
     lambda a: ["program", "events", "--limit", str(a.get("limit", 32)), *optional("--cursor", a, "cursor"),
                *optional("--boot-id", a, "boot_id"),
                *(["--consume"] if a.get("consume") else []), *execute_flag(a)],
     {"limit": {"type": "integer", "minimum": 1, "maximum": 256}, "cursor": GENERATION,
      "boot_id": {"type": "integer", "minimum": 1, "maximum": 4294967295},
      "consume": {"type": "boolean", "default": False}, "execute": EXECUTE}, (),
     lambda a: not a.get("consume") or executing(a), True)


tool("measure", "Hedefte en fazla 60 saniye örnekler; yalnız eat_samples yapılandırmasını yazar. "
     "Hız hedef sıra/zaman farkından ölçülür.",
     lambda a: ["measure", *repeated("--channel", a["channels"]), "--period-ms", str(a["period_ms"]),
                "--duration", str(a["duration"]), *repeated("--threshold", a.get("thresholds", []))],
     {"channels": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 8},
      "period_ms": {"type": "integer", "minimum": 1}, "duration": {"type": "number", "maximum": 60},
      "thresholds": {"type": "array", "items": {"type": "number"}}},
     ("channels", "period_ms", "duration"), mutating=True)


def is_type(value, kinds):
    kinds = kinds if isinstance(kinds, list) else [kinds]
    if isinstance(value, bool):
        return "boolean" in kinds
    return any((kind == "number" and isinstance(value, int | float)) or isinstance(value, TYPES.get(kind, ()))
               for kind in kinds)


def check(schema, arguments):
    """Top-level argument check; values are validated again by the CLI parser and live policy."""
    if not isinstance(arguments, dict):
        raise ValueError("arguments bir nesne olmalı")
    missing = [key for key in schema["required"] if key not in arguments]
    unknown = [key for key in arguments if key not in schema["properties"]]
    if missing or unknown:
        raise ValueError(f"eksik: {missing}, bilinmeyen: {unknown}")
    for key, value in arguments.items():
        spec = schema["properties"][key]
        if not is_type(value, spec["type"]):
            raise ValueError(f"{key} tipi {spec['type']} olmalı")
        if type(value) in (int, float) and not spec.get("minimum", value) <= value <= spec.get("maximum", value):
            raise ValueError(f"{key} izinli aralık dışında "
                             f"({spec.get('minimum', '-')}..{spec.get('maximum', '-')})")
        if "minItems" in spec and len(value) < spec["minItems"]:
            raise ValueError(f"{key} boş olamaz")
        items = spec.get("items") or {}
        if items and not all(is_type(item, items["type"]) for item in value):
            raise ValueError(f"{key} öğeleri {items['type']} olmalı")


def error(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def reply(response):
    keys = ("ok", "result", "error", "error_type", "mutation_outcome", "output", "record")
    payload = {key: response[key] for key in keys if response.get(key) not in (None, "")}
    payload["ok"] = bool(response.get("ok"))
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=1)}],
            "isError": not payload["ok"]}


class Bridge:
    def __init__(self, base, profile, stdout=None):
        self.base, self.profile = base, profile
        self.session = Session(profile)  # connects lazily: tools/list works before OpenOCD is up
        self.out = stdout or sys.stdout
        stub = self.session.live.stub
        self.period = stub.timeout_ms / 3000 if stub is not None and stub.deadman else None
        self.stopped = None
        self.stub_missing = False
        self.openocd = None

    def send(self, message):
        self.out.write(json.dumps(message, ensure_ascii=True, allow_nan=False) + "\n")
        self.out.flush()

    def log(self, **event):
        print(json.dumps(event, ensure_ascii=True), file=sys.stderr, flush=True)

    def connected(self):
        target = self.session.target
        return target is not None and not target.closed

    def connect(self):
        if self.connected():
            return
        try:
            target = open_target(self.profile)
        except OSError:
            if not self.start_openocd():
                raise
            target = self.wait_for_openocd()
        self.session.attach(target)

    def start_openocd(self):
        """Start the profile's OpenOCD once, if the profile opts in; stdout is the MCP stream, keep it clean."""
        if self.profile.transport != "openocd" or self.profile.data.get("openocd", {}).get("autostart") is not True:
            return False
        if self.openocd is not None and self.openocd.poll() is None:
            return True
        plan = command_plan(self.profile, "openocd")
        self.log(event="openocd_start", argv=plan["argv"])
        self.openocd = subprocess.Popen(plan["argv"], cwd=plan["cwd"], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=sys.stderr)
        return True

    def wait_for_openocd(self, timeout_s=10):
        deadline = time.monotonic() + timeout_s
        while True:
            if self.openocd.poll() is not None:
                raise ConnectionError(f"OpenOCD başlatıldı ama çıktı (kod {self.openocd.returncode}); "
                                      "prob bağlı mı, başka bir debug oturumu açık mı?")
            try:
                return open_target(self.profile)
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)

    def stop_openocd(self):
        # Only the server this bridge started; terminating OpenOCD does not reset or halt the target.
        if self.openocd is not None and self.openocd.poll() is None:
            self.openocd.terminate()
            try:
                self.openocd.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.openocd.kill()

    def beat(self):
        if self.period is None or not self.connected():
            return
        try:
            alive = self.session.live.heartbeat()
        except (ValueError, OSError) as exc:
            self.log(event="heartbeat_failed", error=str(exc))
            return
        if not alive and not self.stub_missing:
            self.log(event="stub_missing", error="Mailbox magic yok; heartbeat yazılmadı")
        self.stub_missing = not alive

    def call(self, name, arguments):
        spec = TOOLS.get(name)
        if spec is None:
            raise LookupError(f"Bilinmeyen araç: {name}")
        try:
            check(spec["schema"], arguments)
            argv = spec["argv"](arguments)
        except (ValueError, KeyError, TypeError) as exc:
            return reply({"ok": False, "error": f"Geçersiz argüman: {exc}"})
        online = spec["online"](arguments)
        if name == "fault_evidence":
            from .arch import supported

            online = supported(self.profile)
        if online:
            try:
                self.connect()
            except OSError as exc:
                where = f"{self.profile.connection.get('host', '127.0.0.1')}:{self.profile.connection.get('port', 6666)}"
                return reply({"ok": False, "error": f"OpenOCD'ye bağlanılamadı ({where}): {exc}. OpenOCD ve prob "
                                                    "çalışıyor mu? (eat --profile ... openocd --execute)"})
        response = dispatch(argv, self.base, self.session)
        if response.get("error_type") == "KeyboardInterrupt":
            self.stopped = "Ctrl+C"
        return reply(response)

    def handle(self, message):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return error(None, -32600, "Geçersiz JSON-RPC isteği")
        if "method" not in message or "id" not in message:
            return None  # notifications (initialized, cancelled) and responses need no answer
        mid, method, params = message["id"], message["method"], message.get("params") or {}
        if method == "initialize":
            requested = params.get("protocolVersion")
            result = {"protocolVersion": requested if requested in PROTOCOLS else PROTOCOLS[0],
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "embedded-ai-tool", "version": __version__},
                      "instructions": INSTRUCTIONS}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [{"name": name, "description": spec["description"], "inputSchema": spec["schema"],
                                 "annotations": {"readOnlyHint": not spec["mutating"],
                                                 "destructiveHint": spec["mutating"], "openWorldHint": False}}
                                for name, spec in TOOLS.items()]}
        elif method == "tools/call":
            try:
                result = self.call(params.get("name"), params.get("arguments") or {})
            except LookupError as exc:
                return error(mid, -32602, str(exc))
        else:
            return error(mid, -32601, f"Desteklenmeyen yöntem: {method}")
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def run(self, stdin):
        lines = queue.Queue()

        def pump():
            for line in stdin:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=pump, daemon=True).start()
        handled = 0
        try:
            while self.stopped is None:
                try:
                    line = lines.get(timeout=self.period)
                except queue.Empty:
                    self.beat()
                    continue
                if line is None:
                    self.stopped = "istemci kapandı"
                    break
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    self.send(error(None, -32700, "JSON ayrıştırılamadı"))
                    continue
                response = self.handle(message)
                if response is not None:
                    self.send(response)
                handled += 1
                self.beat()
        except KeyboardInterrupt:
            self.stopped = "Ctrl+C"
        finally:
            if self.session.target is not None:
                self.session.target.close()
            self.stop_openocd()
        return {"messages": handled, "stopped_by": self.stopped,
                "note": "Heartbeat durdu; stub dead-man süresi sonunda pinleri güvenli duruma alır"}


def serve_mcp(args, profile, stdin=None, stdout=None):
    if stdin is None:
        # MCP stdio is UTF-8 with '\n' framing regardless of the Windows console code page.
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    return Bridge(args, profile, stdout).run(stdin or sys.stdin)
