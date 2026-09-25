"""Derive Device Classification profile fields from extraction / normalized specs."""

from __future__ import annotations

import re
from typing import Any

from core.schemas import ExtractionResult

_BRANDS = (
    "Samsung", "Apple", "Google", "Xiaomi", "OnePlus", "OPPO", "Vivo", "realme",
    "Motorola", "Nokia", "Sony", "Huawei", "Honor", "Nothing", "ASUS", "Lenovo",
    "HP", "Dell", "Microsoft", "LG", "Tecno", "Infinix", "POCO",
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _with_unit(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    if re.search(r"\b(gb|tb|mb|ghz|mhz)\b", v, re.I):
        return v
    if re.fullmatch(r"\d+(\.\d+)?", v):
        return f"{v} GB"
    return v


def _brand_from_text(text: str) -> str:
    t = text or ""
    for brand in _BRANDS:
        if re.search(rf"\b{re.escape(brand)}\b", t, re.I):
            return "realme" if brand.lower() == "realme" else brand
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)", t.strip())
    return m.group(1) if m else ""


def _iter_spec_rows(
    result: ExtractionResult | None,
    *,
    ui_features: list[dict[str, Any]] | None = None,
    normalized: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def push(name: str, value: Any) -> None:
        n = str(name or "").strip()
        v = "" if value is None else str(value).strip()
        if not n or not v:
            return
        key = (_norm(n), _norm(v))
        if key in seen:
            return
        seen.add(key)
        rows.append((n, v))

    if ui_features:
        for f in ui_features:
            for p in f.get("parameters") or []:
                push(p.get("name"), p.get("value"))

    if result is not None:
        for feat in result.features or []:
            for s in feat.specifications or []:
                raw = "" if s.value is None else str(s.value)
                val = f"{raw} {s.unit}".strip() if s.unit else raw
                push(s.parameter, val)

    if normalized:
        for mod in normalized.get("modules") or []:
            if not isinstance(mod, dict):
                continue
            for sp in mod.get("specs") or []:
                if isinstance(sp, dict):
                    push(sp.get("key"), sp.get("value"))

    return rows


def _pick(rows: list[tuple[str, str]], score_fn) -> tuple[str, str] | None:
    best = None
    best_score = 0
    for name, value in rows:
        score = score_fn(_norm(name), name, value)
        if score > best_score:
            best_score = score
            best = (name, value)
    return best if best_score > 0 else None


def derive_device_classification(
    result: ExtractionResult | None,
    *,
    device_type: str | None = None,
    product_name: str | None = None,
    document_name: str | None = None,
    ui_features: list[dict[str, Any]] | None = None,
    normalized: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Map extracted specs → Device Classification Parameter/Value fields."""
    rows = _iter_spec_rows(result, ui_features=ui_features, normalized=normalized)
    product = (product_name or (result.document.product_name if result else None) or "").strip()
    if not product and normalized:
        product = str(normalized.get("product_name") or "").strip()

    os_row = _pick(
        rows,
        lambda n, _name, value: (
            100 if n in {"os", "operating system"} else
            95 if "os version" in n or "android version" in n else
            90 if n in {"one ui", "one ui version", "hyperos", "ios version"} else
            80 if "operating system" in n else
            70 if re.search(r"\bos\b", n) and "bluetooth" not in n else
            60 if re.search(r"\b(android|ios|harmonyos|hyperos)\b", n) else
            50 if re.search(r"\b(android|ios|harmonyos|hyperos|one ui)\b", value, re.I)
                and len(value) < 80 else
            0
        ),
    )

    mfr_row = _pick(
        rows,
        lambda n, _name, _value: (
            100 if "manufactured by" in n or n == "manufacturer" else
            80 if n == "brand" else
            0
        ),
    )

    model_row = _pick(
        rows,
        lambda n, _name, _value: (
            100 if n in {"model", "model name", "product name", "device name"} else
            85 if "model name" in n or "model number" in n else
            60 if "model" in n and "form factor" not in n else
            0
        ),
    )

    # Samsung uses "Storage Memory (GB)" for RAM
    ram_row = _pick(
        rows,
        lambda n, _name, _value: (
            100 if "storage memory" in n else
            95 if re.search(r"\bram\b", n) and "program" not in n else
            85 if n in {"memory", "system memory", "user available memory"} else
            70 if n.endswith(" memory") and "storage" not in n else
            0
        ),
    )

    storage_row = _pick(
        rows,
        lambda n, _name, _value: (
            0 if "storage memory" in n or "available storage" in n
                or "expandable" in n or "microsd" in n or "micro sd" in n else
            100 if n in {"storage", "storage gb", "internal storage", "rom"} else
            90 if re.search(r"\bstorage\b", n) and "memory" not in n else
            70 if re.search(r"\brom\b", n) else
            0
        ),
    )

    chipset_row = _pick(
        rows,
        lambda n, _name, value: (
            100 if "chipset" in n or n == "soc" or "processor name" in n else
            95 if re.search(r"snapdragon|dimensity|exynos|tensor|mediatek|helio|apple a\d", value, re.I) else
            80 if "processor" in n and ("type" in n or "name" in n or "model" in n) else
            70 if n in {"cpu", "cpu type", "processor cpu type", "processor"} else
            0
        ),
    )
    cpu_speed_row = _pick(
        rows,
        lambda n, _name, _value: (
            90 if "cpu speed" in n or "processor cpu speed" in n or "clock" in n else
            0
        ),
    )

    cpu = ""
    if chipset_row:
        cpu = chipset_row[1]
        if cpu_speed_row and not re.search(r"ghz|mhz", cpu, re.I):
            cpu = f"{cpu} ({cpu_speed_row[1]})"
    elif cpu_speed_row:
        cpu = cpu_speed_row[1]

    manufacturer = ""
    if mfr_row:
        manufacturer = _brand_from_text(mfr_row[1]) or mfr_row[1].split(",")[0].strip()
    if not manufacturer and product:
        manufacturer = _brand_from_text(product)

    model = product
    if model_row:
        model = model_row[1]
    if not model and document_name:
        model = re.sub(r"\.pdf$", "", document_name, flags=re.I)
        model = re.sub(r"[_-]+", " ", model).strip()

    # Avoid "Samsung" + "Samsung Galaxy S25" duplication in consumers
    if manufacturer and model and model.lower().startswith(manufacturer.lower() + " "):
        pass  # model already includes brand — fine for Model field
    if manufacturer and model == manufacturer:
        model = product or model

    category = (device_type or "").strip().lower()
    if not category:
        category = "mobile"

    return {
        "category": category if category in {"mobile", "laptop", "tablet", "wearable"} else "mobile",
        "os": os_row[1] if os_row else "",
        "manufacturer": manufacturer,
        "model": model,
        "storage": _with_unit(storage_row[1]) if storage_row else "",
        "cpu": cpu,
        "ram": _with_unit(ram_row[1]) if ram_row else "",
    }
