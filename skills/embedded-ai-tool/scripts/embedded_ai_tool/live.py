"""Live RAM-only control: policy-checked peek/poke, declarative pin recipes, stub mailbox.

Nothing here writes flash. Every mutation re-checks the target UID inside the same Tcl
request, is bounded by profile policy, and is never retried after an uncertain outcome.
"""
import ast
import json
import operator
import re
import struct
import time
from pathlib import Path

from .core import (
    Device,
    argv_plan,
    digest,
    number,
    open_target,
    run_plan,
    spans,
    unique,
    utcnow,
)

WIDTHS = (8, 16, 32)
STEP_OPS = ("write", "modify", "read", "poll", "delay_ms")
MAX_EXPR = 256
LIMIT = 2**128

# Stub mailbox (32-bit words). See references/stub-protocol.md.
MAGIC = 0x53544145  # bytes "EATS" in little-endian memory
PROTOCOL = 1
HEADER_WORDS = 18
SAFE_ENTRY_WORDS = 4
WORD = {"magic": 0, "version": 1, "stub_hb": 2, "host_hb": 3, "call_seq": 4, "done_seq": 5,
        "status": 6, "entry": 7, "args": 8, "result": 12, "error": 13, "armed": 14,
        "timeout_ms": 15, "safe_count": 16, "deadman_count": 17}
STATUS = {0: "idle", 1: "busy", 2: "ok", 3: "fault", 4: "deadman_fired"}
DEADMAN_FIRED = 4

BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.LShift: operator.lshift,
          ast.RShift: operator.rshift, ast.BitAnd: operator.and_, ast.BitOr: operator.or_,
          ast.BitXor: operator.xor}
UNARYOPS = {ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Invert: operator.invert}
FUNCTIONS = {"min": min, "max": max}


# ---------------------------------------------------------------- expressions

def evaluate(value, names):
    """Integer-only expression evaluator for recipe fields. No attribute access or calls but min/max."""
    if type(value) is int:
        return value
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_EXPR:
        raise ValueError(f"Geçersiz ifade: {value!r}")
    try:
        tree = ast.parse(value.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"İfade çözümlenemedi: {value}") from exc
    return _evaluate(tree.body, names)


def _evaluate(node, names):
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise ValueError(f"Tanımsız parametre: {node.id}")
        return names[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARYOPS:
        return UNARYOPS[type(node.op)](_evaluate(node.operand, names))
    if isinstance(node, ast.BinOp) and type(node.op) in BINOPS:
        left, right = _evaluate(node.left, names), _evaluate(node.right, names)
        if isinstance(node.op, ast.LShift | ast.RShift) and not 0 <= right <= 64:
            raise ValueError("Kaydırma miktarı 0..64 olmalı")
        if isinstance(node.op, ast.FloorDiv | ast.Mod) and right == 0:
            raise ValueError("Sıfıra bölme")
        result = BINOPS[type(node.op)](left, right)
        if abs(result) >= LIMIT:
            raise ValueError("İfade sonucu çok büyük")
        return result
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS
            and node.args and not node.keywords):
        return FUNCTIONS[node.func.id](*[_evaluate(arg, names) for arg in node.args])
    raise ValueError("İfadede izin verilmeyen öğe")


# --------------------------------------------------------------------- policy

def inside(address, size, ranges):
    return any(start <= address and address + size <= end for start, end in ranges)


def overlaps(address, size, ranges):
    return any(address < end and start < address + size for start, end in ranges)


class Policy:
    """Read/write allow-lists. Protected ranges beat every allow-list; side-effect reads are refused."""

    def __init__(self, config, read_ranges):
        self.write = spans(config.get("write_ranges", []))
        # Stub-owned RAM: inspectable, but only the mailbox protocol and ram load may write it.
        self.reserved = spans([config[key] for key in ("mailbox", "scratch") if key in config])
        self.read = spans(read_ranges) + self.write + self.reserved
        self.protected = spans(config.get("protected_ranges", []))
        self.side_effect = spans(config.get("side_effect_ranges", []))

    def check_read(self, address, size):
        if not inside(address, size, self.read) or overlaps(address, size, self.side_effect):
            raise ValueError(f"Okuma izni yok (alan dışı veya okuma yan etkili): {address:#x}+{size}")

    def check_write(self, address, size):
        if not inside(address, size, self.write) or overlaps(address, size, self.protected + self.reserved):
            raise ValueError(f"Yazma izni yok (write_ranges dışı, korumalı veya stub alanı): {address:#x}+{size}")

    def side_effects(self, address, size):
        return overlaps(address, size, self.side_effect)


