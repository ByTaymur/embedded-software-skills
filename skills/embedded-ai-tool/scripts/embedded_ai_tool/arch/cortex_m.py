"""Cortex-M SCB evidence; reads only, never halt or clear sticky status."""
from ..live import Live

# Armv7-M ARM DDI 0403E.b, B3.2 System control block (register summary,
# B3.2.15 CFSR); B1.5.8 exception return and stack frames.
# Armv8-M ARM DDI 0553B.y, B3.12 Faults (Main Extension).
# https://documentation-service.arm.com/static/5f8eff92f86e16515cdbe5e0
REGISTERS = {"CPUID": 0xE000ED00, "ICSR": 0xE000ED04, "SHCSR": 0xE000ED24,
             "CFSR": 0xE000ED28, "HFSR": 0xE000ED2C, "MMFAR": 0xE000ED34,
             "BFAR": 0xE000ED38, "AFSR": 0xE000ED3C}
FLAGS = {
    "CFSR": {0: "IACCVIOL", 1: "DACCVIOL", 3: "MUNSTKERR", 4: "MSTKERR", 5: "MLSPERR",
             7: "MMARVALID", 8: "IBUSERR", 9: "PRECISERR", 10: "IMPRECISERR", 11: "UNSTKERR",
             12: "STKERR", 13: "LSPERR", 15: "BFARVALID", 16: "UNDEFINSTR", 17: "INVSTATE",
             18: "INVPC", 19: "NOCP", 20: "STKOF", 24: "UNALIGNED", 25: "DIVBYZERO"},
    "HFSR": {1: "VECTTBL", 30: "FORCED", 31: "DEBUGEVT"},
    "SHCSR": {0: "MEMFAULTACT", 1: "BUSFAULTACT", 2: "HARDFAULTACT", 3: "USGFAULTACT",
              4: "SECUREFAULTACT", 5: "NMIACT", 7: "SVCALLACT", 8: "MONITORACT",
              10: "PENDSVACT", 11: "SYSTICKACT", 12: "USGFAULTPENDED", 13: "MEMFAULTPENDED",
              14: "BUSFAULTPENDED", 15: "SVCALLPENDED", 16: "MEMFAULTENA", 17: "BUSFAULTENA",
              18: "USGFAULTENA", 19: "SECUREFAULTENA", 20: "SECUREFAULTPENDED", 21: "HARDFAULTPENDED"},
    "ICSR": {11: "RETTOBASE", 22: "ISRPENDING", 23: "ISRPREEMPT", 25: "PENDSTCLR",
             26: "PENDSTSET", 27: "PENDSVCLR", 28: "PENDSVSET", 31: "NMIPENDSET"}}
SCB_HINT = 'read_ranges içine {"address": "0xE000ED00", "size": "0x100"} gerekli'


def exception_return(value):
    # Security-state transitions require banked stack registers; do not guess those.
    if value not in (0xFFFFFFF1, 0xFFFFFFF9, 0xFFFFFFFD, 0xFFFFFFE1, 0xFFFFFFE9, 0xFFFFFFED):
        return None
    return {"stack": "psp" if value & 4 else "msp", "extended": not bool(value & 16),
            "mode": "thread" if value & 8 else "handler"}


def frame_evidence(target, policy):
    if getattr(target, "kind", None) != "openocd":
        return {"available": False, "note": "Exception frame için OpenOCD ile halt edilmiş çekirdek gerekli"}
    registers = target.halted_registers(["sp", "lr", "pc", "xpsr", "msp", "psp"])
    if registers is None:
        return {"available": False, "note": "Exception frame için halt edilmiş çekirdek gerekli"}
    result = {"available": False, "registers": registers}
    decoded = exception_return(registers["lr"])
    if decoded is None or not registers["xpsr"] & 0x1FF:
        return {**result, "note": "Geçerli EXC_RETURN/exception bağlamı yok; frame yorumlanmadı"}
    # Integer state starts at SP in both layouts; FP state follows at SP+0x20.
    # Cortex-M4 Generic User Guide DDI0439B, 2.3.7, Figure 2-3.
    address = registers[decoded["stack"]]
    policy.check_read(address, 32)
    if address % 4:
        raise ValueError("Exception frame adresi hizasız")
    words = target.read_halted(address, 32, 8)
    return {**result, "available": True, "exc_return": decoded, "address": address,
            "words": words, "stacked_lr": words[5], "stacked_pc": words[6], "stacked_xpsr": words[7],
            "note": "Handler prologue SP'yi değiştirmiş olabilir; frame ardışık okuma kanıtıdır"}


def fault_evidence(target, profile):
    policy = Live(profile, target).policy
    try:
        profile.check_read(0xE000ED00, 0x100)
        for address in REGISTERS.values():
            policy.check_read(address, 4)
    except ValueError as exc:
        raise ValueError(f"SCB okuma reddedildi: {SCB_HINT}; {exc}") from exc
    registers = {name: target.read(address, 32, 1)[0] for name, address in REGISTERS.items()}
    flags = {name: [flag for bit, flag in bits.items() if registers[name] & (1 << bit)]
             for name, bits in FLAGS.items()}
    cpuid = registers["CPUID"]
    result = {"arch": "cortex-m", "supported": True, "registers": registers, "flags": flags,
              "fault_addresses": {name: {"valid": bool(registers["CFSR"] & (1 << bit)),
                                         "address": registers[name] if registers["CFSR"] & (1 << bit) else None}
                                  for name, bit in (("MMFAR", 7), ("BFAR", 15))},
              "cpuid": {"implementer": cpuid >> 24, "variant": (cpuid >> 20) & 15,
                        "architecture": (cpuid >> 16) & 15, "partno": (cpuid >> 4) & 0xFFF,
                        "revision": cpuid & 15},
              "icsr": {"vectactive": registers["ICSR"] & 0x1FF,
                       "vectpending": (registers["ICSR"] >> 12) & 0x1FF},
              "afsr_note": "AFSR bit anlamları uygulamaya özeldir; ham değer raporlandı", "atomic": False}
    try:
        result["frame"] = frame_evidence(target, policy)
    except (ValueError, OSError) as exc:
        result["frame"] = {"available": False, "error": str(exc)}
    return result
