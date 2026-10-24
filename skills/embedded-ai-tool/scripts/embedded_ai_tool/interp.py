"""Static live-program compiler and mailbox v2 client; no transport-specific mutations."""
import copy
import hashlib
import json
import struct
import time
import zlib

from .core import number, unique
from .live import Pins, safe_entries

MAGIC = 0x32544145
WORD = {"request_seq": 26, "command": 27, "args": 28, "ack_seq": 36, "status": 37,
        "error": 38, "result": 39, "generation": 40, "active_bank": 41, "run_state": 42,
        "active_crc": 43, "boot_id": 44, "state_seq": 45, "upload_id": 46,
        "received_bytes": 47, "candidate_state": 48, "task_fault_id": 49}
COMMAND = {"begin": 0x10, "chunk": 0x11, "verify": 0x12, "commit": 0x13,
           "abort": 0x14, "stop": 0x15, "param": 0x16, "message": 0x17}
ERRORS = ("OK", "FORMAT", "CAPACITY", "OPCODE", "RESERVED", "INDEX", "PC", "ALLOW", "DISABLED",
          "CRC", "STATE", "STALE_GENERATION", "BUDGET_EXCEEDED", "EVENT_OVERFLOW", "DEADMAN", "PORT",
          "RANGE", "MIGRATION", "BUSY_PROGRAM")
OPS = {"nop": 0, "const": 1, "mov": 2, "load_var": 3, "store_var": 4, "load_param": 5,
       "add": 6, "sub": 7, "mul": 8, "div": 9, "mod": 10, "bit": 11, "cmp": 16,
       "br_true": 17, "jump": 18, "gpio_read": 32, "gpio_write": 33, "gpio_mode": 34,
       "adc_start": 35, "adc_read": 36, "pwm_set": 37, "timer_set": 48, "wait_timer": 49,
       "delay": 50, "wait_event": 51, "yield": 52, "emit_raw": 64, "end": 127}
ROW_BYTES = (0, 48, 8, 32, 20, 24, 48, 16)
U32 = 0xFFFFFFFF


def uint(value, label="değer", low=0, high=U32):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}: {low}..{high} tam sayı gerekli")
    return value


def fields(obj, allowed, required=()):
    if not isinstance(obj, dict) or set(obj) - set(allowed) or set(required) - set(obj):
        raise ValueError(f"Şema alanları: izinli {allowed}, zorunlu {required}")


def ident(name):
    if type(name) is int:
        return uint(name, "kimlik", 1, 65535)
    if not isinstance(name, str) or not name or len(name) > 128:
        raise ValueError("Kimlik 1..128 karakter olmalı")
    return zlib.crc32(name.encode()) % 65535 + 1


def pack_rows(rows):
    return b"".join(struct.pack("<" + "I" * len(row), *row) for row in rows)


def image_sections(image):
    if len(image) < 24 or image[:4] != b"EATI":
        raise ValueError("Görüntü başlığı geçersiz")
    version, head, total, bytecode, capability, count = struct.unpack_from("<HHIIII", image, 4)
    if version != 1 or bytecode != 1 or total != len(image) or count != 7 or head != 136:
        raise ValueError("Görüntü biçimi geçersiz")
    sections = {}
    intervals = []
    for index in range(count):
        kind, offset, length, rows = struct.unpack_from("<IIII", image, 24 + 16 * index)
        if (kind not in range(1, 8) or kind in sections or offset < head or offset % 8
                or length != rows * ROW_BYTES[kind] or offset + length > total
                or any(length and b > offset and offset + length > a for a, b in intervals)):
            raise ValueError("Görüntü bölümü geçersiz")
        intervals.append((offset, offset + length))
        sections[kind] = image[offset:offset + length]
    return capability, sections


