"""Explicit architecture dispatch; no target architecture inference."""


def supported(profile):
    return profile.data.get("live", {}).get("arch") == "cortex-m"


def fault_evidence(target, profile):
    arch = profile.data.get("live", {}).get("arch")
    if not supported(profile):
        return {"arch": arch, "supported": False, "note": "Fault kanıtı: mimari desteklenmiyor; live.arch gerekli"}
    from .cortex_m import fault_evidence as collect

    return collect(target, profile)
