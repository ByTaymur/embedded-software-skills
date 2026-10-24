"""Profile validation, typed ELF symbols and framed OpenOCD Tcl RPC."""
import hashlib
import io
import json
import math
import socket
import struct
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from elftools.elf.elffile import ELFFile

TYPES = {"u8": "B", "i8": "b", "u16": "H", "i16": "h", "u32": "I",
         "i32": "i", "u64": "Q", "i64": "q", "f32": "f", "f64": "d"}


def number(value):
    if type(value) is int:
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError("Tam sayı gerekli")


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Yinelenen JSON alanı: {key}")
        result[key] = value
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()


def utcnow():
    return datetime.now(UTC).isoformat()


def spans(items):
    result = []
    for item in items:
        start, size = number(item["address"]), number(item["size"])
        if start < 0 or size <= 0 or start + size > 2**64:
            raise ValueError("Geçersiz bellek aralığı")
        result.append((start, start + size))
    return result


def argv_plan(argv, root, timeout_s):
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x for x in argv):
        raise ValueError("Komut, boş olmayan argv metin listesi olmalı")
    return {"argv": argv, "cwd": str(root), "timeout_s": timeout_s}


def run_plan(plan, label):
    """Run an argv plan without a shell; a non-zero exit is an error carrying the tool output."""
    result = subprocess.run(plan["argv"], cwd=plan["cwd"], timeout=plan["timeout_s"],
                            capture_output=True, text=True, errors="replace", check=False)
    if result.returncode:
        raise ValueError(f"{label} başarısız ({result.returncode}): {result.stdout}\n{result.stderr}")
    return result


def tcl_string(value):
    # Jim Tcl in OpenOCD may have no 'binary' command. Quote substitution characters.
    escapes = {"\\": "\\\\", '"': '\\"', "$": "\\$", "[": "\\[", "]": "\\]"}
    value = str(value)
    if any(ord(c) < 32 for c in value):
        raise ValueError("Tcl veri alanında kontrol karakteri olamaz")
    return '"' + "".join(escapes.get(c, c) for c in value) + '"'


def rpc_script(script):
    # Do not put user paths inside a brace-delimited catch body: braces in a
    # quoted filename still affect Tcl's outer brace parser.
    return (f"set __eat_code [catch {tcl_string(script)} __eat_result]; "
            'format "%s\\n%s" [expr {$__eat_code ? "ERROR" : "OK"}] $__eat_result')