def check_width(address, width):
    if width not in WIDTHS or address < 0 or address % (width // 8) or address > 2**32 - width // 8:
        raise ValueError("Geçersiz/hizasız 8/16/32 bit erişim")


# -------------------------------------------------------------------- recipes

def compile_steps(recipe, names):
    """Turn a declarative recipe into concrete integer steps. Pure and offline."""
    names = dict(names)
    for key, expression in recipe.get("derive", {}).items():
        names[key] = evaluate(expression, names)
    steps = []
    for raw in recipe["steps"]:
        op = raw["op"]
        if op not in STEP_OPS:
            raise ValueError(f"Bilinmeyen adım: {op}")
        if op == "delay_ms":
            ms = evaluate(raw["ms"], names)
            if not 0 <= ms <= 1000:
                raise ValueError("delay_ms 0..1000 olmalı")
            steps.append({"op": op, "ms": ms})
            continue
        width = raw.get("width", 32)
        address = evaluate(raw["address"], names)
        check_width(address, width)
        full = (1 << width) - 1
        step = {"op": op, "address": address, "width": width}
        if op in ("write", "modify"):
            mask = evaluate(raw["mask"], names) if op == "modify" else full
            value = evaluate(raw["value"], names)
            verify = raw.get("verify", True)
            if type(verify) is not bool or not 0 < mask <= full or not 0 <= value <= full or value & ~mask:
                raise ValueError(f"Geçersiz maske/değer/doğrulama: {raw}")
            step.update(mask=mask, value=value, verify=verify)
        elif op == "read":
            mask = evaluate(raw.get("mask", full), names)
            shift = raw.get("shift", 0)
            if not 0 < mask <= full or type(shift) is not int or not 0 <= shift < width or not raw.get("name"):
                raise ValueError(f"Geçersiz read adımı: {raw}")
            step.update(mask=mask, shift=shift, name=str(raw["name"]))
        else:  # poll
            mask, value = evaluate(raw["mask"], names), evaluate(raw["value"], names)
            timeout = evaluate(raw.get("timeout_ms", 100), names)
            if not 0 < mask <= full or not 0 <= value <= full or value & ~mask or not 1 <= timeout <= 2000:
                raise ValueError(f"Geçersiz poll adımı: {raw}")
            step.update(mask=mask, value=value, timeout_ms=timeout)
        steps.append(step)
    if not steps:
        raise ValueError("Tarifte adım yok")
    return steps


def safe_entries(steps):
    """Flatten a safe-state recipe into (address, width, mask, value) rows the stub can replay."""
    rows = []
    for step in steps:
        if step["op"] not in ("write", "modify"):
            raise ValueError("Dead-man için güvenli durum tarifi yalnız write/modify adımı içerebilir")
        rows.append([step["address"], step["width"], step["mask"], step["value"]])
    return rows


class McuDb:
    """Per-MCU facts: pin->function->recipe bindings. Values come from the reference manual."""

    def __init__(self, path):
        self.path = Path(path).resolve()
        raw = self.path.read_bytes()
        self.sha = digest(raw)
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique)
        if data.get("schema_version") != 1 or not isinstance(data.get("pins"), dict) \
                or not isinstance(data.get("recipes"), dict):
            raise ValueError("MCU veri dosyası: schema_version 1, pins ve recipes gerekli")
        self.name = data.get("name", self.path.stem)
        self.pins, self.recipes = data["pins"], data["recipes"]


# ----------------------------------------------------------------------- live

class StepFailed(ValueError):
    def __init__(self, message, executed):
        super().__init__(message)
        self.executed = executed


