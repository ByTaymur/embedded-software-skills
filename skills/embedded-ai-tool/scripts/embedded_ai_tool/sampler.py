"""On-target SPSC sampler, shared by probe and serial memory transports."""
import math
import time
from itertools import pairwise

from .core import number, spans
from .live import check_width, overlaps

MAGIC = 0x504D5345
VERSION = 1
CHANNELS = 8
ALLOW_BASE, CHANNEL_BASE, DATA, ROW = 19, 35, 59, 10
MASK = 0xFFFFFFFF
WORD = dict(zip(("magic", "version", "slots", "max_channels", "count", "period", "write", "read",
                 "overrun", "time", "sequence", "enable", "state", "allow_count", "epoch", "error",
                 "start_time", "start_sequence", "start_overrun"), range(19), strict=True))


def memory_channel(text):
    """CLI syntax: address[:width_bits], default width 32. Port IDs are firmware-only."""
    parts = str(text).split(":")
    if len(parts) > 2:
        raise ValueError("Kanal adres[:8|16|32] olmalı")
    address, width = number(parts[0]), number(parts[1]) if len(parts) == 2 else 32
    check_width(address, width)
    if address < 0 or address + width // 8 > 2**32:
        raise ValueError("Kanal adresi 32 bit olmalı")
    return address, width