class Profile:
    def __init__(self, path, require_target=True):
        self.path = Path(path).resolve()
        raw = self.path.read_bytes()
        self.sha = digest(raw)
        self.data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique)
        version = self.data.get("schema_version")
        if version not in (1, 2):
            raise ValueError("schema_version 1 veya 2 gerekli")
        if version == 1 and ("live" in self.data or "pins" in self.data):
            raise ValueError("live/pins alanları için schema_version 2 gerekli")
        self.root = (self.path.parent / self.data.get("project_root", ".")).resolve()
        self.name = self.data["name"]
        self.image = None
        if not require_target:
            return  # Build/search/server startup do not require a connected board's UID.
        self.connection = self.data["connection"]
        self.transport = self.connection.get("transport", "openocd")
        port = self.connection.get("port", 6666)
        if self.transport == "openocd":
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("Geçersiz Tcl portu")
        elif self.transport == "serial":
            baud = self.connection.get("baud", 115200)
            if not isinstance(port, str) or not port or type(baud) is not int or not 1200 <= baud <= 20_000_000:
                raise ValueError("serial bağlantı için port adı (COM5, /dev/ttyACM0) ve baud gerekli")
        else:
            raise ValueError("connection.transport openocd veya serial olmalı")
        timeout = self.connection.get("timeout_s", 10)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError("timeout_s 0..300 aralığında olmalı")
        self.identity = self.data["identity"]
        self.uid_address = number(self.identity["address"])
        self.uid_size = number(self.identity["size"])
        expected = bytes.fromhex(self.identity["expected_hex"])
        if not 1 <= self.uid_size <= 256 or len(expected) != self.uid_size or not any(expected) or all(x == 255 for x in expected):
            raise ValueError("Gerçek karttan alınmış, boş olmayan expected_hex gerekli")
        self.expected = expected
        self.variables = self.data.get("variables", {})
        self.ranges = self.data.get("read_ranges", [])
        spans(self.ranges + self.data.get("flash_ranges", []))
        self.check_read(self.uid_address, self.uid_size)
        for spec in self.variables.values():
            if spec["type"] not in TYPES or type(spec.get("writable", False)) is not bool:
                raise ValueError("Geçersiz değişken tipi/yazma izni")
            if ("symbol" in spec) == ("address" in spec):
                raise ValueError("Her değişkende yalnız symbol veya address gerekli")

    def check_read(self, address, size):
        if address < 0 or size <= 0 or not any(number(r["address"]) <= address and
                address + size <= number(r["address"]) + number(r["size"]) for r in self.ranges):
            raise ValueError(f"İzin verilen okuma alanı dışında: {address:#x}+{size}")

    def artifact(self):
        if self.image is None:
            image = Image(self.root / self.data["artifact"]["path"])
            if image.sha != self.data["artifact"]["sha256"]:
                raise ValueError("ELF/AXF SHA256 eşleşmiyor; doğru build profilini seçin")
            self.image = image
        return self.image

    def variable(self, name):
        spec = self.variables[name]
        size = struct.calcsize(TYPES[spec["type"]])
        address = number(spec["address"]) if "address" in spec else self.artifact().symbol(spec["symbol"], size)
        self.check_read(address, size)
        return address, size, spec

    @property
    def endian(self):
        order = self.data.get("byte_order")
        if order not in ("little", "big"):
            raise ValueError("byte_order little veya big olmalı")
        if "artifact" in self.data and self.artifact().little != (order == "little"):
            raise ValueError("Profil ve ELF byte order farklı")
        return "<" if order == "little" else ">"


class Image:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.raw = self.path.read_bytes()
        self.sha = digest(self.raw)
        self.elf = ELFFile(io.BytesIO(self.raw))
        self.little = self.elf.little_endian

    def symbols(self):
        table = self.elf.get_section_by_name(".symtab")
        if table is None:
            raise ValueError("ELF sembol tablosu yok (stripped build)")
        return [s for s in table.iter_symbols() if s["st_info"]["type"] == "STT_OBJECT" and
                s["st_shndx"] != "SHN_UNDEF" and s.name]

    def symbol(self, name, size):
        address, actual = self.object(name)
        if actual != size:
            raise ValueError(f"Sembol tekil değil veya tip boyutu farklı: {name}")
        return address

    def object(self, name):
        """(address, size) of one data object, e.g. the stub's `eat_mailbox` array."""
        matches = [s for s in self.symbols() if s.name == name]
        if len(matches) != 1 or not matches[0]["st_size"]:
            raise ValueError(f"Sembol tekil değil veya boyutsuz: {name}")
        return matches[0]["st_value"], matches[0]["st_size"]

    def regions(self, ranges):
        result = []
        for segment in self.elf.iter_segments():
            if segment["p_type"] != "PT_LOAD" or not segment["p_filesz"]:
                continue
            address, data = segment["p_paddr"], segment.data()
            if not any(number(r["address"]) <= address and address + len(data) <=
                       number(r["address"]) + number(r["size"]) for r in ranges):
                raise ValueError(f"PT_LOAD flash alanı dışında: {address:#x}")
            result.append((address, data))
        if not result:
            raise ValueError("Doğrulanacak flash PT_LOAD bulunamadı")
        return result