class Compiler:
    """Profile/recipe checks precede lowering. Port catalog ids must be explicitly reviewed."""

    def __init__(self, live, pins=None):
        self.live = live
        self.pins = pins or Pins(live, live.profile)
        self.config = live.config.get("interpreter", {})
        self.capability_hash = uint(self.config.get("capability_hash"), "capability_hash")
        self.catalog = self.config.get("resources", {})
        self.tasks, self.code, self.variables, self.params = [], [], [], []
        self.events, self.allow, self.safe = [], [], []
        self.owners, self.bindings, self.param_slots, self.names = {}, {}, {}, {}
        self.generated = []

    def bind(self, pin, function, owner, inputs=None):
        key = (pin, function, owner)
        if key in self.bindings:
            return self.bindings[key]
        if pin in self.owners and self.owners[pin] != owner:
            raise ValueError(f"Exclusive kaynak çakışması: {pin}")
        if pin in self.pins.state.claims:
            raise ValueError(f"Kaynak pin apply ile kullanımda: {pin}")
        self.owners[pin] = owner
        spec = self.catalog.get(pin)
        if not isinstance(spec, dict) or function not in spec.get("functions", {}):
            raise ValueError(f"Port kataloğunda pin/işlev yok: {pin}/{function}")
        # Reuse the existing recipe and Policy checks, including protected and side effects.
        recipe = self.pins.plan_apply(pin, function, spec.get("inputs", {}) if inputs is None else inputs)
        for resource in recipe["resources"]:
            other = self.names.setdefault(resource, owner)
            if other != owner:
                raise ValueError(f"Periferal kaynağı çakışması: {resource}")
        safe = safe_entries(self.pins.safe[pin]["steps"])
        for entry in safe:
            if entry not in self.safe:
                self.safe.append(entry)
        kind = {"gpio_in": 1, "gpio_out": 1, "adc": 2, "pwm": 3}.get(function)
        if kind is None:
            raise ValueError(f"Bu dilimde desteklenmeyen işlev: {function}")
        if kind == 1 and spec["functions"][function] != (1 if function == "gpio_out" else 0):
            raise ValueError("Port GPIO işlev kimliği giriş=0/çıkış=1 olmalı")
        address = number(spec["address"])
        width, length, mask = spec.get("width", 32), spec.get("length", 4), spec.get("mask", U32)
        uint(width, "width")
        if width not in (8, 16, 32) or address % (width // 8) or length < width // 8:
            raise ValueError("Port kataloğu erişim boyutu/hizası geçersiz")
        if function == "gpio_in" or kind == 2:
            self.live.policy.check_read(address, length)
        else:
            self.live.policy.check_write(address, length)
        limits = spec.get("limits", {})
        lo, hi = limits.get("min0", 0), limits.get("max0", 4095 if kind == 2 else 1)
        lo1, hi1 = limits.get("min1", 0), limits.get("max1", 0)
        entry = self.pins.db.pins[self.pins.config[pin]["mcu_pin"]]["functions"][function]
        rules = self.pins.db.recipes[entry["recipe"]].get("inputs", {})
        profile_limits = self.pins.config[pin].get("limits", {})
        for parameter, axis in (("level" if kind == 1 else "duty_permille", 0), ("freq", 1)):
            for rule in (rules.get(parameter, {}), profile_limits.get(parameter, {})):
                if axis == 0:
                    lo, hi = max(lo, rule.get("min", lo)), min(hi, rule.get("max", hi))
                else:
                    lo1, hi1 = max(lo1, rule.get("min", lo1)), min(hi1, rule.get("max", hi1))
        index = len(self.allow)
        self.allow.append([ident(f"{pin}:{function}"), kind, uint(spec["id"], "resource"),
                           uint(spec["functions"][function], "function"), uint(address), uint(length), width,
                           uint(mask, "mask", 1, (1 << width) - 1), uint(lo), uint(hi), uint(lo1), uint(hi1)])
        if lo > hi or lo1 > hi1:
            raise ValueError("Port sınırları geçersiz")
        # Safe writes must be attributable to this owned envelope for END/removal.
        if any(not address <= r[0] <= address + length - r[1] // 8 for r in safe):
            raise ValueError("Safe satırları port kaynak zarfına sığmıyor")
        self.bindings[key] = index
        return index

    def event(self, name, kind, channel, owner, period=0):
        row = [ident(name), kind, ident(channel), owner, period, 0]
        if row not in self.events:
            self.events.append(row)
        return self.events.index(row)

    def compile(self, program):
        fields(program, ("schema_version", "expected_generation", "params", "tasks", "deadman"),
               ("schema_version", "expected_generation", "tasks"))
        if program["schema_version"] != 1 or type(program["schema_version"]) is not int:
            raise ValueError("Program schema_version 1 olmalı")
        if program.get("deadman", True) is not True or not self.live.stub or not self.live.stub.deadman:
            raise ValueError("Yorumlayıcı dead-man zorunlu")
        uint(program["expected_generation"], "expected_generation", 0, U32 - 1)
        params = program.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("params nesne olmalı")
        if len(params) > self.config.get("params", 8):
            raise ValueError("Parametre kapasitesi aşıldı")
        for name, spec in params.items():
            fields(spec, ("type", "value", "min", "max"), ("type", "value", "min", "max"))
            if spec["type"] != "u32":
                raise ValueError("Yalnız u32 destekleniyor")
            lo, hi = uint(spec["min"]), uint(spec["max"])
            self.param_slots[name] = len(self.params)
            self.params.append([ident(name), uint(spec["value"], name, lo, hi), lo, hi, 1])
        tasks = program["tasks"]
        if not isinstance(tasks, list):
            raise ValueError("tasks liste olmalı")
        if len(tasks) > self.config.get("tasks", 4) or any(not isinstance(task, dict) for task in tasks):
            raise ValueError("Görev kapasitesi/şeması geçersiz")
        ids = [ident(t.get("id")) for t in tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("Görev kimlikleri çakışıyor")
        for task in tasks:
            self.lower_task(task)
        if len(tasks) + len(self.generated) > self.config.get("tasks", 4):
            raise ValueError("Üretilmiş pulse görevleri görev kapasitesini aşıyor")
        for task in self.generated:
            self.lower_task(task)
        for rows, capacity, label in ((self.tasks, 4, "tasks"), (self.params, 8, "params"),
                                      (self.events, 16, "events"), (self.allow, 16, "allow"), (self.safe, 16, "safe")):
            if len(rows) > self.config.get(label, capacity):
                raise ValueError(f"Kapasite aşıldı: {label}")
        for rows in (self.tasks, self.params, self.allow):
            if len({r[0] for r in rows}) != len(rows):
                raise ValueError("Sayısal kimlik çakışması")
        if len({(r[0], r[1]) for r in self.variables}) != len(self.variables):
            raise ValueError("Değişken sayısal kimlik çakışması")
        if len({r[2] for r in self.allow}) != len(self.allow):
            raise ValueError("Aynı port kaynağı birden fazla işleve atanamaz")
        event_ids = {}
        for event in self.events:
            signature = tuple(event[1:3])
            if event_ids.setdefault(event[0], signature) != signature:
                raise ValueError("Olay sayısal kimlik çakışması")
        payloads = [pack_rows(self.tasks), b"".join(self.code), pack_rows(self.variables),
                    pack_rows(self.params), pack_rows(self.events), pack_rows(self.allow), pack_rows(self.safe)]
        header_bytes = 136
        body, descriptors = bytearray(), []
        for kind, data in enumerate(payloads, 1):
            body.extend(b"\0" * (-(header_bytes + len(body)) % 8))
            descriptors.append((kind, header_bytes + len(body), len(data), len(data) // ROW_BYTES[kind]))
            body.extend(data)
        image = (struct.pack("<4sHHIIII", b"EATI", 1, header_bytes, header_bytes + len(body), 1,
                             self.capability_hash, 7) + pack_rows(descriptors) + body)
        if len(image) > self.config.get("image_bytes", 2048):
            raise ValueError("Görüntü banka kapasitesini aşıyor")
        return Compiled(bytes(image), program)

    def lower_task(self, task):
        fields(task, ("id", "revision", "resources", "trigger", "vars", "steps"), ("id", "steps"))
        owner = ident(task["id"])
        if not isinstance(task["steps"], list) or len(task["steps"]) > 256:
            raise ValueError("Görev adımları en fazla 256 öğelik liste olmalı")
        if not isinstance(task.get("vars", []), list) or len(task.get("vars", [])) > self.config.get("vars", 16):
            raise ValueError("Görev değişken şeması/kapasitesi geçersiz")
        resources = task.get("resources", [])
        if not isinstance(resources, list) or len(set(resources)) != len(resources):
            raise ValueError("resources tekil liste olmalı")
        if any(name not in self.pins.config or self.pins.config[name].get("protected") for name in resources):
            raise ValueError("Kaynak profil dışında veya korumalı")
        start, var_start = len(self.code), len(self.variables)
        local, code, labels, patches = {}, [], {}, []
        regs = {}
        mask = 0

        def reg(name):
            if type(name) is int:
                return uint(name, "register", 0, 7)
            ident(name)
            if name not in regs:
                if len(regs) >= 4:
                    raise ValueError("En fazla dört sembolik geçici (diğerleri derleyici için)")
                regs[name] = len(regs)
            return regs[name]

        def ins(op, a=0, b=0, c=0, k=0):
            code.append([op, a, b, c, k])

        def label(name):
            if name in labels:
                raise ValueError("Tekrarlanan etiket")
            labels[name] = len(code)

        def branch(op, target, a=0):
            patches.append((len(code), target))
            ins(op, a)

        def binding(pin, function, inputs=None):
            nonlocal mask
            if pin not in resources:
                raise ValueError(f"Kaynak görevde bildirilmemiş: {pin}")
            index = self.bind(pin, function, owner, inputs)
            if function == "adc" and task.get("trigger", {}).get("kind") == "periodic":
                if task["trigger"]["period_ms"] < self.allow[index][10]:
                    raise ValueError("ADC periyodu port hız sınırının altında")
            mask |= 1 << index
            return index

        def variable(spec):
            fields(spec, ("id", "type", "initial", "min", "max", "preserve"), ("id",))
            if spec.get("type", "u32") != "u32" or type(spec.get("preserve", False)) is not bool:
                raise ValueError("Değişken tipi/preserve geçersiz")
            name = spec["id"]
            if name in local:
                raise ValueError("Tekrarlanan değişken")
            local[name] = len(local)
            lo, hi = uint(spec.get("min", 0)), uint(spec.get("max", U32))
            self.variables.append([owner, ident(name), 1, 1, uint(spec.get("initial", 0), name, lo, hi),
                                   lo, hi, int(spec.get("preserve", False))])
            return local[name]

        for spec in task.get("vars", []):
            variable(spec)
        trigger = task.get("trigger", {"kind": "once"})
        fields(trigger, ("kind", "period_ms", "message_id", "event_id", "channel"), ("kind",))
        label("_entry")
        if trigger["kind"] == "periodic":
            period = uint(trigger.get("period_ms"), "period_ms", 1, 0x7FFFFFFF)
            event = self.event(f"{task['id']}:period", 3, f"{task['id']}:period", owner, period)
            ins(51, 6, 7, k=event)
        elif trigger["kind"] in ("message", "threshold"):
            kind = 5 if trigger["kind"] == "message" else 4
            name = trigger.get("message_id", trigger.get("event_id"))
            event = self.event(name, kind, trigger.get("channel", name), owner)
            ins(51, 0, 7, k=event)
        elif trigger["kind"] != "once":
            raise ValueError("Desteklenmeyen trigger")
        for index, step in enumerate(task["steps"]):
            if not isinstance(step, dict):
                raise ValueError("Adım nesne olmalı")
            op = step.get("op")
            if op == "analog_read":
                fields(step, ("op", "pin", "dst"), ("pin", "dst"))
                h, dst = binding(step["pin"], "adc"), reg(step["dst"])
                ins(35, k=h)
                label(f"_adc{index}")
                ins(36, dst, 5, k=h)
                branch(17, f"_ready{index}", 5)
                ins(52)
                branch(18, f"_adc{index}")
                label(f"_ready{index}")
                ins(52)
            elif op == "gpio_write":
                fields(step, ("op", "pin", "value"), ("pin", "value"))
                h = binding(step["pin"], "gpio_out")
                if type(step["value"]) is int:
                    value = uint(step["value"], "GPIO", 0, 1)
                    if not self.allow[h][8] <= value <= self.allow[h][9]:
                        raise ValueError("GPIO değeri port/profil sınırı dışında")
                    ins(1, 4, k=value)
                    src = 4
                else:
                    src = reg(step["value"])
                ins(33, src, k=h)
            elif op == "gpio_read":
                fields(step, ("op", "pin", "dst"), ("pin", "dst"))
                ins(32, reg(step["dst"]), k=binding(step["pin"], "gpio_in"))
            elif op == "gpio_mode":
                fields(step, ("op", "pin", "function"), ("pin", "function"))
                if step["function"] not in ("gpio_in", "gpio_out"):
                    raise ValueError("gpio_mode işlevi GPIO olmalı")
                ins(34, k=binding(step["pin"], step["function"]))
            elif op == "pwm_set":
                fields(step, ("op", "pin", "duty", "frequency"), ("pin", "duty", "frequency"))
                duty, freq = step["duty"], step["frequency"]
                inputs = {"duty_permille": uint(duty), "freq": uint(freq)} if type(duty) is int and type(freq) is int else None
                h = binding(step["pin"], "pwm", inputs)
                if ((type(duty) is int and not self.allow[h][8] <= duty <= self.allow[h][9])
                        or (type(freq) is int and not self.allow[h][10] <= freq <= self.allow[h][11])):
                    raise ValueError("PWM değeri port/profil sınırı dışında")
                if type(duty) is int:
                    ins(1, 4, k=duty)
                    duty = 4
                else:
                    duty = reg(duty)
                if type(freq) is int:
                    ins(1, 5, k=freq)
                    freq = 5
                else:
                    freq = reg(freq)
                ins(37, duty, freq, k=h)
            elif op == "emit":
                fields(step, ("op", "channel", "value"), ("channel", "value"))
                event = self.event(f"{task['id']}:sample:{step['channel']}", 1, step["channel"], owner)
                ins(64, reg(step["value"]), 7, k=event)
            elif op == "on_rising_threshold":
                fields(step, ("op", "value", "param", "hysteresis", "actions"),
                       ("value", "param", "hysteresis", "actions"))
                param = self.param_slots[step["param"]]
                hyst = uint(step["hysteresis"])
                if self.params[param][2] < hyst:
                    raise ValueError("Histerezis alt sınırı u32 altında")
                slot = variable({"id": f"_above{index}", "max": 1, "preserve": True})
                value = reg(step["value"])
                ins(3, 4, k=slot)
                branch(17, f"_above{index}", 4)
                ins(5, 5, k=param)
                ins(16, 4, value, 5, 5)  # value >= upper
                branch(17, f"_rise{index}", 4)
                branch(18, f"_done{index}")
                label(f"_rise{index}")
                ins(1, 4, k=1)
                ins(4, 4, k=slot)
                ins(52)
                event_name = f"{task['id']}:threshold:{index}"
                event = self.event(event_name, 4, event_name, owner)
                ins(64, value, 7, k=event)
                branch(18, f"_done{index}")
                label(f"_above{index}")
                ins(5, 5, k=param)
                ins(1, 4, k=hyst)
                ins(7, 5, 5, 4)
                ins(16, 4, value, 5, 3)  # value <= lower
                branch(17, f"_fall{index}", 4)
                branch(18, f"_done{index}")
                label(f"_fall{index}")
                ins(1, 4, k=0)
                ins(4, 4, k=slot)
                label(f"_done{index}")
                for action_index, action in enumerate(step["actions"]):
                    fields(action, ("op", "pin", "duration_ms", "retrigger"), ("op", "pin", "duration_ms"))
                    if action["op"] != "pulse" or action.get("retrigger", "ignore") != "ignore":
                        raise ValueError("Bu dilimde yalnız pulse/retrigger=ignore")
                    pin = action["pin"]
                    if pin not in resources:
                        raise ValueError("Pulse kaynağı görevde bildirilmemiş")
                    ms = uint(action["duration_ms"], "duration_ms", 1, 0x7FFFFFFF)
                    self.generated.append({"id": f"{task['id']}:pulse:{index}:{action_index}",
                        "resources": [pin], "trigger": {"kind": "threshold", "event_id": event_name},
                        "steps": [{"op": "gpio_write", "pin": pin, "value": 1},
                                  {"op": "delay_ms", "ms": ms},
                                  {"op": "gpio_write", "pin": pin, "value": 0}]})
            elif op == "delay_ms":
                fields(step, ("op", "ms"), ("ms",))
                ins(1, 4, k=uint(step["ms"], "ms", 1, 0x7FFFFFFF))
                ins(50, 4, k=0)
            elif op == "label":
                fields(step, ("op", "name"), ("name",))
                if step["name"].startswith("_"):
                    raise ValueError("Ayrılmış etiket")
                label(step["name"])
            elif op in OPS:
                fields(step, ("op", "a", "b", "c", "k", "target"), ("op",))
                a, b, c = (uint(step.get(f, 0), f, 0, 7) for f in ("a", "b", "c"))
                if op in ("jump", "br_true"):
                    branch(OPS[op], step["target"], a)
                else:
                    # Hardware operands must go through binding; raw h/manifest indices are unsafe input.
                    if OPS[op] in (*range(32, 38), 51, 64):
                        raise ValueError("Ham donanım/olay indeksi yerine sembolik adım kullanın")
                    ins(OPS[op], a, b, c, uint(step.get("k", 0)))
            else:
                raise ValueError(f"Bilinmeyen/desteklenmeyen op: {op}")
        if trigger["kind"] == "once":
            ins(127)
        else:
            ins(52)
            branch(18, "_entry")
        for pc, target in patches:
            if target not in labels:
                raise ValueError(f"Bilinmeyen etiket: {target}")
            code[pc][4] = start + labels[target]
        # Bound every acyclic path between cooperative boundaries; back edges retain target enforcement.
        self.check_code(code, start, len(local))
        if len(local) > self.config.get("vars", 16):
            raise ValueError("Değişken kapasitesi aşıldı")
        encoded = b"".join(struct.pack("<BBBBI", *instruction) for instruction in code)
        self.code.extend(encoded[i:i + 8] for i in range(0, len(encoded), 8))
        self.tasks.append([owner, uint(task.get("revision", 1)), start, len(code), var_start, len(local), mask,
                           zlib.crc32(encoded), zlib.crc32(pack_rows(self.variables[var_start:])),
                           zlib.crc32(pack_rows([r for i, r in enumerate(self.allow) if mask & (1 << i)])), 16, 0])

    def check_code(self, code, start, variables, costs=None):
        costs = costs or {OPS[name]: value for name, value in self.config.get("opcode_costs", {}).items()}
        for op, a, b, c, k in code:
            if ((op in (0, 52, 127) and (a or b or c or k))
                    or (op in (1, 3, 4, 5, 17, 48, 50) and (b or c))
                    or (op == 2 and (c or k))
                    or (op in (6, 7, 8, 9, 10) and k)
                    or (op == 11 and k > 4) or (op == 16 and k > 5)
                    or (op in (18, 49) and (a or b or c))):
                raise ValueError("Ayrılmış komut alanı")
            if (op in (3, 4) and k >= variables) or (op == 5 and k >= len(self.params)):
                raise ValueError("Slot indeksi geçersiz")
            if op in (48, 49, 50) and k >= self.config.get("timers", 2):
                raise ValueError("Timer indeksi geçersiz")
            if op in (9, 10) and self.config.get("div", True) is not True:
                raise ValueError("DIV özelliği kapalı")
        # Explore bounded paths; loops are accepted with the mandatory runtime budget guard.
        todo, seen = [(0, 0)], set()
        while todo:
            pc, used = todo.pop()
            if (pc, used) in seen or not 0 <= pc < len(code):
                continue
            seen.add((pc, used))
            op, a, b, c, k = code[pc]
            used += uint(costs.get(op, 1), "opcode_cost", 1, 16)
            if used > 16:
                raise ValueError("Görev dilimi 16: açık yield/wait gerekli")
            if op in (49, 50, 51, 52, 127):
                if op != 127:
                    todo.append((pc + 1, 0))
            elif op in (17, 18):
                target = k - start
                if target > pc:
                    todo.append((target, used))
                if op == 17:
                    todo.append((pc + 1, used))
            else:
                todo.append((pc + 1, used))


class Compiled:
    def __init__(self, image, source):
        self.image, self.source = image, copy.deepcopy(source)
        self.crc = zlib.crc32(image)
        self.sha = hashlib.sha256(image).hexdigest()

    def plan(self):
        return {"expected_generation": self.source["expected_generation"], "bytes": len(self.image),
                "crc32": self.crc, "sha256": self.sha, "tasks": [t["id"] for t in self.source["tasks"]],
                "effect": "RAM upload, doğrulama, safe kaynak geçişi, atomik commit",
                "migration": "Değişen kod girişten; uyumlu preserve değişkenleri; görüntünün açık parametreleri"}


class Program:
    def __init__(self, live):
        if not live.stub:
            raise ValueError("live.mailbox gerekli")
        self.live, self.target = live, live.target
        self.base = live.stub.base
        self.size = number(live.config["mailbox"]["size"])

    def read(self, offset, width, count):
        if offset < 0 or offset + count * width // 8 > self.size:
            raise ValueError("Mailbox alanı dışında")
        return self.target.read(self.base + offset, width, count)

    def write(self, offset, width, values):
        if offset < 0 or offset + len(values) * width // 8 > self.size:
            raise ValueError("Mailbox alanı dışında")
        self.target.write(self.base + offset, width, values)

    def snapshot(self):
        for _ in range(20):
            seq = self.read(180, 32, 1)[0]
            head = self.read(0, 32, 64)
            if seq == head[45] == self.read(180, 32, 1)[0] and seq % 2 == 0:
                if head[0:2] != [MAGIC, 2] or head[18] != 46:
                    raise ValueError("Yorumlayıcı mailbox v2 gerekli")
                regions = [(0, 256), (head[19], head[20]), (head[21], head[23]),
                           (head[22], head[23]), (head[24], head[25])]
                for i, (offset, length) in enumerate(regions):
                    if offset % 4 or not length or offset + length > self.size:
                        raise ValueError("V2 bölge boyutu geçersiz")
                    if any(offset < o + n and o < offset + length for o, n in regions[:i]):
                        raise ValueError("V2 bölgeleri çakışıyor")
                return head
        raise TimeoutError("Tutarlı state_seq snapshot alınamadı")

    def heartbeat(self):
        # A guarded read/write path works on either target; no mutation is retried.
        head = self.snapshot()
        self.write(12, 32, [(head[3] + 1) & U32])

    def require_alive(self):
        self.live.verify_build()
        first = self.snapshot()
        for _ in range(10):
            if self.snapshot()[2] != first[2]:
                return first
            time.sleep(0.01)
        raise ValueError("Stub heartbeat ilerlemiyor")

    def request(self, command, args, timeout=5):
        if len(args) > 8:
            raise ValueError("En fazla sekiz istek argümanı")
        args = [uint(arg) for arg in args]
        head = self.snapshot()
        if head[26] != head[36] or head[26] >= U32 - 1:
            raise ValueError("Bekleyen/biten oturum isteği; sonucu okuyun, tekrar denemeyin")
        seq = head[26] + 1
        self.write(112, 32, [*args, *([0] * (8 - len(args)))])
        self.write(108, 32, [COMMAND[command]])
        self.write(104, 32, [seq])
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            head = self.snapshot()
            if head[44] != self.boot:
                raise ValueError("İstek sırasında boot_id değişti; sonuç belirsiz")
            if head[36] == seq:
                if head[37]:
                    raise ValueError(ERRORS[head[38]] if head[38] < len(ERRORS) else f"error {head[38]}")
                return head
            self.heartbeat()
            time.sleep(0.001)
        raise TimeoutError("İstek zaman aşımı; sonuç belirsiz, tekrar denenmedi")

    def get(self):
        head = self.snapshot()
        result = {key: head[index] for key, index in WORD.items() if key != "args"}
        if head[40]:
            offset = head[21 + head[41]]
            prefix = bytes(self.read(offset, 8, 24))
            size = struct.unpack_from("<I", prefix, 8)[0]
            if size < 136 or size > head[23]:
                raise ValueError("Aktif görüntü boyutu geçersiz")
            image = bytes(self.read(offset, 8, size))
            if zlib.crc32(image) != head[43]:
                raise ValueError("Aktif görüntü CRC uyuşmuyor")
            _, sections = image_sections(image)
            result["image_hex"] = image.hex()
            result["tasks"] = [list(r) for r in struct.iter_unpack("<12I", sections[1])]
            names = {code: name for name, code in OPS.items()}
            result["instructions"] = [dict(pc=pc, op=names.get(op, f"unknown_{op}"), a=a, b=b, c=c, k=k)
                                      for pc, (op, a, b, c, k) in enumerate(struct.iter_unpack("<BBBBI", sections[2]))]
            result["params"] = [list(r) for r in struct.iter_unpack("<5I", sections[4])]
            values = self.read(head[19] + 64, 32, len(result["params"])) if result["params"] else []
            for item, value in zip(result["params"], values, strict=True):
                item[1] = value
            after = self.snapshot()
            if (after[40], after[43], after[44]) != (head[40], head[43], head[44]):
                raise ValueError("Program okuma sırasında değişti")
        return result

    def set(self, compiled):
        head = self.require_alive()
        self.boot = head[44]
        expected = compiled.source["expected_generation"]
        if expected != head[40]:
            raise ValueError("STALE_GENERATION")
        caps = self.read(head[19], 32, 64)
        if caps[0:3] != [1, 1, struct.unpack_from("<I", compiled.image, 16)[0]]:
            raise ValueError("Yetkinlik hash/sürüm uyuşmuyor")
        if len(compiled.image) > head[23]:
            raise ValueError("Hedef banka kapasitesi yetersiz")
        _, sections = image_sections(compiled.image)
        tasks = list(struct.iter_unpack("<12I", sections[1]))
        if len(tasks) > caps[4] or any(t[5] > caps[5] for t in tasks) or caps[7:10] != [64, 16, 1]:
            raise ValueError("Hedef görev/zamanlama kapasitesi uyumsuz")
        code = list(struct.iter_unpack("<BBBBI", sections[2]))
        if any((op in (35, 36) and not caps[3] & 1) or (op == 37 and not caps[3] & 2)
               or (op in (9, 10) and not caps[3] & 4) for op, *_ in code):
            raise ValueError("Hedef opcode özelliği kapalı")
        checker = Compiler(self.live)
        checker.params = list(struct.iter_unpack("<5I", sections[4]))
        for task in tasks:
            checker.check_code(code[task[2]:task[2] + task[3]], task[2], task[5],
                               {32 + i: value for i, value in enumerate(caps[26:32])})
        self.heartbeat()
        self.write(56, 32, [1, self.live.stub.timeout_ms])
        head = self.request("begin", [expected, len(compiled.image), compiled.crc, 1])
        upload = head[46]
        bank = head[22] if head[40] and head[41] == 0 else head[21]
        chunk_size = 128
        if hasattr(self.target, "max_payload"):
            chunk_size = min(chunk_size, (self.target.max_payload - 2 - len(self.target.guard) - 7) // 4 * 4)
        if chunk_size < 4:
            raise ValueError("Seri payload en az dört baytlık chunk taşımalı")
        for offset in range(0, len(compiled.image), chunk_size):
            chunk = compiled.image[offset:offset + chunk_size]
            self.write(bank + offset, 8, list(chunk))
            self.request("chunk", [upload, offset, len(chunk), zlib.crc32(chunk)])
            self.heartbeat()
        self.request("verify", [upload])
        deadline = time.monotonic() + 5
        while True:
            head = self.snapshot()
            if head[48] == 3:
                break
            if head[48] == 4:
                raise ValueError(ERRORS[head[38]])
            if time.monotonic() >= deadline:
                raise TimeoutError("VERIFY zaman aşımı; tekrar denenmedi")
            self.heartbeat()
            time.sleep(0.001)
        self.request("commit", [upload, expected])
        result = self.get()
        if result["generation"] != expected + 1 or result["active_crc"] != compiled.crc:
            raise ValueError("Commit geri okuması uyuşmuyor; tekrar denenmedi")
        return result

    def mutate(self, command, expected, item=None, value=None):
        head = self.require_alive()
        self.boot = head[44]
        args = [uint(expected, "expected_generation", 0, U32 - 1)]
        if item is not None:
            args += [ident(item), uint(value)]
        self.heartbeat()
        return {key: h for key, h in zip(("generation", "active_bank", "run_state", "active_crc"),
                                         self.request(command, args)[40:44], strict=True)}

    def events_read(self, limit=32, cursor=None, consume=False, execute=False, boot_id=None):
        uint(limit, "limit", 1, 256)
        if boot_id is not None:
            uint(boot_id, "boot_id", 1)
        if consume and not execute:
            return {"plan": {"cursor": cursor, "limit": limit, "consume": True}, "executed": False}
        head = self.snapshot()
        cache_path = self.live.profile.path.with_suffix(".events.local.json")
        cache = getattr(self.live, "_interp_ring_cache", None)
        if cache is None and cache_path.exists():
            cache = load_source(cache_path.read_text(encoding="utf-8"))
            if cache.get("uid_hex") != self.live.profile.expected.hex():
                raise ValueError("Olay cursor kaydı başka hedefe ait")
        if cursor is not None:
            known_boot = boot_id if boot_id is not None else (cache or {}).get("boot_id")
            if known_boot != head[44]:
                raise ValueError("Cursor boot_id bayat veya eksik; önce cursor olmadan okuyun")
        offset, size = head[24:26]
        ring = bytes(self.read(offset, 8, 32))
        version, record_bytes, capacity, write, read, dropped, unit, clock = struct.unpack("<8I", ring)
        if (version != 1 or record_bytes != 32 or capacity >= 2**31 or capacity & (capacity - 1)
                or size != 32 + capacity * 32 or ((write - read) & U32) > capacity):
            raise ValueError("Olay halkası biçimi geçersiz")
        observed_at = time.time()
        anchor = cache if (cache and cache.get("boot_id") == head[44] and cache.get("clock_id") == clock
                           and 0 <= observed_at - cache.get("observed_at", 0) < 0x7FFFFFFF / 1000) else None
        previous_raw = (anchor or {}).get("raw")
        extended = (anchor or {}).get("extended")
        cursor = read if cursor is None else uint(cursor)
        first_cursor = cursor
        available = (write - cursor) & U32
        if available > capacity or ((cursor - read) & U32) > ((write - read) & U32):
            raise ValueError("Bayat/geçersiz cursor")
        events = []
        for _ in range(min(available, limit)):
            slot = offset + 32 + (cursor & (capacity - 1)) * 32
            record = bytes(self.read(slot, 8, 32))
            seq, timestamp, generation, source, kind, flags, channel, value, aux, reserved = struct.unpack(
                "<IIIHBBIIII", record)
            if seq != cursor or bytes(self.read(slot, 8, 4)) != record[:4] or reserved or flags & ~7:
                raise ValueError("Halka kaydı değişti/geçersiz")
            if previous_raw is None:
                extended = timestamp
            else:
                delta = (timestamp - previous_raw) & U32
                extended += delta if delta < 2**31 else -((previous_raw - timestamp) & U32)
            previous_raw = timestamp
            events.append(dict(seq=seq, timestamp=timestamp, generation=generation, source=source,
                               kind=kind, flags=flags, channel=channel, value=value, aux=aux,
                               timestamp_extended=extended))
            cursor = (cursor + 1) & U32
        if self.snapshot()[44] != head[44]:
            raise ValueError("Halka okunurken boot_id değişti")
        write_after = int.from_bytes(bytes(self.read(offset + 12, 8, 4)), "little")
        if ((write_after - write) & U32) >= 2**31 or ((write_after - first_cursor) & U32) > capacity:
            raise ValueError("Halka penceresi okuma sırasında değişti")
        if consume:
            self.write(200, 32, [cursor])
            deadline = time.monotonic() + 2
            while True:
                ack, status = self.read(204, 32, 2)
                if ack == cursor:
                    if status:
                        raise ValueError("Halka cursor reddedildi")
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("Cursor ack zaman aşımı; tekrar denenmedi")
                time.sleep(0.001)
        cache = {"uid_hex": self.live.profile.expected.hex(), "boot_id": head[44], "clock_id": clock,
                 "cursor": cursor, "raw": previous_raw, "extended": extended, "observed_at": observed_at}
        self.live._interp_ring_cache = cache
        if consume:
            temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
            temporary.write_text(json.dumps(cache), encoding="utf-8")
            temporary.replace(cache_path)
        return {"events": events, "cursor": cursor, "boot_id": head[44], "dropped": dropped,
                "time_unit_ns": unit, "clock_id": clock, "consumed": consume,
                "max_read_interval_ms": 0x7FFFFFFF, "time_origin": "first_observation"}


def load_source(text):
    return json.loads(text, object_pairs_hook=unique)


def run_program(args, profile):
    from .core import open_target
    from .live import Live, read_project_file

    session = getattr(args, "_session", None)
    live = session.live if session else Live(profile, None)
    pins = session.pins if session else Pins(live, profile)
    action, execute = args.action, getattr(args, "execute", False)
    saved = pins.state.data.get("program")
    compiled, plan = None, None
    if action in ("set", "task-add", "task-remove"):
        if action == "set":
            source = load_source(args.json) if args.json else load_source(read_project_file(profile, args.file)[1])
        else:
            if not saved:
                raise ValueError("Görev düzenleme için doğrulanmış host kaynak kaydı gerekli; program set kullanın")
            source = copy.deepcopy(saved["source"])
            source["expected_generation"] = args.expected_generation
            if action == "task-add":
                task = load_source(args.json)
                index = next((i for i, t in enumerate(source["tasks"]) if t["id"] == task["id"]), len(source["tasks"]))
                if index == len(source["tasks"]):
                    source["tasks"].append(task)
                else:
                    source["tasks"][index] = task
            else:
                if not any(t["id"] == args.task_id for t in source["tasks"]):
                    raise ValueError("Görev kaynak kaydında yok")
                source["tasks"] = [t for t in source["tasks"] if t["id"] != args.task_id]
        if getattr(args, "expected_generation", None) is not None:
            source["expected_generation"] = args.expected_generation
        compiled = Compiler(live, pins).compile(source)
        plan = compiled.plan()
    elif action in ("stop", "param", "message"):
        plan = {"command": action, "expected_generation": uint(args.expected_generation),
                **({"id": args.item, "value": uint(args.value)} if action != "stop" else {})}
    elif action == "events" and args.consume and not execute:
        plan = {"command": "events", "limit": args.limit, "cursor": args.cursor, "consume": True}
    if plan is not None and not execute:
        return {"plan": plan, "executed": False}
    owned = session is None
    if owned:
        live.target = live.device.target = open_target(profile)
    try:
        program = Program(live)
        if compiled:
            if action != "set":
                head = program.snapshot()
                if (saved["boot_id"], saved["generation"], saved["active_crc"]) != (head[44], head[40], head[43]):
                    raise ValueError("Kaynak kaydı bayat; program get/set ile uzlaştırın")
            result = program.set(compiled)
            pins.state.data["program"] = {"source": compiled.source, "boot_id": result["boot_id"],
                                          "generation": result["generation"], "active_crc": result["active_crc"]}
            pins.state.save()
            return {"plan": plan, "executed": True, "program": result}
        if action == "get":
            return program.get()
        if action == "events":
            return program.events_read(args.limit, args.cursor, args.consume, execute, args.boot_id)
        before = program.snapshot()
        result = program.mutate(action, args.expected_generation,
                                None if action == "stop" else args.item,
                                None if action == "stop" else args.value)
        if action == "param" and saved:
            current = (before[44], before[40], before[43])
            if (saved["boot_id"], saved["generation"], saved["active_crc"]) != current:
                pins.state.data["program"] = None
                pins.state.save()
            elif (spec := saved["source"].get("params", {}).get(args.item)) is not None:
                spec["value"] = args.value
                saved["generation"] = result["generation"]
                saved["source"]["expected_generation"] = result["generation"]
                pins.state.save()
        return {"executed": True, "program": result}
    finally:
        if owned:
            live.target.close()
