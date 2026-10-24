"""Offline CMSIS-SVD names and decoding. Device descriptions never grant access."""
import copy
import difflib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

DEFAULTS = ("size", "access", "resetValue", "resetMask")
SIDE_EFFECTS = {"clear", "set", "modify", "modifyExternal"}
MAX_BYTES = 64 * 1024 * 1024


def text(node, key, default=None):
    value = node.findtext(key)
    return value.strip() if value is not None else default


def number(value):
    value = value.strip().lower()
    try:
        return int(value[1:], 2) if value.startswith("#") else int(value, 16 if value.startswith("0x") else
                                                                  2 if value.startswith("0b") else 10)
    except ValueError as exc:
        raise ValueError(f"Geçersiz SVD sayısı: {value}") from exc


def merge(base, own):
    result = copy.deepcopy(base)
    result.attrib.update(own.attrib)
    result.attrib.pop("derivedFrom", None)
    for child in own:
        name = text(child, "name")
        previous = next((c for c in result if c.tag == child.tag and text(c, "name") == name), None)
        replacement = merge(previous, child) if previous is not None and child.tag in {
            "registers", "fields"} else copy.deepcopy(child)
        if previous is not None:
            result.remove(previous)
        result.append(replacement)
    return result


class Resolver:
    def __init__(self, root):
        self.index, self.paths, self.cache, self.active = {}, {}, {}, set()
        self.index_tree(root, ())

    def index_tree(self, node, path):
        name = text(node, "name")
        if node.tag in {"peripheral", "register", "cluster", "field", "enumeratedValues"} and name:
            path = (*path, name)
            self.index[path] = node
        self.paths[node] = path
        for child in node:
            self.index_tree(child, path)

    def resolve(self, node):
        if node in self.cache:
            return self.cache[node]
        if node in self.active:
            raise ValueError(f"SVD derivedFrom döngüsü: {'.'.join(self.paths[node])}")
        self.active.add(node)
        result = copy.deepcopy(node)
        reference = node.get("derivedFrom")
        if reference:
            parts = tuple(reference.split("."))
            path = self.paths[node][:-1]
            candidates = [(*path[:i], *parts) for i in range(len(path), -1, -1)]
            base = next((self.index[p] for p in candidates if p in self.index), None)
            if base is None:
                base = next((found for p in candidates if (found := self.inherited(p)) is not None), None)
            if base is None or base.tag != node.tag:
                raise ValueError(f"SVD derivedFrom bulunamadı: {reference}")
            result = merge(self.resolve(base), node)
        # Resolve original children before copying, preserving their reference scope.
        for child in node:
            if child.tag in {"registers", "fields", "cluster", "register", "field", "enumeratedValues"}:
                resolved = self.resolve(child)
                previous = next((c for c in result if c.tag == child.tag and
                                 text(c, "name") == text(child, "name")), None)
                if previous is not None:
                    result.remove(previous)
                    if child.tag in {"registers", "fields"}:
                        resolved = merge(previous, resolved)
                result.append(resolved)
        self.active.remove(node)
        self.cache[node] = result
        return result

    def inherited(self, path):
        for length in range(len(path) - 1, 0, -1):
            parent = self.index.get(path[:length])
            if parent is None or not parent.get("derivedFrom"):
                continue
            parts = tuple(parent.get("derivedFrom").split("."))
            scope = path[:length - 1]
            candidates = [(*scope[:i], *parts) for i in range(len(scope), -1, -1)]
            base = next((self.index[p] for p in candidates if p in self.index), None)
            if base is None:
                continue
            node = self.resolve(base)
            for name in path[length:]:
                children = list(node)
                for container in ("registers", "fields"):
                    wrapper = node.find(container)
                    if wrapper is not None:
                        children.extend(wrapper)
                node = next((c for c in children if text(c, "name") == name), None)
                if node is None:
                    break
            if node is not None:
                # Already resolved nodes need no second reference-scope traversal.
                self.cache[node] = node
                return node
        return None


def instances(node):
    name = text(node, "name", "")
    dim = text(node, "dim")
    if dim is None:
        return [(name, name, 0)]
    count = number(dim)
    if not 1 <= count <= 100000:
        raise ValueError("SVD dim 1..100000 olmalı")
    indices = text(node, "dimIndex")
    if indices is None:
        indices = [str(i) for i in range(count)]
    elif "," in indices:
        indices = [i.strip() for i in indices.split(",")]
    elif match := re.fullmatch(r"(\d+)-(\d+)|([A-Za-z])-([A-Za-z])", indices):
        a, b, c, d = match.groups()
        indices = [str(i) for i in range(int(a), int(b) + 1)] if a else [
            chr(i) for i in range(ord(c), ord(d) + 1)]
    else:
        indices = [indices]
    if len(indices) != count:
        raise ValueError("SVD dimIndex ile dim uyuşmuyor")
    increment = number(text(node, "dimIncrement", "0"))
    return [(name.replace("[%s]", i).replace("%s", i), name.replace("%s", i), n * increment)
            for n, i in enumerate(indices)]


@dataclass
class Field:
    name: str
    offset: int
    width: int
    register: "Register"
    enums: dict = field(default_factory=dict)
    default_enum: str | None = None
    read_action: str | None = None