class RPC:
    def __init__(self, connection):
        self.sock = socket.create_connection((connection.get("host", "127.0.0.1"), connection.get("port", 6666)),
                                             connection.get("timeout_s", 10))
        self.sock.settimeout(connection.get("timeout_s", 10))
        self.buffer = b""

    @property
    def closed(self):
        return self.sock is None

    def close(self):
        if self.sock is not None:
            self.sock.close()  # Never shutdown OpenOCD or resume/reset the CPU.
            self.sock = None

    def call(self, script):
        if self.sock is None:
            raise ConnectionError("OpenOCD bağlantısı önceki bir hatadan sonra kapatıldı; yeni bağlantı açın")
        try:
            self.sock.sendall(rpc_script(script).encode("utf-8") + b"\x1a")
            while b"\x1a" not in self.buffer:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("OpenOCD bağlantısı kapandı; yazma sonucu belirsiz olabilir")
                self.buffer += chunk
                if len(self.buffer) > 4 * 1024 * 1024:
                    raise ValueError("OpenOCD yanıtı çok büyük")
        except BaseException:
            # A late reply would be read as the next request's answer; drop the stream instead.
            self.close()
            raise
        frame, self.buffer = self.buffer.split(b"\x1a", 1)
        response = frame.decode("utf-8")
        if not response.startswith("OK\n"):
            raise ValueError("OpenOCD: " + response)
        return response[3:]


def identity_guard(profile):
    """Tcl prefix that aborts the whole request unless the attached board's UID matches the profile."""
    expected = " ".join(str(x) for x in profile.expected)
    return (f"set __eat_uid [read_memory {profile.uid_address} 8 {profile.uid_size}]; "
            f"if {{[llength $__eat_uid] != {profile.uid_size}}} {{error IDENTITY_MISMATCH}}; "
            f"foreach __eat_actual $__eat_uid __eat_expected {{{expected}}} "
            '{if {$__eat_actual != $__eat_expected} {error IDENTITY_MISMATCH}}; ')


class OpenOcdTarget:
    """Target memory through OpenOCD Tcl RPC. Every request re-checks the board identity in the same
    Tcl evaluation, so a swapped board never receives a write. Other transports offer the same methods."""

    kind = "openocd"

    def __init__(self, profile, rpc):
        self.rpc, self.guard = rpc, identity_guard(profile)

    @property
    def closed(self):
        return self.rpc.closed

    def close(self):
        self.rpc.close()

    def script(self, body):
        return self.rpc.call(self.guard + body)

    def read(self, address, width, count):
        values = self.script(f"read_memory {address} {width} {count}").split()
        if len(values) != count:
            raise ValueError("Eksik bellek okuması")
        return [int(v, 0) for v in values]

    def halted_registers(self, names):
        if any(not name.isidentifier() for name in names):
            raise ValueError("Geçersiz register adı")
        registers = " ".join(names)
        response = self.script(
            'if {[[target current] curstate] != "halted"} {set __regs {}} else {'
            f'set __r [get_reg -force {{{registers}}}]; list '
            + " ".join(f"[dict get $__r {name}]" for name in names) + "}")
        values = response.split()
        if not values:
            return None
        if len(values) != len(names):
            raise ValueError("Eksik register okuması")
        return dict(zip(names, (int(v, 0) for v in values), strict=True))

    def read_halted(self, address, width, count):
        values = self.script('if {[[target current] curstate] != "halted"} {error CORE_NOT_HALTED}; '
                             f"read_memory {address} {width} {count}").split()
        if len(values) != count:
            raise ValueError("Eksik bellek okuması")
        return [int(v, 0) for v in values]

    def write(self, address, width, values):
        self.script(f"write_memory {address} {width} {{{' '.join(map(str, values))}}}")

    def modify(self, address, width, mask, value):
        """reg = (reg & ~mask) | value in one request; returns the register value before the write."""
        full = (1 << width) - 1
        script = (f"set __v [lindex [read_memory {address} {width} 1] 0]; "
                  f"write_memory {address} {width} [expr {{($__v & {full & ~mask}) | {value}}}]; set __v")
        return int(self.script(script).strip(), 0)

    def increment_if(self, check_address, expected, address):
        """Increment a 32-bit word only if check_address holds expected (same request); True if done."""
        done = self.script(
            f"if {{[lindex [read_memory {check_address} 32 1] 0] == {expected}}} "
            f"{{write_memory {address} 32 [expr {{([lindex [read_memory {address} 32 1] 0] + 1) & 0xffffffff}}]; "
            "set __hb 1} else {set __hb 0}")
        return done.strip() == "1"