class Live:
    def __init__(self, profile, target):
        self.profile, self.target = profile, target
        config = profile.data.get("live", {})
        if not isinstance(config, dict):
            raise ValueError("live bir nesne olmalı")
        self.config = dict(config)
        # {"symbol": "eat_mailbox"}: the firmware's own array; no fixed address or linker edits needed.
        for key in ("mailbox", "scratch"):
            region = self.config.get(key)
            if isinstance(region, dict) and "symbol" in region:
                if "artifact" not in profile.data:
                    raise ValueError(f"live.{key}.symbol için profilde artifact (ELF) gerekli")
                address, size = profile.artifact().object(region["symbol"])
                self.config[key] = {"address": address, "size": size, "symbol": region["symbol"]}
        self.policy = Policy(self.config, profile.data.get("read_ranges", []))
        self.device = Device(profile, target)
        self.order = "<" if profile.data["byte_order"] == "little" else ">"
        self._verified = False
        self._beat_at = None
        self.stub = Stub(self) if "mailbox" in self.config else None

    # -- transport (OpenOcdTarget, SerialTarget: same methods, identity checked in every request)
    def read_words(self, address, width, count):
        return self.target.read(address, width, count)

    def refuse_program_mutation(self):
        if self.config.get("interpreter") and self.stub and self.read_words(self.stub.base, 32, 1)[0] == 0x32544145:
            raise ValueError("BUSY_PROGRAM: mailbox v2 için program komutlarını kullanın")

    def heartbeat(self):
        if self.stub is None:
            return False
        if self.config.get("interpreter"):
            if self.target.increment_if(self.stub.base, 0x32544145, self.stub.address(WORD["host_hb"])):
                return True
        return self.stub.heartbeat()

    def verify_build(self):
        data = self.profile.data
        wanted = self.config.get("verify_build", "artifact" in data and bool(data.get("flash_ranges")))
        if wanted and not self._verified:
            result = self.device.verify(lambda: self.keepalive(throttle=True))
            self._verified = True
            return result
        return None

    def watch_variables(self, names, samples=20, interval_ms=200):
        if type(samples) is not int or not 1 <= samples <= 200:
            raise ValueError("samples 1..200 olmalı")
        if type(interval_ms) is not int or not 10 <= interval_ms <= 5000:
            raise ValueError("interval_ms 10..5000 olmalı")
        if not names or len(set(names)) != len(names):
            raise ValueError("Tekil değişken adları gerekli")
        if (samples - 1) * interval_ms > 60000:
            raise ValueError("Toplam izleme süresi en fazla 60 saniye olabilir")
        for name in names:
            address, size, _ = self.profile.variable(name)
            self.policy.check_read(address, size)
        started = time.monotonic()
        deadline = started + 60
        verification = self.device.verify(lambda: self.keepalive(throttle=True)) if any(
            "symbol" in self.profile.variables[name] for name in names) else None
        rows, limits = [], {}
        first = None
        for _ in range(samples):
            if time.monotonic() >= deadline:
                break
            at = time.monotonic()
            first = at if first is None else first
            values = {}
            for name in names:
                if time.monotonic() >= deadline:
                    break
                values.update(self.device.snapshot([name]))
                if time.monotonic() < deadline:
                    self.keepalive(throttle=True)
            if len(values) != len(names):
                break
            rows.append([round((at - first) * 1000, 3), *[values[n] for n in names]])
            for name, value in values.items():
                old = limits.get(name, {"min": value, "max": value})
                limits[name] = {"min": min(old["min"], value), "max": max(old["max"], value)}
            if len(rows) == samples:
                break
            until = min(at + interval_ms / 1000, deadline)
            while True:
                remaining = until - time.monotonic()
                if remaining <= 0:
                    break
                self.keepalive(throttle=True)
                time.sleep(min(remaining, 0.01))
        return {"columns": ["t_ms", *names], "rows": rows, "min_max": limits,
                "samples": len(rows), "complete": len(rows) == samples,
                "build_verification": verification, "atomic": False}

    # -- peek / poke
    def peek(self, address, count=1, width=32):
        check_width(address, width)
        if not 1 <= count <= 256:
            raise ValueError("count 1..256 olmalı")
        self.policy.check_read(address, count * width // 8)
        values = self.read_words(address, width, count)
        return {"address": address, "width": width, "values": [f"{v:#0{2 + width // 4}x}" for v in values]}

    def poke_plan(self, address, value, width=32, mask=None, verify=True):
        check_width(address, width)
        full = (1 << width) - 1
        mask = full if mask is None else mask
        if not 0 < mask <= full or not 0 <= value <= full or value & ~mask:
            raise ValueError("Değer/maske genişliğe sığmıyor veya değer maske dışı bit içeriyor")
        step = {"op": "modify" if mask != full else "write", "address": address, "width": width,
                "mask": mask, "value": value, "verify": verify}
        return {"step": self.prepare([step])[0]}

    def poke(self, plan):
        build = self.verify_build()
        record = dict(plan["step"])
        try:
            self.mutate(record)
        except (ValueError, OSError) as exc:
            record["outcome"] = "unknown_if_sent" if isinstance(exc, OSError) else "failed"
            raise StepFailed(str(exc), [record]) from exc
        record["outcome"] = "done"
        return {"step": record, "build_verification": build}

    def prepare(self, steps):
        """Apply policy to every step; side-effect registers are written blind, never read."""
        prepared = []
        for step in steps:
            step = dict(step)
            if step["op"] in ("write", "modify"):
                size = step["width"] // 8
                self.policy.check_write(step["address"], size)
                # Unverified (write-only / write-1-to-clear) and side-effect registers are never read:
                # a read-modify-write would write back pending W1C flags or junk read from them.
                blind = self.policy.side_effects(step["address"], size) or not step["verify"]
                full = (1 << step["width"]) - 1
                if blind and step["mask"] != full:
                    raise ValueError(f"Yan etkili veya doğrulamasız (W1C/yalnız-yazma) register maskeli "
                                     f"yazılamaz: {step['address']:#x}")
                step["blind"] = blind
                step["verify"] = step["verify"] and not blind
            elif step["op"] in ("read", "poll"):
                self.policy.check_read(step["address"], step["width"] // 8)
            prepared.append(step)
        return prepared

    def mutate(self, step):
        self.refuse_program_mutation()
        address, width, mask, value = step["address"], step["width"], step["mask"], step["value"]
        if step.get("blind"):
            self.target.write(address, width, [value])
        else:
            step["before"] = self.target.modify(address, width, mask, value) & mask
        if step["verify"]:
            step["after"] = self.read_words(address, width, 1)[0] & mask
            if step["after"] != value & mask:
                raise ValueError(f"readback_mismatch: {address:#x} beklenen {value & mask:#x} okunan {step['after']:#x}")

    def run_steps(self, steps):
        executed, outputs = [], {}
        for step in steps:
            record = dict(step)
            try:
                if step["op"] in ("write", "modify"):
                    self.mutate(record)
                elif step["op"] == "read":
                    value = self.read_words(step["address"], step["width"], 1)[0]
                    outputs[step["name"]] = (value & step["mask"]) >> step["shift"]
                elif step["op"] == "poll":
                    self.keepalive()
                    self.poll(step)
                else:
                    self.keepalive()
                    time.sleep(step["ms"] / 1000)
                    self.keepalive()
            except (ValueError, OSError) as exc:
                record["outcome"] = "unknown_if_sent" if isinstance(exc, OSError) else "failed"
                executed.append(record)
                raise StepFailed(str(exc), executed) from exc
            record["outcome"] = "done"
            executed.append(record)
        return executed, outputs

    def keepalive(self, throttle=False):
        """Feed the dead-man; throttle=True skips the write if a beat went out within timeout/6."""
        if self.stub is None or not self.stub.deadman:
            return
        now = time.monotonic()
        if throttle and self._beat_at is not None and now - self._beat_at < self.stub.timeout_ms / 6000:
            return
        self.heartbeat()
        self._beat_at = now

    def poll(self, step):
        deadline = time.monotonic() + step["timeout_ms"] / 1000
        while True:
            value = self.read_words(step["address"], step["width"], 1)[0]
            if value & step["mask"] == step["value"]:
                return
            if time.monotonic() >= deadline:
                raise ValueError(f"poll zaman aşımı: {step['address']:#x}")
            time.sleep(0.001)

    # -- RAM program
    def scratch(self):
        if "scratch" not in self.config:
            raise ValueError("live.scratch tanımlı değil")
        start, end = spans([self.config["scratch"]])[0]
        return start, end

    def ram_plan(self, data, address=None):
        start, end = self.scratch()
        address = start if address is None else address
        if address % 4 or not data or not inside(address, -(-len(data) // 4) * 4, [(start, end)]):
            raise ValueError("RAM parçası boş, hizasız veya live.scratch dışında")
        if self.policy.protected and overlaps(address, len(data), self.policy.protected):
            raise ValueError("RAM parçası korumalı alanla çakışıyor")
        return {"address": address, "size": len(data), "sha256": digest(data)}

    def ram_load(self, data, address=None):
        self.refuse_program_mutation()
        plan = self.ram_plan(data, address)
        self.verify_build()
        padded = data + b"\x00" * (-len(data) % 4)
        words = struct.unpack(self.order + f"{len(padded) // 4}I", padded)
        for offset in range(0, len(words), 128):
            chunk = words[offset:offset + 128]
            at = plan["address"] + offset * 4
            self.target.write(at, 32, chunk)
            if tuple(self.read_words(at, 32, len(chunk))) != chunk:
                raise ValueError(f"RAM readback uyuşmuyor: {at:#x}; parça çalıştırılmamalı")
        return {**plan, "readback_verified": True}

    def ram_digest(self, address, size):
        """SHA-256 of what scratch RAM holds now (a reset or partial load changes it)."""
        raw = b""
        total = -(-size // 4)
        for offset in range(0, total, 128):
            count = min(128, total - offset)
            raw += struct.pack(self.order + f"{count}I", *self.read_words(address + offset * 4, 32, count))
        return digest(raw[:size])

    def ram_run(self, entry, args, timeout_s):
        self.refuse_program_mutation()
        if self.stub is None:
            raise ValueError("RAM çağrısı için live.mailbox ve çalışan stub gerekir")
        # Architecture-specific call bits come from the profile (Cortex-M Thumb: 1); none by default.
        entry_or = self.config.get("entry_or", 0)
        if type(entry_or) is not int or not 0 <= entry_or <= 0xF:
            raise ValueError("live.entry_or 0..15 olmalı")
        try:
            return self.stub.call(entry | entry_or, args, timeout_s)
        except ValueError as exc:
            if not str(exc).startswith("RAM parçası hata verdi: fault,") or not self.config.get("arch"):
                raise
            from . import arch

            try:
                evidence = arch.fault_evidence(self.target, self.profile)
            except (ValueError, OSError) as evidence_error:
                evidence = {"error": str(evidence_error)}
            raise ValueError(str(exc) + "; fault_evidence=" + json.dumps(evidence, separators=(",", ":"))) from exc


# ----------------------------------------------------------------------- stub

class Stub:
    """Host side of the preloaded stub's RAM mailbox. Word ownership is in references/stub-protocol.md."""

    def __init__(self, live):
        self.live = live
        box = live.config["mailbox"]
        self.base, end = spans([box])[0]
        if self.base % 4 or (end - self.base) < (HEADER_WORDS + SAFE_ENTRY_WORDS) * 4:
            raise ValueError("live.mailbox hizalı ve en az 88 bayt olmalı")
        self.capacity = (end - self.base) // 4 - HEADER_WORDS
        self.capacity //= SAFE_ENTRY_WORDS
        self.timeout_ms = live.config.get("heartbeat_timeout_ms", 1000)
        if type(self.timeout_ms) is not int or not 100 <= self.timeout_ms <= 60000:
            raise ValueError("heartbeat_timeout_ms 100..60000 olmalı")
        self.deadman = live.config.get("deadman", True) is True
        if "scratch" in live.config:
            first, last = spans([live.config["scratch"]])[0]
            if first < end and self.base < last:
                raise ValueError("live.scratch ve live.mailbox çakışamaz")

    def address(self, word):
        return self.base + 4 * word

    def header(self):
        return self.live.read_words(self.base, 32, HEADER_WORDS)

    def status(self):
        words = self.header()
        if words[WORD["magic"]] != MAGIC:
            # Without the stub this RAM is application data; decoding it would invent armed/status fields.
            return {"magic_ok": False, "protocol": PROTOCOL, "stub_heartbeat": None, "armed": False,
                    "deadman_count": 0, "note": "Stub yok: mailbox alanı stub'a ait değil, içeriği yorumlanmadı"}
        pick = {name: words[index] for name, index in WORD.items() if name != "args"}
        pick["args"] = words[WORD["args"]:WORD["args"] + 4]
        return {"magic_ok": pick["magic"] == MAGIC, "version": pick["version"], "protocol": PROTOCOL,
                "stub_heartbeat": pick["stub_hb"], "host_heartbeat": pick["host_hb"],
                "status": STATUS.get(pick["status"], f"unknown({pick['status']})"),
                "armed": bool(pick["armed"]), "safe_count": pick["safe_count"],
                "timeout_ms": pick["timeout_ms"], "call_seq": pick["call_seq"], "done_seq": pick["done_seq"],
                "deadman_fired": pick["status"] == DEADMAN_FIRED, "deadman_count": pick["deadman_count"]}

    def require_alive(self):
        first = self.status()
        if not first["magic_ok"] or first["version"] != PROTOCOL:
            raise ValueError("Stub bulunamadı (magic/sürüm uyuşmuyor); önce stub yüklenmeli")
        for _ in range(10):
            time.sleep(0.05)
            if self.status()["stub_heartbeat"] != first["stub_heartbeat"]:
                return first
        raise ValueError("Stub heartbeat ilerlemiyor; stub çalışmıyor veya CPU durmuş")

    def heartbeat(self):
        """Increment host_hb only if the stub's magic is present (checked in the same request).

        Without the stub this RAM belongs to the application; returns False instead of writing it.
        """
        return self.live.target.increment_if(self.base, MAGIC, self.address(WORD["host_hb"]))

    def write(self, word, values):
        self.live.target.write(self.address(word), 32, values)

    def arm(self, rows):
        self.live.refuse_program_mutation()
        if len(rows) > self.capacity:
            raise ValueError(f"Güvenli durum tablosu kapasiteyi aşıyor ({self.capacity})")
        flat = [word for row in rows for word in row]
        self.write(WORD["armed"], [0])
        if not rows:
            # An empty table must not leave old rows for the fault handler to replay.
            self.write(WORD["safe_count"], [0])
        else:
            self.write(HEADER_WORDS, flat)
            self.write(WORD["timeout_ms"], [self.timeout_ms, len(rows)])
            self.heartbeat()
            self.write(WORD["armed"], [1])

    def call(self, entry, args, timeout_s):
        if len(args) > 4:
            raise ValueError("En fazla 4 argüman")
        self.require_alive()
        seq = (self.live.read_words(self.address(WORD["call_seq"]), 32, 1)[0] + 1) & 0xFFFFFFFF
        payload = [entry, *args, *([0] * (4 - len(args)))]
        self.write(WORD["entry"], payload)
        self.write(WORD["call_seq"], [seq])  # last: starts the call
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.heartbeat()
            head = self.header()
            if head[WORD["done_seq"]] == seq:
                code = STATUS.get(head[WORD["status"]], "unknown")
                if code != "ok":
                    raise ValueError(f"RAM parçası hata verdi: {code}, error={head[WORD['error']]:#x}")
                return {"result": head[WORD["result"]], "status": code, "call_seq": seq}
            time.sleep(0.01)
        raise TimeoutError("RAM çağrısı zaman aşımı; kod hâlâ çalışıyor olabilir, tekrar denenmedi. "
                           "Durdurmak için control halt veya reset-halt kullanın")


# ----------------------------------------------------------------------- pins

class PinState:
    """Host-recorded claims (not measured hardware state), stored beside the profile."""

    def __init__(self, profile):
        self.path = profile.path.with_suffix(".pins.local.json")
        self.uid = profile.expected.hex()
        self.data = {"version": 1, "uid_hex": self.uid, "claims": {}, "ram": None, "deadman_seen": 0}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"), object_pairs_hook=unique)
            if data.get("uid_hex") != self.uid:
                raise ValueError(f"{self.path.name} başka karta ait; elle inceleyip silin")
            self.data = data

    @property
    def claims(self):
        return self.data["claims"]

    def save(self):
        temp = self.path.with_name(self.path.name + ".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=True, indent=2, allow_nan=False), encoding="utf-8")
        temp.replace(self.path)


def merge_undo(undo, executed):
    result = [dict(row) for row in undo]
    for step in executed:
        if step["op"] not in ("write", "modify") or step.get("before") is None:
            continue
        match = next((r for r in result if r["address"] == step["address"] and r["width"] == step["width"]), None)
        if match is None:
            result.append({"address": step["address"], "width": step["width"], "mask": step["mask"],
                           "old": step["before"]})
        else:
            fresh = step["mask"] & ~match["mask"]
            match["old"] |= step["before"] & fresh
            match["mask"] |= step["mask"]
    return result


class Pins:
    def __init__(self, live, profile):
        self.live, self.profile = live, profile
        path = live.config.get("mcu_db")
        self.db = McuDb(profile.path.parent / path) if path else None
        self.config = profile.data.get("pins", {})
        self.state = PinState(profile)
        self.safe = {}
        if not self.config:
            return
        if self.db is None:
            raise ValueError("pins için live.mcu_db gerekli")
        for name, spec in self.config.items():
            self.validate(name, spec)

    def validate(self, name, spec):
        entry = self.db.pins.get(spec.get("mcu_pin"))
        if entry is None:
            raise ValueError(f"{name}: mcu_pin MCU veri dosyasında yok")
        if type(spec.get("protected", False)) is not bool:
            raise ValueError(f"{name}: protected true/false olmalı")
        if spec.get("protected"):
            return
        missing = [f for f in [*spec.get("functions", []), spec.get("safe_function")]
                   if f not in entry.get("functions", {})]
        if missing or not spec.get("safe_function"):
            raise ValueError(f"{name}: işlev(ler) MCU veri dosyasında yok veya safe_function eksik: {missing}")
        self.safe[name] = self.compile(name, spec["safe_function"], {}, safe=True)
        if self.live.stub is not None and self.live.stub.deadman:
            safe_entries(self.safe[name]["steps"])

    def compile(self, name, function, user, safe=False):
        spec = self.config.get(name)
        if spec is None:
            raise ValueError(f"Profilde olmayan pin: {name}")
        if spec.get("protected"):
            raise ValueError(f"Korumalı pin: {name} ({spec.get('reason', 'sebep belirtilmemiş')})")
        if function not in spec.get("functions", []) and not (safe and function == spec["safe_function"]):
            raise ValueError(f"{name} için izinli olmayan işlev: {function}; izinliler: {spec.get('functions', [])}")
        entry = self.db.pins[spec["mcu_pin"]]["functions"][function]
        recipe = self.db.recipes[entry["recipe"]]
        names = {}
        for key, expression in entry.get("params", {}).items():
            names[key] = evaluate(expression, names)
        inputs = recipe.get("inputs", {})
        unknown = set(user) - set(inputs)
        if unknown or set(inputs) & set(names):
            raise ValueError(f"Bilinmeyen/çakışan girdi: {sorted(unknown or set(inputs) & set(names))}")
        resolved = {}
        for key, rule in inputs.items():
            if key in user:
                value = user[key]
            elif "default" in rule:
                value = rule["default"]
            else:
                raise ValueError(f"Zorunlu girdi eksik: {key}")
            if type(value) is not int:
                raise ValueError(f"{key} tam sayı olmalı: {value!r}")
            limit = spec.get("limits", {}).get(key, {})
            low = max(rule.get("min", value), limit.get("min", value))
            high = min(rule.get("max", value), limit.get("max", value))
            if not low <= value <= high:
                raise ValueError(f"{key}={value!r} izinli aralık dışında ({low}..{high})")
            names[key] = resolved[key] = value
        steps = self.live.prepare(compile_steps(recipe, names))
        resources = [re.sub(r"\{(\w+)\}", lambda m: str(names[m.group(1)]), item)
                     for item in [*recipe.get("resources", []), *entry.get("resources", [])]]
        return {"pin": name, "function": function, "inputs": resolved, "resources": resources, "steps": steps}

    # -- planning (offline)
    def plan_apply(self, name, function, user):
        plan = self.compile(name, function, user)
        for other, claim in self.state.claims.items():
            shared = set(plan["resources"]) & set(claim.get("resources", []))
            if other != name and shared:
                raise ValueError(f"Kaynak çakışması: {sorted(shared)} zaten {other} pininde kullanımda")
        return plan

    def plan_release(self, name):
        if name not in self.safe:
            self.compile(name, "", {})  # raises the precise protected/unknown-pin error
        return self.safe[name]

    def plan_restore(self, name):
        claim = self.state.claims.get(name)
        if claim is None:
            raise ValueError(f"{name} için kayıtlı talep yok")
        steps = []
        for row in reversed(claim.get("undo", [])):
            full = (1 << row["width"]) - 1
            steps.append({"op": "write" if row["mask"] == full else "modify", "address": row["address"],
                          "width": row["width"], "mask": row["mask"], "value": row["old"], "verify": True})
        return {"pin": name, "steps": self.live.prepare(steps), "undo_complete": claim.get("undo_complete", False)}

    def listing(self):
        rows = []
        for name, spec in self.config.items():
            claim = self.state.claims.get(name)
            rows.append({"pin": name, "mcu_pin": spec["mcu_pin"], "protected": bool(spec.get("protected")),
                         "functions": spec.get("functions", []), "safe_function": spec.get("safe_function"),
                         "claim": claim and {k: claim[k] for k in ("function", "inputs", "status", "applied_at")},
                         "measured": False})
        return rows

    # -- execution
    def rows(self, extra=None):
        rows = []
        for name, claim in self.state.claims.items():
            if name != (extra or {}).get("pin"):
                rows += claim.get("safe_entries", [])
        if extra:
            rows += extra["safe_entries"]
        return rows

    def sync_stub(self, rows):
        stub = self.live.stub
        if stub is not None and stub.deadman:
            stub.arm(rows)

    def warn_stale(self):
        stub = self.live.stub
        if stub is None:
            return []
        status = stub.require_alive()
        armed_claims = stub.deadman and any(c.get("safe_entries") for c in self.state.claims.values())
        reset = armed_claims and not status["armed"]  # stub init zeroes the mailbox
        if status["deadman_count"] == self.state.data.get("deadman_seen", 0) and not reset:
            return []
        self.state.data["deadman_seen"] = status["deadman_count"]
        for claim in self.state.claims.values():
            claim["status"] = "stale_after_deadman"
        self.state.save()
        return [("dead-man tetiklenmiş veya stub yeniden başlamış: kayıtlı pin talepleri bayat; "
                 "pinler güvenli/reset durumunda olabilir")]

    def apply(self, plan):
        self.live.refuse_program_mutation()
        self.live.verify_build()
        warnings = self.warn_stale()
        entries = safe_entries(self.safe[plan["pin"]]["steps"]) if self.live.stub and self.live.stub.deadman else []
        previous = self.state.claims.get(plan["pin"], {})
        self.sync_stub(self.rows({"pin": plan["pin"], "safe_entries": entries}))  # arm before the first write
        error = None
        try:
            executed, outputs = self.live.run_steps(plan["steps"])
        except StepFailed as exc:
            executed, outputs, error = exc.executed, {}, exc
        self.state.claims[plan["pin"]] = {
            "function": plan["function"], "inputs": plan["inputs"], "resources": plan["resources"],
            "status": "partial" if error else "applied", "applied_at": utcnow(), "safe_entries": entries,
            "undo": merge_undo(previous.get("undo", []), executed),
            "undo_complete": previous.get("undo_complete", True) and all(
                s.get("before") is not None for s in executed if s["op"] in ("write", "modify"))}
        self.state.save()
        if error:
            raise error
        return {"pin": plan["pin"], "function": plan["function"], "inputs": plan["inputs"],
                "outputs": outputs, "steps": executed, "warnings": warnings, "measured": "register readback only"}

    def finish(self, name, plan):
        """Run a release/restore plan; the claim is dropped only if every step succeeded."""
        self.live.refuse_program_mutation()
        self.live.verify_build()
        try:
            executed, _ = self.live.run_steps(plan["steps"])
        except StepFailed:
            if name in self.state.claims:
                self.state.claims[name]["status"] = "partial_release"
                self.state.save()
            raise
        self.state.claims.pop(name, None)
        self.state.save()
        self.sync_stub(self.rows())
        return {"pin": name, "steps": executed}

    def safe_all(self, names):
        results = []
        for name in names:
            try:
                results.append({**self.finish(name, self.plan_release(name)), "ok": True})
            except (ValueError, OSError) as exc:
                results.append({"pin": name, "ok": False, "error": str(exc)})
        return results


# ------------------------------------------------------------------------ CLI

def parse_params(items):
    params = {}
    for item in items or []:
        key, separator, value = item.partition("=")
        if not separator or not key or key in params:
            raise ValueError(f"--param k=değer biçiminde ve tekil olmalı: {item}")
        params[key] = number(value)
    return params


def read_project_file(profile, name):
    path = (profile.root / name).resolve()
    if not path.is_relative_to(profile.root) or not path.is_file() or path.stat().st_size > 4_000_000:
        raise ValueError(f"Dosya proje kökü içinde, mevcut ve ≤4 MB olmalı: {name}")
    return path, path.read_bytes()


class Session:
    """One `serve`/`mcp` session. Profile, policy, MCU data, pin state and build verification are loaded
    once and shared by every request, so the flash check is not repeated while the dead-man waits."""

    def __init__(self, profile, target=None):
        self.profile = profile
        self.live = Live(profile, target)
        self.pins = Pins(self.live, profile)

    @property
    def target(self):
        return self.live.target

    def attach(self, target):
        """Use a new connection; the target may have been reflashed meanwhile, so verify again."""
        self.live.target = self.live.device.target = target
        self.live._verified = False
        self.live._beat_at = None


def run_live(args, profile):
    command, action = args.command, getattr(args, "action", None)
    execute = getattr(args, "execute", False)
    session = getattr(args, "_session", None)
    if session is not None:
        live, pins = session.live, session.pins
    else:
        live = Live(profile, None)
        pins = None if command == "reg" else Pins(live, profile)

    if command == "fault":
        from .arch import fault_evidence, supported

        if not supported(profile):
            return fault_evidence(None, profile)

    # Offline planning first: nothing below connects unless --execute or a read command.
    plan = None
    registers = None
    if command == "reg":
        svd = profile.svd()
        if action == "list":
            names = [args.peripheral] if args.peripheral else svd.peripherals()
            return {"registers": [{"name": r.name, "address": hex(r.address), "width": r.size}
                                  for p in names for r in svd.registers(p)
                                  if args.filter.casefold() in r.name.casefold()]}
        registers = []
        for name in args.names:
            item = svd.lookup(name)
            reg = getattr(item, "register", item)
            check_width(reg.address, reg.size)
            live.policy.check_read(reg.address, reg.size // 8)
            if overlaps(reg.address, reg.size // 8, live.policy.protected):
                raise ValueError(f"Okuma izni yok (korumalı alan): {reg.name}")
            if reg.side_effect or reg.access == "write-only":
                raise ValueError(f"Okuma izni yok (SVD okuma yan etkili veya yalnız-yazma): {reg.name}")
            if reg not in registers:
                registers.append(reg)
    if command == "pin" and action == "list":
        return {"pins": pins.listing(), "mcu_db": pins.db and pins.db.name,
                "note": "claim bilgisi ana makinede kayıtlıdır; donanım durumu ölçülmedi"}
    if command == "poke":
        plan = live.poke_plan(number(args.address), number(args.value), args.width,
                              None if args.mask is None else number(args.mask), not args.no_verify)
    elif command == "pin":
        if action == "apply":
            plan = pins.plan_apply(args.pin, args.function, parse_params(args.param))
        elif action == "release":
            plan = pins.plan_release(args.pin)
        else:
            plan = pins.plan_restore(args.pin)
    elif command == "safe":
        names = [n for n, s in pins.config.items() if not s.get("protected")] if args.all else list(pins.state.claims)
        plan = {"pins": names}
    elif command == "ram" and action == "build":
        build = live.config.get("ram_build")
        if not isinstance(build, dict) or not build.get("output"):
            raise ValueError("live.ram_build.argv ve output gerekli")
        plan = {**argv_plan(build.get("argv"), profile.root, build.get("timeout_s", 60)), "output": build["output"]}
    elif command == "ram" and action == "load":
        name = args.file or live.config.get("ram_build", {}).get("output")
        if not name:
            raise ValueError("--file veya live.ram_build.output gerekli")
        _, data = read_project_file(profile, name)
        plan = {**live.ram_plan(data, None if args.address is None else number(args.address)), "file": name}
    elif command == "ram" and action == "run":
        loaded = pins.state.data.get("ram")
        if not loaded:
            raise ValueError("Önce ram load ile bir parça yüklenmeli (ana makine kaydı yok)")
        entry = number(args.entry) if args.entry else loaded["address"]
        if not inside(entry, 2, [(loaded["address"], loaded["address"] + loaded["size"])]):
            raise ValueError("Giriş noktası yüklenen parçanın içinde olmalı")
        plan = {"entry": entry, "args": [number(a) for a in args.arg], "address": loaded["address"],
                "size": loaded["size"], "loaded_sha256": loaded["sha256"], "timeout_s": args.timeout}
        if not 0 < args.timeout <= 300 or len(plan["args"]) > 4:
            raise ValueError("timeout 0..300 sn, en fazla 4 argüman")
    if plan is not None and not execute:
        return {"plan": plan, "executed": False}

    if command == "ram" and action == "build":
        done = run_plan(plan, "RAM derlemesi")
        _, data = read_project_file(profile, plan["output"])
        return {"output": plan["output"], **live.ram_plan(data), "stdout": done.stdout}

    owned = session is None
    if owned:
        live.target = live.device.target = open_target(profile)
    try:
        if registers is not None:
            values = []
            for reg in registers:
                raw = live.peek(reg.address, width=reg.size)["values"][0]
                values.append({"name": reg.name, "address": hex(reg.address), "width": reg.size,
                               "raw_value": raw, "fields": svd.decode(reg, int(raw, 16))})
            return {"registers": values}
        return execute_live(args, profile, live, pins, plan)
    finally:
        if owned:
            live.target.close()


def execute_live(args, profile, live, pins, plan):
    command, action = args.command, getattr(args, "action", None)
    if command == "fault":
        from .arch import fault_evidence

        return fault_evidence(live.target, profile)
    if command == "watch-variables":
        return live.watch_variables(args.names, args.samples, args.interval_ms)
    if command == "peek":
        return live.peek(number(args.address), args.count, args.width)
    if command == "stub":
        if live.stub is None:
            raise ValueError("live.mailbox tanımlı değil")
        return live.stub.status()
    if command == "poke":
        return live.poke(plan)
    if command == "pin" and action == "apply":
        return pins.apply(plan)
    if command == "pin":
        return pins.finish(args.pin, plan)
    if command == "safe":
        if args.all and live.stub and live.read_words(live.stub.base, 32, 1)[0] == 0x32544145:
            from .interp import Program

            program = Program(live)
            return {"program": program.mutate("stop", program.snapshot()[40]), "executed": True}
        results = pins.safe_all(plan["pins"])
        return {"results": results, "ok": all(r["ok"] for r in results),
                "remaining_claims": list(pins.state.claims)}
    if command == "ram" and action == "load":
        _, data = read_project_file(profile, plan["file"])
        # Forget the previous snippet before touching scratch: a failed load leaves mixed bytes.
        pins.state.data["ram"] = None
        pins.state.save()
        result = live.ram_load(data, plan["address"])
        pins.state.data["ram"] = {"address": result["address"], "size": result["size"],
                                  "sha256": result["sha256"], "loaded_at": utcnow()}
        pins.state.save()
        return result
    if command == "ram" and action == "run":
        if live.ram_digest(plan["address"], plan["size"]) != plan["loaded_sha256"]:
            raise ValueError("RAM'deki parça kayıtlı yüklemeyle uyuşmuyor (reset veya başka yazma); "
                             "çalıştırılmadı, önce ram load")
        started = time.monotonic()
        result = live.ram_run(plan["entry"], plan["args"], plan["timeout_s"])
        return {**result, "entry": plan["entry"], "elapsed_s": round(time.monotonic() - started, 3)}
    raise ValueError("Bilinmeyen canlı komut")