class Sampler:
    def __init__(self, live):
        self.live, self.target = live, live.target
        if "samples" not in live.config:
            raise ValueError("live.samples tanımlı değil")
        self.address, end = spans([live.config["samples"]])[0]
        self.size = end - self.address
        if self.address % 4 or self.address < 0 or self.address + self.size > 2**32 or self.size < DATA * 4:
            raise ValueError("Geçersiz live.samples alanı")
        self.header(coherent=False)  # validate before any write
        self.channels = []
        self.baseline = None

    def read(self, word, count):
        if word < 0 or count <= 0 or (word + count) * 4 > self.size:
            raise ValueError("Örnekleyici alanı dışında okuma")
        values = self.target.read(self.address + word * 4, 32, count)
        if len(values) != count:
            raise ValueError("Eksik örnekleyici cevabı")
        return values

    def write(self, word, values):
        # Never write producer words or ring data, even if a caller supplies a bad offset.
        allowed = {4, 5, 7, 11, 13} | set(range(ALLOW_BASE, DATA))
        if not values or any(i not in allowed for i in range(word, word + len(values))):
            raise ValueError("Örnekleyici yapılandırması dışında yazma")
        if (word + len(values)) * 4 > self.size:
            raise ValueError("Örnekleyici alanı dışında yazma")
        self.target.write(self.address + word * 4, 32, values)

    def header(self, coherent=True):
        for _ in range(32):
            epoch = self.read(WORD["epoch"], 1)[0] if coherent else 0
            raw = self.read(0, len(WORD))
            after = self.read(WORD["epoch"], 1)[0] if coherent else 0
            if not coherent or (epoch == raw[14] == after and not epoch & 1):
                h = {name: raw[index] for name, index in WORD.items()}
                slots = h["slots"]
                if (h["magic"] != MAGIC or h["version"] != VERSION or h["max_channels"] != CHANNELS or
                        not 1 <= slots <= 65536 or slots & (slots - 1) or
                        (DATA + slots * ROW) * 4 > self.size or
                        (h["write"] - h["read"]) & MASK > slots):
                    raise ValueError("Geçersiz örnekleyici başlığı")
                return h
        raise TimeoutError("Örnekleyici tutarlı başlığı okunamadı")

    def wait_state(self, wanted, timeout=2):
        until = time.monotonic() + timeout
        while True:
            state = self.read(WORD["state"], 1)[0]
            if state == wanted:
                return self.header(coherent=wanted == 0)
            if wanted == 1 and state == 2:
                raise ValueError("Hedef örnekleyici yapılandırmasını reddetti")
            if time.monotonic() >= until:
                raise TimeoutError("Örnekleyici tick/onay zaman aşımı")
            self.live.keepalive(throttle=True)
            time.sleep(0.001)

    def stop(self):
        self.write(WORD["enable"], [0])
        return self.wait_state(0)

    def configure(self, channels, period_ms):
        channels = [memory_channel(c) for c in channels]
        if not 1 <= len(channels) <= CHANNELS or type(period_ms) is not int or not 1 <= period_ms <= 0x7FFFFFFF:
            raise ValueError("1..8 kanal, period_ms 1..2147483647 gerekli")
        for address, width in channels:
            self.live.profile.check_read(address, width // 8)
            if overlaps(address, width // 8, self.live.policy.side_effect):
                raise ValueError("Yan etkili kanal okunamaz")
            if address < self.address + self.size and self.address < address + width // 8:
                raise ValueError("Örnekleyici alanı kanal olamaz")
        h = self.stop()  # config is immutable until producer acknowledges stop
        self.write(WORD["read"], [h["write"]])
        self.write(ALLOW_BASE, [v for a, w in channels for v in (a, w)])
        self.write(CHANNEL_BASE, [v for a, w in channels for v in (0, a, w)])
        self.write(WORD["count"], [len(channels), period_ms])
        self.write(WORD["allow_count"], [len(channels)])
        self.channels = channels

    def start(self):
        if not self.channels:
            raise ValueError("Önce configure gerekli")
        self.write(WORD["enable"], [1])
        h = self.wait_state(1)
        # These target-owned anchors stay immutable throughout the run. Reading them
        # works even when sampling is faster than a host header transaction.
        self.baseline = {"sequence": h["start_sequence"], "time": h["start_time"],
                         "overrun": h["start_overrun"]}
        return self.baseline

    def drain(self):
        h = self.header(coherent=False)  # only the atomic write index is needed here
        if h["count"] != len(self.channels):
            raise ValueError("Örnekleyici kanal sayısı değişti")
        read, write, slots = h["read"], h["write"], h["slots"]
        remaining = (write - read) & MASK
        rows = []
        while remaining:
            index = read & (slots - 1)
            take = min(remaining, slots - index)
            raw = self.read(DATA + index * ROW, take * ROW)
            for offset in range(0, len(raw), ROW):
                row = raw[offset:offset + ROW]
                rows.append({"sequence": row[0], "time_ms": row[1], "values": row[2:2 + len(self.channels)]})
            read = (read + take) & MASK
            remaining -= take
        if rows:
            self.write(WORD["read"], [read])  # release only after the entire bulk read succeeds
        return rows

    def measure(self, channels, period_ms, duration, thresholds=None):
        if not math.isfinite(duration) or not 0 < duration <= 86400:
            raise ValueError("duration 0..86400 saniye gerekli")
        thresholds = thresholds or []
        if len(thresholds) > len(channels) or any(not math.isfinite(t) for t in thresholds):
            raise ValueError("Her kanal için en fazla bir sonlu eşik gerekli")
        self.configure(channels, period_ms)
        rows = []
        try:
            start = self.start()
            until = time.monotonic() + duration
            while time.monotonic() < until:
                rows.extend(self.drain())
                self.live.keepalive(throttle=True)
                time.sleep(min(0.02, max(0, until - time.monotonic())))
        finally:
            end = self.stop()
        rows.extend(self.drain())
        return {"samples": rows, **stats(rows, start, end, len(self.channels), thresholds)}


def stats(rows, start, end, channel_count, thresholds=()):
    attempts = (end["sequence"] - start["sequence"]) & MASK
    elapsed = (end["time"] - start["time"]) & MASK
    overruns = (end["overrun"] - start["overrun"]) & MASK
    previous = start["sequence"]
    gaps = 0
    for row in rows:
        gaps += ((row["sequence"] - previous) & MASK) - 1
        previous = row["sequence"]
    # Tail drops do not appear as sequence gaps until a later record arrives.
    loss = max(overruns, gaps, attempts - len(rows))
    channels = []
    for i in range(channel_count):
        values = [row["values"][i] for row in rows]
        crossings = None
        if i < len(thresholds):
            threshold = thresholds[i]
            crossings = sum((b["sequence"] - a["sequence"]) & MASK == 1 and
                            (a["values"][i] >= threshold) != (b["values"][i] >= threshold)
                            for a, b in pairwise(rows))
        channels.append({"min": min(values) if values else None, "max": max(values) if values else None,
                         "mean": sum(values) / len(values) if values else None, "threshold_crossings": crossings})
    return {"count": len(rows), "attempts": attempts, "target_elapsed_ms": elapsed,
            "rate_hz": attempts * 1000 / elapsed if elapsed else None,
            "loss": loss, "loss_percent": loss * 100 / attempts if attempts else 0,
            "overruns": overruns, "sequence_gaps": gaps, "channels": channels}
