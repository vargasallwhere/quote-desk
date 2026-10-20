"""Focused parser ported from the supplied Scout files; no catalog lookups."""
import re

_SIZE_INCH_RE = re.compile(r'(\d+)\s*[-\s]?inch(?:es)?', re.I)
_SIZE_QUOTE_RE = re.compile(r'(\d+)["“”‘’ʼʹ]')
_CHIP_PARSE_RE = re.compile(r'\b(M\d+\s*(?:Pro|Max|Ultra)?)\b', re.I)
_APPLE_RAM_GB = {8, 16, 18, 24, 32, 36, 48, 64, 96, 128}
_MEM_RE = re.compile(r'\b(\d+)\s*[-\s]?GB(?:\s*(?:RAM|memory|unified))?', re.I)
_STOR_TB_RE = re.compile(r'\b(\d+)\s*TB\b', re.I)
_STOR_GB_RE = re.compile(r'\b(256|512|1024|2048)\s*GB\b', re.I)
_CORES_RE = re.compile(r'\b(\d+)[\s\-‑]?core(?:\s+(?:cpu|processor))?\s+(\d+)[\s\-‑]?core\b', re.I)
_CORES_SLASH_RE = re.compile(r'\b(\d+)\s*[Cc]/(\d+)\s*[Cc]\b')
_COLORS_BY_LEN = sorted([
    "Space Black", "Space Gray", "Space Grey", "Silver", "Starlight",
    "Midnight", "Sky Blue", "Teal", "Blue", "Green", "Pink", "Orange",
    "Purple", "Yellow", "Gold", "Rose Gold",
], key=len, reverse=True)
_MODEL_PATTERNS = [
    (r'macbook\s*pro\s*16|16\s*macbook\s*pro|macbook\s*pro.*\b16\b|\b16\b.*macbook\s*pro', 'MacBook Pro 16'),
    (r'macbook\s*pro\s*14|14\s*macbook\s*pro|macbook\s*pro.*\b14\b|\b14\b.*macbook\s*pro', 'MacBook Pro 14'),
    (r'macbook\s*air\s*15|15\s*macbook\s*air|macbook\s*air.*\b15\b|\b15\b.*macbook\s*air', 'MacBook Air 15'),
    (r'macbook\s*air\s*13|13\s*macbook\s*air|macbook\s*air.*\b13\b|\b13\b.*macbook\s*air', 'MacBook Air 13'),
    (r'macbook\s*pro', 'MacBook Pro'), (r'macbook\s*air', 'MacBook Air'),
    (r'mac\s*mini', 'Mac mini'),
    (r'imac\s*24|24[\-\s]?inch\s*imac|\b24\b.*imac|imac.*\b24\b', 'iMac 24'),
    (r'imac', 'iMac'), (r'mac\s*pro', 'Mac Pro'), (r'ipad\s*pro', 'iPad Pro'),
    (r'ipad\s*air', 'iPad Air'), (r'ipad\s*mini', 'iPad mini'), (r'ipad', 'iPad'),
    (r'iphone', 'iPhone'), (r'macbook', 'MacBook'),
    (r'(?:laptop|notebook).*\b16\b(?!\s*(?:gb|tb))|\b16\b(?!\s*(?:gb|tb)).*(?:laptop|notebook)', 'MacBook Pro 16'),
    (r'(?:laptop|notebook).*\b14\b(?!\s*(?:gb|tb))|\b14\b(?!\s*(?:gb|tb)).*(?:laptop|notebook)', 'MacBook Pro 14'),
    (r'(?:laptop|notebook).*\b15\b(?!\s*(?:gb|tb))|\b15\b(?!\s*(?:gb|tb)).*(?:laptop|notebook)', 'MacBook Air 15'),
    (r'(?:laptop|notebook).*\b13\b(?!\s*(?:gb|tb))|\b13\b(?!\s*(?:gb|tb)).*(?:laptop|notebook)', 'MacBook Air 13'),
    (r'laptop|notebook', 'MacBook'),
]


def parse_device_text(text):
    tn = _SIZE_INCH_RE.sub(lambda m: m[1], text)
    tn = _SIZE_QUOTE_RE.sub(lambda m: m[1], tn).replace('"', '').replace("'", '')
    model = next((label for pattern, label in _MODEL_PATTERNS if re.search(pattern, tn.lower())), None)
    chip = None
    m = _CHIP_PARSE_RE.search(tn)
    if m:
        chip = re.sub(r'^[mM](\d+)', lambda x: f'M{x[1]}', m[1].strip())
        chip = re.sub(r'\s*(Pro|Max|Ultra)', lambda x: ' ' + x[1].capitalize(), chip, flags=re.I).strip()
    tb, gb = _STOR_TB_RE.search(tn), _STOR_GB_RE.search(tn)
    storage = f"{tb[1]} TB" if tb else (f"{gb[1]} GB" if gb else None)
    memory = next((f"{m[1]} GB" for m in _MEM_RE.finditer(tn) if int(m[1]) in _APPLE_RAM_GB), None)
    color = next((c for c in _COLORS_BY_LEN if c.lower() in tn.lower()), None)
    cores = _CORES_RE.search(tn) or _CORES_SLASH_RE.search(tn)
    return dict(model_query=model, chip=chip, memory=memory, storage=storage, color=color,
                cpu_cores=int(cores[1]) if cores else None, gpu_cores=int(cores[2]) if cores else None)