@dataclass
class Register:
    name: str
    address: int
    size: int
    access: str | None
    reset_value: int | None
    reset_mask: int | None
    read_action: str | None
    fields: list = field(default_factory=list)

    @property
    def side_effect(self):
        return self.read_action in SIDE_EFFECTS or any(f.read_action in SIDE_EFFECTS for f in self.fields)


class Device:
    def __init__(self, root):
        self.endian = text(root, "cpu/endian")
        self._peripherals, self._names = {}, {}
        resolver = Resolver(root)
        defaults = self.defaults(root, {})
        for peripheral in root.findall("peripherals/peripheral"):
            node = resolver.resolve(peripheral)
            name = text(node, "name")
            self._peripherals[name] = []
            registers = node.find("registers")
            if registers is not None:
                self.walk(registers, (name,), (name,), number(text(node, "baseAddress")),
                          self.defaults(node, defaults), name)

    @classmethod
    def load(cls, path):
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("SVD dosyası 64 MB sınırını aşıyor")
        # NUL removal also detects declarations in UTF-16/32 before XML parsing.
        if re.search(br"<!\s*(DOCTYPE|ENTITY)\b", raw.replace(b"\x00", b""), re.I):
            raise ValueError("SVD DOCTYPE/ENTITY içeremez")
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ValueError(f"SVD XML çözümlenemedi: {exc}") from exc
        for node in root.iter():
            node.tag = node.tag.rsplit("}", 1)[-1]
        return cls(root)

    @staticmethod
    def defaults(node, inherited):
        return {key: text(node, key, inherited.get(key)) for key in DEFAULTS}

    def add_name(self, path, obj):
        key = ".".join(path).casefold()
        if key in self._names and self._names[key] is not obj:
            raise ValueError(f"SVD adı tekil değil: {key}")
        self._names[key] = obj

    def walk(self, parent, path, alias, address, defaults, peripheral):
        for node in parent:
            if node.tag not in {"register", "cluster"}:
                continue
            props = self.defaults(node, defaults)
            for name, alternate, increment in instances(node):
                full, other = (*path, name), (*alias, alternate)
                location = address + number(text(node, "addressOffset", "0")) + increment
                if node.tag == "cluster":
                    self.walk(node, full, other, location, props, peripheral)
                    continue
                if props["size"] is None:
                    raise ValueError(f"SVD register genişliği eksik: {'.'.join(full)}")
                reg = Register(".".join(full), location, number(props["size"]), props["access"],
                               number(props["resetValue"]) if props["resetValue"] else None,
                               number(props["resetMask"]) if props["resetMask"] else None, text(node, "readAction"))
                self._peripherals[peripheral].append(reg)
                self.add_name(full, reg)
                self.add_name(other, reg)
                for fnode in node.findall("fields/field"):
                    offset, width = self.position(fnode)
                    for fname, falias, shift in instances(fnode):
                        f = Field(fname, offset + shift, width, reg, read_action=text(fnode, "readAction"))
                        if f.offset < 0 or f.width <= 0 or f.offset + f.width > reg.size:
                            raise ValueError(f"SVD bit alanı register dışında: {reg.name}.{fname}")
                        for enums in fnode.findall("enumeratedValues"):
                            if text(enums, "usage", "read-write") == "write":
                                continue
                            for enum in enums.findall("enumeratedValue"):
                                ename, value = text(enum, "name"), text(enum, "value")
                                if text(enum, "isDefault") in {"true", "1"}:
                                    f.default_enum = ename
                                elif value and "x" not in value.lower().removeprefix("0x"):
                                    f.enums[number(value)] = ename
                        reg.fields.append(f)
                        self.add_name((*full, fname), f)
                        self.add_name((*other, falias), f)

    @staticmethod
    def position(node):
        if text(node, "bitOffset") is not None:
            return number(text(node, "bitOffset")), number(text(node, "bitWidth"))
        if text(node, "lsb") is not None:
            low, high = number(text(node, "lsb")), number(text(node, "msb"))
        else:
            match = re.fullmatch(r"\[(\d+):(\d+)\]", text(node, "bitRange", ""))
            if not match:
                raise ValueError("SVD bit konumu eksik veya geçersiz")
            high, low = map(int, match.groups())
        return low, high - low + 1

    def lookup(self, name):
        key = re.sub(r"\[([^\[\]]+)\]", r"\1", name).casefold()
        if key not in self._names:
            close = difflib.get_close_matches(key, self._names, n=5)
            raise ValueError(f"SVD adı bulunamadı: {name}; yakın adlar: {', '.join(close)}")
        return self._names[key]

    def peripherals(self):
        return list(self._peripherals)

    def registers(self, peripheral):
        name = next((p for p in self._peripherals if p.casefold() == peripheral.casefold()), None)
        if name is None:
            close = difflib.get_close_matches(peripheral.upper(), self._peripherals)
            raise ValueError(f"SVD çevre birimi bulunamadı: {peripheral}; yakın adlar: {', '.join(close)}")
        return list(self._peripherals[name])

    @staticmethod
    def decode(register, value):
        return decode(register, value)


def decode(register, value):
    result = []
    for f in register.fields:
        raw = (value >> f.offset) & ((1 << f.width) - 1)
        result.append({"name": f.name, "bit_range": [f.offset + f.width - 1, f.offset],
                       "raw_value": raw, "enum_name": f.enums.get(raw, f.default_enum)})
    return result
