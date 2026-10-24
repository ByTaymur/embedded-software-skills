"""Serial transport: talk to the stub's byte-stream link (UART, USB CDC, ...) instead of a debug probe.

Same methods as core.OpenOcdTarget, so every live command, `serve` and `mcp` work unchanged. Every
request carries the profile's expected identity bytes; the stub compares them before doing anything,
the serial counterpart of the UID guard in each OpenOCD Tcl request. A timed-out or garbled exchange
closes the link and is never retried. Frame format: ../../stub/eat_link.h, references/stub-protocol.md.
"""
import struct
import time

SYNC = b"\xea\x7e"
PROTOCOL = 1
COMMAND = {"info": 0x01, "read": 0x02, "write": 0x03, "modify": 0x04, "increment_if": 0x05}
STATUS = {0: "ok", 1: "bad_request", 2: "IDENTITY_MISMATCH", 3: "unknown_command", 4: "alignment"}


def crc16(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE, as eat_link_crc16()."""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def frame(payload):
    length = struct.pack("<H", len(payload))
    return SYNC + length + payload + struct.pack("<H", crc16(length + payload))


class SerialTarget:
    kind = "serial"

    def __init__(self, profile, stream=None):
        connection = profile.connection
        self.timeout = connection.get("timeout_s", 2)
        if stream is None:
            try:
                import serial  # optional dependency: pip install pyserial
            except ImportError as exc:
                raise ValueError("serial bağlantı için pyserial gerekli: pip install pyserial") from exc
            stream = serial.Serial(connection["port"], connection.get("baud", 115200), timeout=0.05)
        self.stream, self.seq, self.max_payload = stream, 0, 64
        self.guard = struct.pack("<IB", profile.uid_address, profile.uid_size) + profile.expected
        protocol, self.max_payload, self.mailbox_address, self.mailbox_words = struct.unpack(
            "<BHII", self.request(COMMAND["info"], b""))
        if protocol != PROTOCOL:
            self.close()
            raise ValueError(f"Stub seri protokol sürümü {protocol}, beklenen {PROTOCOL}")

    @property
    def closed(self):
        return self.stream is None

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def request(self, command, arguments):
        if self.stream is None:
            raise ConnectionError("Seri bağlantı önceki bir hatadan sonra kapatıldı; yeni bağlantı açın")
        self.seq = (self.seq + 1) & 0xFF
        payload = bytes([self.seq, command]) + self.guard + arguments
        if len(payload) > self.max_payload:
            raise ValueError("Seri istek stub'ın EAT_LINK_MAX_PAYLOAD sınırını aşıyor")
        try:
            self.stream.write(frame(payload))
            response = self.receive()
            if len(response) < 2 or response[0] != self.seq:
                raise ConnectionError("Seri yanıt sırası uyuşmuyor; yazma sonucu belirsiz")
        except BaseException:
            # A late answer would be taken for the next request's; drop the link instead.
            self.close()
            raise
        if response[1]:
            raise ValueError("Stub: " + STATUS.get(response[1], f"status {response[1]}"))
        return response[2:]

    def receive(self):
        deadline = time.monotonic() + self.timeout

        def exact(count):
            data = b""
            while len(data) < count:
                # Checked on every pass: a line that keeps sending noise must not hang the host.
                if time.monotonic() >= deadline:
                    raise TimeoutError("Seri yanıt zaman aşımı; yazma sonucu belirsiz, tekrar denenmedi")
                data += self.stream.read(count - len(data))
            return data

        window = b""
        while window != SYNC:
            window = (window + exact(1))[-2:]
        length = exact(2)
        payload = exact(struct.unpack("<H", length)[0])
        if struct.unpack("<H", exact(2))[0] != crc16(length + payload):
            raise ConnectionError("Seri yanıt CRC hatası; yazma sonucu belirsiz")
        return payload

    # -- target interface (same as core.OpenOcdTarget)
    @staticmethod
    def check(width):
        if width not in (8, 16, 32):
            raise ValueError("Seri bağlantı 8/16/32 bit erişim destekler")
        return width // 8

    def read(self, address, width, count):
        size, values = self.check(width), []
        per_request = (self.max_payload - 2) // size
        for start in range(0, count, per_request):
            part = min(per_request, count - start)
            data = self.request(COMMAND["read"], struct.pack("<IBH", address + start * size, width, part))
            if len(data) != part * size:
                raise ValueError("Eksik bellek okuması")
            values += [int.from_bytes(data[i:i + size], "little") for i in range(0, len(data), size)]
        return values

    def write(self, address, width, values):
        size = self.check(width)
        per_request = (self.max_payload - 2 - len(self.guard) - 7) // size
        for start in range(0, len(values), per_request):
            part = values[start:start + per_request]
            data = b"".join((v & ((1 << width) - 1)).to_bytes(size, "little") for v in part)
            self.request(COMMAND["write"], struct.pack("<IBH", address + start * size, width, len(part)) + data)

    def modify(self, address, width, mask, value):
        self.check(width)
        return struct.unpack("<I", self.request(COMMAND["modify"], struct.pack("<IBII", address, width, mask, value)))[0]

    def increment_if(self, check_address, expected, address):
        return self.request(COMMAND["increment_if"], struct.pack("<III", check_address, expected, address)) == b"\x01"