def parse_alt_description(text, country=""):
    parsed = parse_device_text(text)
    model, display = parsed["model_query"] or "", ""
    m = re.search(r'\b(13|14|15|16|24)\s*$', model)
    if m:
        model, display = model[:m.start()].strip(), f'{m[1]}"'
    if not display:
        m = re.search(r'\b(13|14|15|16|24)\s*(?:["”]|-?\s*inch)', text, re.I)
        if m:
            display = f'{m[1]}"'
    brands = [
        "Western Digital", "Blue Yeti", "Sennheiser", "Plantronics", "SteelSeries",
        "CalDigit", "Logitech", "Microsoft", "Samsung", "Lenovo", "Corsair",
        "HyperX", "Kingston", "Seagate", "Synology", "Ubiquiti", "Elgato",
        "Apple", "Sony", "Jabra", "Bose", "Razer", "Belkin", "Anker",
        "Dell", "Asus", "Acer", "Rode", "Poly", "LG", "HP",
    ]
    make = next((b for b in brands if re.search(r'\b' + re.escape(b) + r'\b', text, re.I)), "")
    if not make and any(k in model.lower() for k in ("macbook", "imac", "mac mini", "mac pro", "ipad", "iphone")):
        make = "Apple"
    mpn = re.search(r'\b([A-Z][A-Z0-9]{4,8}[A-Z]{2}/[A-Z])\b', text)
    price = re.search(r'\$\s*([\d,]+(?:\.\d{1,2})?)', text)
    cores = f'{parsed["cpu_cores"]}C/{parsed["gpu_cores"]}C' if parsed["cpu_cores"] and parsed["gpu_cores"] else ""
    region = country.upper() if country in ("us", "uk") else ""
    return dict(make=make, model=model, display_size=display,
                processor=" ".join(p for p in (parsed["chip"], cores) if p),
                memory=parsed["memory"] or "", storage=parsed["storage"] or "", color=parsed["color"] or "",
                mpn=mpn[1] if mpn else "", price=price[1].replace(",", "") if price else "",
                keyboard_language=region, sku_country=region)


def build_review(info, indices, text):
    items = info.get("items")
    if not isinstance(items, list) or not indices or not isinstance(indices, list):
        raise ValueError("Select at least one requested item.")
    selected, seen = [], set()
    for i in indices:
        if type(i) is not int or i < 0 or i >= len(items):
            raise ValueError("The item selection is invalid. Reload the order and select again.")
        item = items[i]
        if not isinstance(item, dict):
            raise ValueError("Order items could not be read. Reload the order.")
        sku = str(item.get("sku") or "").strip()
        if not sku:
            raise ValueError("A selected item has no SKU. Resolve it before opening a review.")
        if sku not in seen:
            selected.append(item)
            seen.add(sku)
    country = (info.get("shipping_country") or "").strip().lower()
    # Source popup groups Australia with UK; EU/other regions deliberately stay blank.
    country = "uk" if country in ("united kingdom", "uk", "gb", "great britain", "australia", "au") else (
        "us" if country in ("", "united states", "us", "usa") else "")
    parsed = parse_alt_description(text, country)
    primary = selected[0]
    name = (primary.get("product_name") or "").lower()
    device_type = "Laptop" if "macbook" in name or "laptop" in name else (
        "Tablet" if "ipad" in name or "tablet" in name else (
            "Mobile Phone" if "iphone" in name or "phone" in name else "Other"))
    brands = ("Western Digital", "Sennheiser", "Plantronics", "SteelSeries", "CalDigit",
              "Logitech", "Microsoft", "Samsung", "Lenovo", "Corsair", "HyperX",
              "Kingston", "Seagate", "Synology", "Ubiquiti", "Elgato", "MacBook",
              "Apple", "Sony", "Jabra", "Bose", "Razer", "Belkin", "Anker",
              "Dell", "Asus", "Acer", "Rode", "Poly", "LG", "HP")
    make = parsed["make"] or next((
        "Apple" if b == "MacBook" else b for b in brands
        if (f" {b.lower()} " if b in ("LG", "HP") else b.lower()) in name
    ), "")
    alt_type = "CTO device" if (parsed["mpn"] or primary.get("mpn") or "").upper().startswith("Z") else "Out of stock / backordered"
    return {**{k: info.get(k, "") for k in (
        "order_number", "org_name", "order_manager_name", "order_manager_email",
        "procurement_manager_email", "procurement_manager_name")},
        **parsed, "order_number": info.get("resolved_order_number") or info["order_number"],
        "make": make, "is_rush": bool(info.get("is_rush")),
        "requested_by": info.get("procurement_manager_email") or "",
        "requested_sku": str(primary["sku"]), "selected_skus": [str(i["sku"]) for i in selected],
        "multiple_skus": len(selected) > 1, "device_type": device_type,
        "alt_type": alt_type, "alt_subtype": "Model unavailable",
        "lead_time": "3-5 weeks" if alt_type == "CTO device" else ""}
