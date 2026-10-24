"""Offline MCU recipe scaffold from explicitly confirmed register/field mappings."""
import json
from pathlib import Path

from .core import unique
from .live import compile_steps, expand_name
from .svd import Device, Field


def scaffold(svd_path, map_path, out):
    svd = Device.load(svd_path)
    mapping = json.loads(Path(map_path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique)
    if not isinstance(mapping.get("pins"), dict) or not mapping["pins"]:
        raise ValueError("Eşlemede boş olmayan pins nesnesi gerekli")
    data = {"schema_version": 1, "name": mapping.get("name", "SVD scaffold"), "pins": {}, "recipes": {}}

    def field_step(spec, op, value=None):
        register = svd.lookup(expand_name(spec["register"], {}))
        if not hasattr(register, "fields"):
            raise ValueError("Eşleme bir register adı içermeli")
        if op in ("read", "modify") and (register.side_effect or register.access == "write-only"):
            raise ValueError("Eşlenen register okunamaz (SVD okuma yan etkili veya yalnız-yazma)")
        name = expand_name(spec["field"], {})
        if "." in name:
            raise ValueError("Alan seçilen register içinde olmalı")
        field = svd.lookup(f"{register.name}.{name}")
        if not isinstance(field, Field) or field.register is not register:
            raise ValueError("Alan seçilen register içinde değil")
        step = {"op": op, "address": register.name, "width": register.size,
                "mask": f'field_mask("{name}")'}
        if op == "read":
            step.update(shift=field.offset, name="level")
        else:
            step["value"] = f'field_value("{name}", {value})'
        return step

    def integer(spec, key):
        value = spec[key]
        if type(value) is not int:
            raise ValueError(f"Eşlemede {key} tam sayı olmalı")
        return value

    for pin, spec in mapping["pins"].items():
        level = spec["level"]
        low, high = integer(level, "low"), integer(level, "high")
        output = field_step(level, "modify", f"{low} + level * ({high} - {low})")
        if "atomic" in spec:
            atomic = spec["atomic"]
            set_step = field_step(atomic["set"], "write", integer(atomic["set"], "value"))
            clear_step = field_step(atomic["clear"], "write", integer(atomic["clear"], "value"))
            if set_step["address"] != clear_step["address"]:
                raise ValueError("Atomik set/clear alanları aynı register içinde olmalı")
            output = {"op": "write", "address": set_step["address"], "width": set_step["width"],
                      "verify": False,
                      "value": f'level * ({set_step["value"]}) + (1 - level) * ({clear_step["value"]})'}
        directions = spec["direction"]
        if not isinstance(directions, list) or not directions:
            raise ValueError("direction boş olmayan register/alan listesi olmalı")
        recipes = {
            "gpio_out": {"inputs": {"level": {"default": 0, "min": 0, "max": 1}},
                         "steps": [output] + [field_step(d, "modify", integer(d, "output")) for d in directions]},
            "gpio_in": {"steps": [field_step(d, "modify", integer(d, "input")) for d in directions]},
            "gpio_read": {"steps": [field_step(spec["input"], "read")]},
        }
        functions = {}
        for function, recipe in recipes.items():
            # Check both output levels; overflow must fail before creating any file.
            for value in (0, 1):
                compile_steps(recipe, {"level": value}, svd)
            key = f"{pin}:{function}"
            data["recipes"][key] = recipe
            functions[function] = {"recipe": key}
        data["pins"][pin] = {"functions": functions}
    with Path(out).open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=True, indent=2, allow_nan=False)
        stream.write("\n")
    return {"mcu_db": str(Path(out).resolve()), "pins": list(data["pins"]),
            "status": "scaffold_requires_hardware_review"}