def open_target(profile):
    if profile.transport == "serial":
        from .link import (
            SerialTarget,  # pyserial is optional; only serial profiles need it
        )

        return SerialTarget(profile)
    return OpenOcdTarget(profile, RPC(profile.connection))


def openocd_only(target, command):
    if getattr(target, "kind", None) != "openocd":
        raise ValueError(f"{command} yalnız OpenOCD bağlantısında var (halt/reset/flash debug sunucusu ister)")
    return target


class Device:
    def __init__(self, profile, target):
        self.profile, self.target = profile, target

    def read(self, address, size, width=8):
        self.profile.check_read(address, size)
        if width not in (8, 16, 32, 64) or size % (width // 8) or address % (width // 8):
            raise ValueError("Geçersiz/hizasız bellek okuma genişliği")
        count = size // (width // 8)
        values = self.target.read(address, width, count)
        order = self.profile.data["byte_order"]
        data = b"".join(v.to_bytes(width // 8, order) for v in values)
        if len(data) != size:
            raise ValueError("Eksik bellek okuması")
        return data

    def snapshot(self, names):
        values = {}
        for name in names:
            address, size, spec = self.profile.variable(name)
            width = number(spec.get("access_bits", min(size * 8, 32)))
            raw = self.read(address, size, width)
            value = struct.unpack(self.profile.endian + TYPES[spec["type"]], raw)[0]
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"Sonlu olmayan ölçüm: {name}; raw_hex={raw.hex()}")
            values[name] = value
        return values  # Sequential observations, not an atomic snapshot.

    def verify(self, tick=None):
        """Compare flash with the artifact; tick() runs between chunks to feed the stub heartbeat."""
        total = 0
        for address, data in self.profile.artifact().regions(self.profile.data["flash_ranges"]):
            for offset in range(0, len(data), 256):
                if tick:
                    tick()
                expected = data[offset:offset + 256]
                if self.read(address + offset, len(expected)) != expected:
                    raise ValueError(f"Flash build eşleşmiyor: {address + offset:#x}")
                total += len(expected)
        return {"verified_bytes": total, "artifact_sha256": self.profile.artifact().sha,
                "scope": "all file-backed PT_LOAD bytes; unoccupied flash excluded"}

    def write_plan(self, name, value):
        address, size, spec = self.profile.variable(name)
        if spec.get("writable") is not True:
            raise ValueError(f"Yazma izni yok: {name}")
        parsed = float(value) if spec["type"].startswith("f") else number(value)
        if not math.isfinite(parsed) or not spec["min"] <= parsed <= spec["max"]:
            raise ValueError("Değer profil limitleri dışında")
        raw = struct.pack(self.profile.endian + TYPES[spec["type"]], parsed)
        return {"name": name, "address": address, "value": parsed, "bytes_hex": raw.hex(), "size": size}

    def write(self, plan):
        self.verify()
        # The transport rechecks the UID in the same request as the write. Never retry a mutation.
        width = plan["size"] * 8
        if width not in (8, 16, 32, 64) or plan["address"] % plan["size"]:
            raise ValueError("Hizalı 8/16/32/64 bit yazma gerekli")
        word = int.from_bytes(bytes.fromhex(plan["bytes_hex"]), self.profile.data["byte_order"])
        self.target.write(plan["address"], width, [word])
        actual = self.read(plan["address"], plan["size"], width).hex()
        return {**plan, "readback_hex": actual, "readback_matches": actual == plan["bytes_hex"],
                "note": "RAM firmware tarafından yeniden değiştirilebilir; fiziksel sonuç ölçülmedi"}
