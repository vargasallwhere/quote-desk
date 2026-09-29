"""Order lookup and email builders ported from Scout Dev (scout_engine.py, order_confirm_engine.py).
Logins come from environment variables (Replit Secrets), never from this file."""
import os, re, time, base64, logging, datetime
from email.mime.text import MIMEText
import requests

ALLWHERE_AUTH = (os.environ.get("ALLWHERE_USER", ""), os.environ.get("ALLWHERE_PASS", ""))


def cache_get(*_):  # Scout's disk cache is not used here
    return None


def cache_set(*_):
    pass


PS_AUTH = {"Authorization": "Basic " + base64.b64encode(
    f'{os.environ.get("PS_USER", "")}:{os.environ.get("PS_PASS", "")}'.encode()).decode()}

ALLWHERE_BASE = "https://service.production.allwhere.co/v1"

PS_BASE    = "https://product.allwhere.co/v1"

EU_COUNTRIES = {
    "austria", "belgium", "bulgaria", "croatia", "cyprus",
    "czech republic", "czechia", "denmark", "estonia", "finland",
    "france", "germany", "greece", "hungary", "ireland", "italy",
    "latvia", "lithuania", "luxembourg", "malta", "netherlands",
    "poland", "portugal", "romania", "slovakia", "slovenia",
    "spain", "sweden",
    "at", "be", "bg", "hr", "cy", "cz", "dk", "ee", "fi", "fr",
    "de", "gr", "hu", "ie", "it", "lv", "lt", "lu", "mt", "nl",
    "pl", "pt", "ro", "sk", "si", "es", "se",
}

UK_COUNTRIES = {"united kingdom", "gb", "uk", "great britain"}

ALLWHERE_BASE_V2 = "https://service.production.allwhere.co/v2"

def _extract_allwhere_mpn(description_html: str) -> str:
    """Pull the first <li> text from an Allwhere product description.
    Allwhere stores the MPN as the first bullet of the product description HTML.
    Returns empty string if not found or if the text looks like a sentence (not an MPN).
    """
    if not description_html:
        return ""
    m = re.search(r"<li[^>]*>(.*?)</li>", description_html, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
    # MPN should be a short code with no spaces and ≤30 chars (not a sentence)
    if len(text) <= 30 and " " not in text and text:
        return text
    return ""

def _ps_variant(variant_id: str) -> dict:
    """
    Look up a variant in the product-service API (new catalog, v3.0+).
    Returns dict with sku, mpn, title, price, is_build_to_order, or {} on failure.
    Cached by variant_id.
    """
    cached = cache_get("ps_variants", variant_id)
    if cached is not None:
        return cached
    try:
        r = requests.get(f"{PS_BASE}/product-variants/{variant_id}",
                         headers=PS_AUTH, timeout=15)
        if r.status_code == 200:
            v = r.json()
            result = {
                "sku":               str(v.get("sku", "")),
                "mpn":               v.get("mpn"),   # None = catalog explicitly has no MPN
                "product_name":      v.get("title") or "",
                "price_charged":     float(v.get("price") or 0),
                "is_build_to_order": bool(v.get("is_build_to_order")),
                "attributes":        v.get("attributes") or {},
                "found":             True,
            }
            cache_set("ps_variants", variant_id, result)
            return result
    except Exception:
        pass
    cache_set("ps_variants", variant_id, {})
    return {}

def clean_po(po: str) -> str:
    """Strip trailing ' (2)', ' (3)' etc. and word suffixes like '-GOOD', '-IRON'."""
    po = re.sub(r"\s*\(\d+\)\s*$", "", po.strip())
    po = re.sub(r"-[A-Z]+$", "", po)
    return po

def _parse_item_seq(order_item_number: str) -> int:
    """'122900-1-3-HIGH' → 3  (line-item sequence number, second-to-last segment)"""
    parts = order_item_number.split("-")
    try:
        return int(parts[-2])
    except (IndexError, ValueError):
        return 0

def get_order_header(order_number: str) -> dict:
    """
    Fetch order-level data via v2 in one call (embeds all orderItems + notes).
    Returns: {order_id, order_number, color_swap_approved, lead_time_approved,
              checkout_notes, internal_notes, raw_items: [{productVariantId, quantity}]}
    On error returns {"error": "..."}.
    """
    po_clean = clean_po(order_number)
    try:
        r = requests.get(
            f"{ALLWHERE_BASE_V2}/order",
            auth=ALLWHERE_AUTH,
            params={"orderNumber": po_clean},
            timeout=15,
        )
    except requests.RequestException as e:
        return {"error": f"Allwhere order lookup failed: {e}"}

    if r.status_code != 200 or not r.json().get("items"):
        return {"error": f"No Allwhere order found for: {po_clean}"}

    order = r.json()["items"][0]

    order_type = order.get("orderType") or {}
    is_depot   = bool(order_type.get("toDepot"))
    depot      = order.get("depot") or {}
    depot_name = (depot.get("name") or "").strip()

    rec_addr         = (order.get("recipient") or {}).get("address") or {}
    shipping_country = (rec_addr.get("country") or "").strip()
    if not shipping_country:
        shipping_country = (order.get("serviceCountry") or "").strip()
    if not shipping_country:
        fd = (order.get("finalDestination") or "").lower()
        if " uk" in fd or "united kingdom" in fd:
            shipping_country = "United Kingdom"
        elif "ireland" in fd:
            shipping_country = "Ireland"
        elif "australia" in fd:
            shipping_country = "Australia"

    raw_items = []
    for oi in order.get("orderItems", []):
        pv_id = oi.get("productVariantId")
        # For depot orders, productVariantId may live on the embedded asset object
        if not pv_id and oi.get("asset"):
            pv_id = (oi["asset"] or {}).get("productVariantId")
        if not pv_id:
            continue
        raw_items.append({
            "productVariantId":  pv_id,
            "quantity":          int(oi.get("quantity") or 1),
            "order_item_number": oi.get("orderItemNumber", ""),
            "asset_id":          oi.get("assetId"),
            "snapshot":          oi.get("productVariantSnapshot"),
            "protection_plan":   (oi.get("protectionPlan") or "").strip(),
        })
    raw_items.sort(key=lambda x: _parse_item_seq(x["order_item_number"]))

    om      = order.get("orderManager") or {}
    pm      = order.get("procurementManager") or {}
    ship    = order.get("shippingType") or {}
    org     = order.get("organization") or {}
    ship_name = (ship.get("name") or ship.get("shippingTypeName") or "").strip()
    is_rush = bool(
        re.search(r"overnight|next.?day|2.?day|two.?day", ship_name, re.IGNORECASE)
        or order.get("rush", False)
    )

    enterprise_warranty = False
    enterprise_warranty_notes = ""
    org_id = (org.get("id") or "").strip()
    if org_id:
        try:
            org_r = requests.get(
                f"{ALLWHERE_BASE}/organizations/{org_id}",
                auth=ALLWHERE_AUTH,
                timeout=15,
            )
            if org_r.status_code == 200:
                org_notes = (org_r.json().get("internalNotes") or "").strip()
                if org_notes and any(kw in org_notes.lower() for kw in ("ace", "enterprise", "warranty", "applecare")):
                    enterprise_warranty = True
                    enterprise_warranty_notes = org_notes.split("-----")[0].strip()
        except requests.RequestException:
            pass

    if not raw_items:
        return {
            "error": f"No order items found for: {po_clean}",
            "enterprise_warranty": enterprise_warranty,
            "enterprise_warranty_notes": enterprise_warranty_notes,
        }

    return {
        "order_number":        order_number,
        "order_id":            order.get("id", ""),
        "color_swap_approved": bool(order.get("deviceColorSwapApproved", False)),
        "lead_time_approved":  bool(order.get("flexibleLeadTimeApproved", False)),
        "checkout_notes":      (order.get("checkoutNotes") or "").strip(),
        "internal_notes":      (order.get("internalNotes") or "").strip(),
        "raw_items":           raw_items,
        "order_manager_email": (om.get("email") or "").strip().lower(),
        "order_manager_name":  (f"{om.get('firstName', '')} {om.get('lastName', '')}".strip()
                                or om.get("name") or om.get("fullName") or ""),
        "procurement_manager_email": (pm.get("email") or "").strip().lower(),
        "procurement_manager_name":  f"{(pm.get('firstName') or '')} {(pm.get('lastName') or '')}".strip(),
        "org_name":            (org.get("name") or "").strip(),
        "org_id":              org_id,
        "shipping_type":       ship_name,
        "is_rush":             is_rush,
        "is_depot_order":      is_depot,
        "depot_name":          depot_name,
        "final_destination":   (order.get("finalDestination") or "").strip(),
        "shipping_country":    shipping_country,
        # Always USD: every price Scout auto-fills (Allwhere's own price, TD Synnex/
        # Ingram/B&H stock price) is already USD. Select UK/EU quotes come back by
        # email, not through Scout, so there's never a real GBP/EUR number to convert.
        "currency":            "USD",
        "enterprise_warranty": enterprise_warranty,
        "enterprise_warranty_notes": enterprise_warranty_notes,
    }

def get_recipient_info(order_number: str) -> dict:
    """
    Returns recipient shipping info for a given order (used for BH Photo autofill).
    Data lives in the embedded 'recipient' field of the v2 order response.
    """
    po_clean = clean_po(order_number)
    try:
        r = requests.get(
            f"{ALLWHERE_BASE_V2}/order",
            auth=ALLWHERE_AUTH,
            params={"orderNumber": po_clean},
            timeout=15,
        )
    except requests.RequestException as e:
        return {"error": f"Allwhere order lookup failed: {e}"}

    if r.status_code != 200 or not r.json().get("items"):
        return {"error": f"No Allwhere order found for: {po_clean}"}

    order = r.json()["items"][0]
    rec   = order.get("recipient") or {}
    addr  = rec.get("address") or {}
    org   = order.get("organization") or {}

    if not rec:
        sc = (order.get("serviceCountry") or "").strip().lower()
        fd = (order.get("finalDestination") or "").lower()
        is_uk = sc in ("gb", "uk", "united kingdom") or "uk" in fd or "united kingdom" in fd

        if is_uk:
            return {
                "order_number": order_number,
                "first_name":   "allwhere ZAM19",
                "last_name":    order_number,
                "email":        "sourcing@allwhere.co",
                "phone":        "3477749603",
                "address1":     "Unit 8 Oakham Drive",
                "address2":     "Greenford Park",
                "city":         "Greenford",
                "state":        "Middlesex",
                "zip":          "UB6 0FD",
                "country":      "United Kingdom",
                "org_name":     (org.get("name") or "").strip(),
            }
        return {
            "order_number": order_number,
            "first_name":   "Zones c/o Allwhere",
            "last_name":    order_number,
            "email":        "sourcing@allwhere.co",
            "phone":        "347-774-9603",
            "address1":     "785 Center Ave",
            "address2":     "",
            "city":         "Carol Stream",
            "state":        "IL",
            "zip":          "60188",
            "country":      "United States",
            "org_name":     (org.get("name") or "").strip(),
        }

    country = (addr.get("country") or "").strip()
    if country.lower() == "united states":
        country = "United States"

    return {
        "order_number": order_number,
        "first_name":   (rec.get("firstName") or "").strip(),
        "last_name":    (rec.get("lastName") or "").strip(),
        "email":        (rec.get("email") or "").strip(),
        "phone":        (rec.get("phoneNumber") or "").strip(),
        "address1":     (addr.get("streetAddress1") or "").strip(),
        "address2":     (addr.get("streetAddress2") or "").strip(),
        "city":         (addr.get("city") or "").strip(),
        "state":        (addr.get("state") or "").strip(),
        "zip":          (addr.get("zipCode") or "").strip(),
        "country":      country,
        "org_name":     (org.get("name") or "").strip(),
    }

def _item_is_cto(item: dict, lead_time_approved: bool) -> bool:
    """
    True when an order item is a CTO device.
    Only Z-prefix MPNs are a reliable signal — heuristic fallback was
    too aggressive and flagged uncatalogued standard devices as CTO.
    """
    mpn = (item.get("mpn") or "").strip()
    return bool(mpn and mpn[0].upper() == "Z")

def generate_uk_email(order_number: str) -> dict:
    """
    Build a pre-filled UK vendor email for the given order.
    Returns {"email_text": ...} or {"error": "..."}.
    """
    header = get_order_header(order_number)
    if "error" in header:
        return header

    ew_fields = {
        "enterprise_warranty":       header.get("enterprise_warranty", False),
        "enterprise_warranty_notes": header.get("enterprise_warranty_notes", ""),
    }

    # ── Items with specs — separate devices from warranty ──────────────────
    _WARRANTY_RE = re.compile(r"apple\s*care|protection\s*plan|warranty|extended\s*service", re.IGNORECASE)

    _APPLE_KW = {"apple", "macbook", "ipad", "iphone", "imac", "mac mini", "mac studio", "mac pro", "airpods"}
    _BRAND_KW = ["lenovo", "dell", "hp", "microsoft", "samsung", "asus", "acer", "apple"]

    # Group by variant_id to consolidate duplicate items
    products_grouped = {}
    products_order = []
    warranty_grouped = {}
    warranty_order = []
    has_apple = False
    has_non_apple = False
    item_brands = set()

    for raw in header["raw_items"]:
        details = get_item_details(raw["productVariantId"], raw["quantity"])
        if "error" in details:
            snap = raw.get("snapshot") or {}
            if not snap:
                continue
            details = {
                "quantity":     raw["quantity"],
                "product_name": snap.get("productName") or snap.get("title", ""),
                "specs":        {a["name"]: a["value"] for a in (snap.get("attributes") or [])
                                 if a.get("name") and a.get("value")},
            }
        name  = details.get("product_name", "")
        specs = details.get("specs", {})
        qty   = details.get("quantity", 1)
        name = re.sub(r"^.*?\|\s*", "", name)
        mpn = details.get("allwhere_mpn", "")
        vid = raw["productVariantId"]

        if _WARRANTY_RE.search(name):
            if vid in warranty_grouped:
                warranty_grouped[vid]["qty"] += qty
            else:
                warranty_grouped[vid] = {"name": name, "qty": qty}
                warranty_order.append(vid)
        else:
            name_lower = name.lower()
            if any(kw in name_lower for kw in _APPLE_KW):
                has_apple = True
            else:
                has_non_apple = True
            for brand in _BRAND_KW:
                if brand in name_lower:
                    item_brands.add(brand)

            if vid in products_grouped:
                products_grouped[vid]["qty"] += qty
            else:
                spec_parts = []
                for key in ("Memory", "Storage", "Color"):
                    val = specs.get(key, "")
                    if val:
                        spec_parts.append(val)
                desc = f"{name} - {', '.join(spec_parts)}" if spec_parts else name
                products_grouped[vid] = {"desc": desc, "mpn": mpn, "qty": qty}
                products_order.append(vid)

    product_lines = []
    for i, vid in enumerate(products_order):
        if i > 0:
            product_lines.append("")
        g = products_grouped[vid]
        if g["qty"] > 1:
            product_lines.append(f"{g['qty']}x")
        if g["mpn"]:
            product_lines.append(g["mpn"])
        product_lines.append(g["desc"])

    warranty_lines = []
    for vid in warranty_order:
        g = warranty_grouped[vid]
        line = f"{g['qty']}x {g['name']}" if g["qty"] > 1 else g["name"]
        warranty_lines.append(line)

    if not product_lines and not warranty_lines:
        return {"error": "No items found for this order.", **ew_fields}

    # ── Recipient (shipping address) ─────────────────────────────────────────
    UK_STORAGE_ADDRESS = (
        "Unit 8 Oakham Drive\n"
        "Greenford Park\n"
        "Greenford, Middlesex UB6 0FD\n"
        "United Kingdom"
    )
    AU_STORAGE_ADDRESS = (
        "allwhere Storage Australia\n"
        "Unit 3\n"
        "1 Harford Street\n"
        "Jamison Town, NSW 2750\n"
        "Phone: 86-136-7164-9032"
    )
    fd_lower = header.get("final_destination", "").lower()
    if "allwhere storage uk" in fd_lower:
        shipped_to = UK_STORAGE_ADDRESS
    elif "allwhere storage australia" in fd_lower:
        shipped_to = AU_STORAGE_ADDRESS
    elif "ireland" in fd_lower and header.get("is_depot_order"):
        shipped_to = "Ireland Depot"
    else:
        recipient = get_recipient_info(order_number)
        if "error" in recipient:
            shipped_to = "(Could not fetch shipping address)"
        else:
            addr_parts = [
                f"{recipient.get('first_name', '')} {recipient.get('last_name', '')}".strip(),
                recipient.get("address1", ""),
            ]
            if recipient.get("address2"):
                addr_parts.append(recipient["address2"])
            city_line = ", ".join(filter(None, [
                recipient.get("city", ""),
                recipient.get("state", ""),
                recipient.get("zip", ""),
            ]))
            if city_line:
                addr_parts.append(city_line)
            country = recipient.get("country", "")
            if country:
                addr_parts.append(country)
            shipped_to = "\n".join(p for p in addr_parts if p)

    # ── Org data ─────────────────────────────────────────────────────────────
    org = {}
    org_id = header.get("org_id", "")
    if org_id:
        try:
            r = requests.get(
                f"{ALLWHERE_BASE}/organizations/{org_id}",
                auth=ALLWHERE_AUTH,
                timeout=15,
            )
            if r.status_code == 200:
                org = r.json()
        except requests.RequestException:
            pass

    # ── Enrollment — ABM for Apple, CSV for non-Apple ────────────────────────
    abm_number = (org.get("appleDepNumber") or "").strip()
    autopilot_text = (org.get("windowsAutopilot") or "").strip()

    # ── Assemble email ───────────────────────────────────────────────────────
    lines = ["Hi Cian,", ""]

    lines.append("Please quote:")
    for pl in product_lines:
        lines.append(pl)
    if warranty_lines:
        lines.append("Warranty:")
        for wl in warranty_lines:
            lines.append(wl)

    lines.append("")

    if ew_fields.get("enterprise_warranty") and ew_fields.get("enterprise_warranty_notes"):
        lines.append(f"With Enterprise Warranty — {ew_fields['enterprise_warranty_notes']}")
        lines.append("")

    if has_non_apple and autopilot_text:
        lines.append("Please provide a CSV hash extraction")
        lines.append("")

    if has_apple and abm_number:
        lines.append(f"Enrolled in ABM: {abm_number}")
        lines.append("")

    lines.append("Reminders:")
    lines.append("- Please include the adapter in the quote.")
    lines.append("")
    lines.append(f"Shipped to:\n{shipped_to}")

    additional = (org.get("additionalEnrollment") or "").strip()
    if additional:
        lines.append("")
        lines.append("Notes:")
        lines.append(additional)

    lines.append("")
    lines.append("Best,")
    lines.append("Sara")

    return {"email_text": "\n".join(lines), **ew_fields}

def generate_eu_email(order_number: str) -> dict:
    """
    Build a pre-filled EU vendor email for the given order.
    Standalone copy of generate_uk_email's logic (not a passthrough) —
    EU and UK share a vendor today but their wording is expected to
    diverge, so each template is edited independently.
    Returns {"email_text": ...} or {"error": "..."}.
    """
    header = get_order_header(order_number)
    if "error" in header:
        return header

    ew_fields = {
        "enterprise_warranty":       header.get("enterprise_warranty", False),
        "enterprise_warranty_notes": header.get("enterprise_warranty_notes", ""),
    }

    # ── Items with specs — separate devices from warranty ──────────────────
    _WARRANTY_RE = re.compile(r"apple\s*care|protection\s*plan|warranty|extended\s*service", re.IGNORECASE)

    _APPLE_KW = {"apple", "macbook", "ipad", "iphone", "imac", "mac mini", "mac studio", "mac pro", "airpods"}
    _BRAND_KW = ["lenovo", "dell", "hp", "microsoft", "samsung", "asus", "acer", "apple"]

    # Group by variant_id to consolidate duplicate items
    products_grouped = {}
    products_order = []
    warranty_grouped = {}
    warranty_order = []
    has_apple = False
    has_non_apple = False
    item_brands = set()
    has_cto_item = False

    for raw in header["raw_items"]:
        details = get_item_details(raw["productVariantId"], raw["quantity"])
        if "error" in details:
            snap = raw.get("snapshot") or {}
            if not snap:
                continue
            details = {
                "quantity":     raw["quantity"],
                "product_name": snap.get("productName") or snap.get("title", ""),
                "specs":        {a["name"]: a["value"] for a in (snap.get("attributes") or [])
                                 if a.get("name") and a.get("value")},
            }
        name  = details.get("product_name", "")
        specs = details.get("specs", {})
        qty   = details.get("quantity", 1)
        name = re.sub(r"^.*?\|\s*", "", name)
        mpn = details.get("allwhere_mpn", "")
        if mpn and mpn.upper().startswith("Z"):
            has_cto_item = True
        vid = raw["productVariantId"]

        if _WARRANTY_RE.search(name):
            if vid in warranty_grouped:
                warranty_grouped[vid]["qty"] += qty
            else:
                warranty_grouped[vid] = {"name": name, "qty": qty}
                warranty_order.append(vid)
        else:
            name_lower = name.lower()
            if any(kw in name_lower for kw in _APPLE_KW):
                has_apple = True
            else:
                has_non_apple = True
            for brand in _BRAND_KW:
                if brand in name_lower:
                    item_brands.add(brand)

            if vid in products_grouped:
                products_grouped[vid]["qty"] += qty
            else:
                spec_parts = []
                for key in ("Memory", "Storage", "Color"):
                    val = specs.get(key, "")
                    if val:
                        spec_parts.append(val)
                desc = f"{name} - {', '.join(spec_parts)}" if spec_parts else name
                products_grouped[vid] = {"desc": desc, "mpn": mpn, "qty": qty}
                products_order.append(vid)

    product_lines = []
    for i, vid in enumerate(products_order):
        if i > 0:
            product_lines.append("")
        g = products_grouped[vid]
        if g["qty"] > 1:
            product_lines.append(f"{g['qty']}x")
        if g["mpn"]:
            product_lines.append(g["mpn"])
        product_lines.append(g["desc"])

    warranty_lines = []
    for vid in warranty_order:
        g = warranty_grouped[vid]
        line = f"{g['qty']}x {g['name']}" if g["qty"] > 1 else g["name"]
        warranty_lines.append(line)

    if not product_lines and not warranty_lines:
        return {"error": "No items found for this order.", **ew_fields}

    # ── Recipient (shipping address) ─────────────────────────────────────────
    UK_STORAGE_ADDRESS = (
        "Unit 8 Oakham Drive\n"
        "Greenford Park\n"
        "Greenford, Middlesex UB6 0FD\n"
        "United Kingdom"
    )
    fd_lower = header.get("final_destination", "").lower()
    if "allwhere storage uk" in fd_lower:
        shipped_to = UK_STORAGE_ADDRESS
    elif "ireland" in fd_lower and header.get("is_depot_order"):
        shipped_to = "Ireland Depot"
    else:
        recipient = get_recipient_info(order_number)
        if "error" in recipient:
            shipped_to = "(Could not fetch shipping address)"
        else:
            addr_parts = [
                f"{recipient.get('first_name', '')} {recipient.get('last_name', '')}".strip(),
                recipient.get("address1", ""),
            ]
            if recipient.get("address2"):
                addr_parts.append(recipient["address2"])
            city_line = ", ".join(filter(None, [
                recipient.get("city", ""),
                recipient.get("state", ""),
                recipient.get("zip", ""),
            ]))
            if city_line:
                addr_parts.append(city_line)
            country = recipient.get("country", "")
            if country:
                addr_parts.append(country)
            shipped_to = "\n".join(p for p in addr_parts if p)

    # ── Org data ─────────────────────────────────────────────────────────────
    org = {}
    org_id = header.get("org_id", "")
    if org_id:
        try:
            r = requests.get(
                f"{ALLWHERE_BASE}/organizations/{org_id}",
                auth=ALLWHERE_AUTH,
                timeout=15,
            )
            if r.status_code == 200:
                org = r.json()
        except requests.RequestException:
            pass

    # ── Enrollment — ABM for Apple, CSV for non-Apple ────────────────────────
    abm_number = (org.get("appleDepNumber") or "").strip()
    autopilot_text = (org.get("windowsAutopilot") or "").strip()

    # ── Assemble email ───────────────────────────────────────────────────────
    lines = ["Hi Cian,", ""]

    lines.append("Please quote:")
    for pl in product_lines:
        lines.append(pl)
    if warranty_lines:
        lines.append("Warranty:")
        for wl in warranty_lines:
            lines.append(wl)

    lines.append("")

    if ew_fields.get("enterprise_warranty") and ew_fields.get("enterprise_warranty_notes"):
        lines.append(f"With Enterprise Warranty — {ew_fields['enterprise_warranty_notes']}")
        lines.append("")

    if has_non_apple and autopilot_text:
        lines.append("Please provide a CSV hash extraction")
        lines.append("")

    if has_apple and abm_number:
        lines.append(f"Enrolled in ABM: {abm_number}")
        lines.append("")

    if not has_cto_item:
        lines.append("Reminders:")
        lines.append("- Please include the adapter in the quote.")
        lines.append("")
    lines.append(f"Shipped to:\n{shipped_to}")

    additional = (org.get("additionalEnrollment") or "").strip()
    if additional:
        lines.append("")
        lines.append("Notes:")
        lines.append(additional)

    lines.append("")
    lines.append("Best,")
    lines.append("Sara")

    return {"email_text": "\n".join(lines), **ew_fields}

def generate_us_email(order_number: str) -> dict:
    """
    Build a pre-filled US vendor email for the given order.
    Returns {"email_text": ...} or {"error": "..."}.
    """
    header = get_order_header(order_number)
    if "error" in header:
        return header

    _WARRANTY_RE = re.compile(r"apple\s*care|protection\s*plan|warranty|extended\s*service", re.IGNORECASE)
    _APPLE_KW = {"apple", "macbook", "ipad", "iphone", "imac", "mac mini", "mac studio", "mac pro", "airpods"}
    _BRAND_KW = ["lenovo", "dell", "hp", "microsoft", "samsung", "asus", "acer", "apple"]

    products = []
    warranty_skus = []
    has_apple = False
    has_non_apple = False
    item_brands = set()

    for raw in header["raw_items"]:
        details = get_item_details(raw["productVariantId"], raw["quantity"])
        if "error" in details:
            snap = raw.get("snapshot") or {}
            if not snap:
                continue
            details = {
                "quantity":     raw["quantity"],
                "product_name": snap.get("productName") or snap.get("title", ""),
                "specs":        {a["name"]: a["value"] for a in (snap.get("attributes") or [])
                                 if a.get("name") and a.get("value")},
            }
        name  = details.get("product_name", "")
        specs = details.get("specs", {})
        qty   = details.get("quantity", 1)
        name = re.sub(r"^.*?\|\s*", "", name)
        mpn = details.get("allwhere_mpn", "")
        vid = raw["productVariantId"]
        needs_warranty = raw.get("protection_plan", "") not in ("", "No protection plan")

        if _WARRANTY_RE.search(name):
            warranty_skus.append({"name": name, "qty": qty})
        else:
            name_lower = name.lower()
            if any(kw in name_lower for kw in _APPLE_KW):
                has_apple = True
            else:
                has_non_apple = True
            for brand in _BRAND_KW:
                if brand in name_lower:
                    item_brands.add(brand)

            spec_parts = []
            for key in ("Color", "Memory", "Storage", "Keyboard", "Processor", "Display Size"):
                val = specs.get(key, "")
                if val:
                    spec_parts.append(val)

            existing = next((p for p in products if p["vid"] == vid), None)
            if existing:
                existing["qty"] += qty
                if needs_warranty:
                    existing["warranty"] = True
            else:
                products.append({
                    "name": name,
                    "mpn": mpn,
                    "specs": ", ".join(spec_parts),
                    "qty": qty,
                    "warranty": needs_warranty,
                    "vid": vid,
                })

    if not products and not warranty_skus:
        return {"error": "No items found for this order."}

    # ── Recipient ────────────────────────────────────────────────────────────
    recipient = get_recipient_info(order_number)
    if "error" in recipient:
        shipped_to = "(Could not fetch shipping address)"
        phone_line = ""
    else:
        addr_parts = [
            f"{recipient.get('first_name', '')} {recipient.get('last_name', '')}".strip(),
            recipient.get("address1", ""),
        ]
        if recipient.get("address2"):
            addr_parts.append(recipient["address2"])
        city_state = ", ".join(filter(None, [
            recipient.get("city", ""),
            recipient.get("state", ""),
        ]))
        if city_state:
            addr_parts.append(city_state)
        if recipient.get("zip"):
            addr_parts.append(recipient["zip"])
        country = recipient.get("country", "")
        if country:
            addr_parts.append(country)
        shipped_to = "\n".join(p for p in addr_parts if p)
        phone_line = recipient.get("phone", "")

    # ── Org data ─────────────────────────────────────────────────────────────
    org = {}
    org_id = header.get("org_id", "")
    if org_id:
        try:
            r = requests.get(
                f"{ALLWHERE_BASE}/organizations/{org_id}",
                auth=ALLWHERE_AUTH,
                timeout=15,
            )
            if r.status_code == 200:
                org = r.json()
        except requests.RequestException:
            pass

    # ── Deal Registration ────────────────────────────────────────────────────
    org_notes = (org.get("internalNotes") or "").strip()
    deal_reg_block = ""
    has_deal_reg = False
    deal_match = re.search(
        r"(Approved Deal Registration \(([^)]+)\)\s*\n\s*Deal ID:\s*.+\n\s*Expiry Date:\s*.+)",
        org_notes,
    )
    if deal_match:
        deal_brand = deal_match.group(2).strip().lower()
        if deal_brand in item_brands:
            deal_reg_block = deal_match.group(1).strip()
            has_deal_reg = True

    # ── Enrollment ───────────────────────────────────────────────────────────
    abm_number = (org.get("appleDepNumber") or "").strip()
    autopilot_text = (org.get("windowsAutopilot") or "").strip()

    # ── Assemble email ───────────────────────────────────────────────────────
    greeting = "Hi Don," if has_deal_reg else "Hi Jeremy,"
    lines = [greeting, ""]

    if deal_reg_block:
        deal_brand_name = deal_match.group(2).strip() if deal_match else ""
        if deal_brand_name.lower() == "dell":
            lines.append("This order has a deal registration!")
            lines.append("")
        lines.append(deal_reg_block)
        lines.append("")

    lines.append("Please quote")
    lines.append("")

    for p in products:
        if p["qty"] > 1:
            lines.append(f"{p['qty']}X")
        else:
            lines.append("1X")
        if p["mpn"]:
            lines.append(f"MPN: {p['mpn']}")
        lines.append(p["name"])
        if p["specs"]:
            lines.append(p["specs"])
        if p["warranty"]:
            lines.append("")
            lines.append("With warranty")
        lines.append("")

    if warranty_skus:
        for ws in warranty_skus:
            line = f"{ws['qty']}x {ws['name']}" if ws["qty"] > 1 else ws["name"]
            lines.append(line)
        lines.append("")

    enterprise_warranty = header.get("enterprise_warranty", False)
    enterprise_warranty_notes = header.get("enterprise_warranty_notes", "")
    if enterprise_warranty and enterprise_warranty_notes:
        lines.append(f"With Enterprise Warranty — {enterprise_warranty_notes}")
        lines.append("")

    if has_non_apple and autopilot_text:
        lines.append("Enrolled in Autopilot")
        lines.append(autopilot_text)
        lines.append("")

    if has_apple and abm_number:
        lines.append(f"Enrolled in ABM: {abm_number}")
        lines.append("")

    shipping_speed = header.get("shipping_type", "")
    if shipping_speed:
        lines.append(shipping_speed)
    lines.append(f"Shipped to:\n{shipped_to}")
    if phone_line:
        lines.append(phone_line)

    lines.append("")
    lines.append("")
    lines.append("Best,")
    lines.append("Sara")

    return {"email_text": "\n".join(lines)}

def generate_auto_quote_email(order_number: str) -> dict:
    """
    Auto-route a quote request email based on shipping country.
    Returns {order_number, region, shipping_country, to, cc, subject, email_text}
    or {error}.
    """
    ROUTING = {
        "uk": {
            "to": ["cian.samuel-maher@selecttechgroup.com", "jack.bryan@selecttechgroup.com"],
            "cc": [],
            "greeting": None,
        },
        "eu": {
            "to": ["cian.samuel-maher@selecttechgroup.com", "jack.bryan@selecttechgroup.com"],
            "cc": [],
            "greeting": None,
        },
        "au": {
            "to": ["john.angel@compnow.com.au", "uyen.ngo@compnow.com.au"],
            "cc": [],
            "greeting": "Hi John & Uyen,",
        },
        "nz": {
            "to": ["darryl.coughey@cyclone.co.nz"],
            "cc": ["sam.savea@cyclone.co.nz"],
            "greeting": "Hi Darryl,",
        },
        "us": {
            "to": ["Jeremy.Houck@tdsynnex.com", "SMB17001@tdsynnex.com"],
            "cc": [],
            "greeting": "Hi Jeremy & SMB Team,",
        },
    }

    header = get_order_header(order_number)
    if "error" in header:
        return header

    country = (header.get("shipping_country") or "").strip().lower()
    if not country:
        recipient = get_recipient_info(order_number)
        if "error" not in recipient:
            country = (recipient.get("country") or "").strip().lower()
    if country in ("united states", "us", "usa"):
        region = "us"
    elif country in ("australia", "au"):
        region = "au"
    elif country in ("new zealand", "nz"):
        region = "nz"
    elif country in UK_COUNTRIES:
        region = "uk"
    elif country in EU_COUNTRIES:
        region = "eu"
    else:
        # Unrecognized/blank country — fall back to the UK template and vendor.
        region = "uk"

    route = ROUTING[region]

    if region == "eu":
        result = generate_eu_email(order_number)
    elif region in ("uk", "au", "nz"):
        result = generate_uk_email(order_number)
    else:
        result = generate_us_email(order_number)

    if "error" in result:
        return result

    email_text = result["email_text"]

    if route["greeting"]:
        lines = email_text.split("\n")
        lines[0] = route["greeting"]
        email_text = "\n".join(lines)

    # "Hope all is well!" + line space after "Please quote"
    email_text = email_text.replace("Please quote:", "Hope all is well!\n\nPlease quote:\n", 1)
    email_text = email_text.replace("Please quote\n", "Hope all is well!\n\nPlease quote\n", 1)

    # UK orders (P2R and P2D) skip the adapter reminder entirely
    if region == "uk":
        email_text = email_text.replace(
            "Reminders:\n- Please include the adapter in the quote.\n\n", "", 1
        )

    # Adapter reminder language
    email_text = email_text.replace(
        "- Please include the adapter in the quote.",
        "- Please include relevant adaptors in the quote.",
    )

    to_addrs = route["to"]
    cc_addrs = route["cc"] + ["sourcing@allwhere.co"]
    subject = order_number

    # Create Gmail draft
    draft_url = None
    try:
        from gmail_auth import get_gmail_service
        svc = get_gmail_service()
        msg = MIMEText(email_text)
        msg["to"] = ", ".join(to_addrs)
        if cc_addrs:
            msg["cc"] = ", ".join(cc_addrs)
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        draft = svc.users().drafts().create(
            userId="me", body={"message": {"raw": raw}}
        ).execute()
        draft_id = draft["id"]
        draft_url = f"https://mail.google.com/mail/u/0/#drafts?compose={draft['message']['id']}"
    except Exception as e:
        return {"error": f"Email generated but Gmail draft failed: {e}"}

    return {
        "order_number": order_number,
        "region": region,
        "shipping_country": header.get("shipping_country", ""),
        "to": to_addrs,
        "cc": cc_addrs,
        "subject": subject,
        "email_text": email_text,
        "draft_url": draft_url,
    }

def get_order_info_for_ticket(order_number: str) -> dict:
    """
    Fetch all data needed to pre-fill the Create Ticket panel.
    Returns order header + per-item details (name, MPN, price).
    """
    header = get_order_header(order_number)
    if "error" in header:
        return header

    items = []
    for raw in header["raw_items"]:
        details = get_item_details(raw["productVariantId"], raw["quantity"])
        if "error" in details:
            snap = raw.get("snapshot") or {}
            if not snap:
                continue
            # v1 product-variant endpoint returned 404 (deleted/archived variant) —
            # reconstruct from the snapshot Allwhere embeds in v2 order items.
            details = {
                "variant_id":    raw["productVariantId"],
                "quantity":      raw["quantity"],
                "sku":           str(snap.get("sku", "")),
                "product_id":    snap.get("productId", ""),
                "product_name":  snap.get("productName") or snap.get("title", ""),
                "price_charged": float(snap.get("price", 0) or 0),
                "specs":         {a["name"]: a["value"] for a in (snap.get("attributes") or [])
                                  if a.get("name") and a.get("value")},
                "allwhere_mpn":  snap.get("mpn") or "",
            }
        sku          = details.get("sku", "")
        product_name = details.get("product_name", "")
        specs        = details.get("specs", {})
        # Product-service is the sole source of truth for MPN.
        # If PS knows the variant and has null, that means no MPN — stop there.
        # Only fall back to description extraction if PS has never heard of this variant.
        ps_data = _ps_variant(raw["productVariantId"])
        if ps_data.get("found"):
            mpn = ps_data.get("mpn") or ""
        else:
            # PS doesn't know this variant ID — use mono description extraction only
            mpn = details.get("allwhere_mpn") or ""
        items.append({
            "variant_id":   raw["productVariantId"],
            "sku":          sku,
            "product_name": product_name,
            "specs":        specs,
            "mpn":          mpn,
            "price":        details.get("price_charged", 0),
            "quantity":     raw["quantity"],
            "asset_id":     raw.get("asset_id"),
        })

    lead_time_approved = header["lead_time_approved"]
    cto_detected       = any(_item_is_cto(i, lead_time_approved) for i in items)
    cto_mpns           = [i["mpn"] for i in items if (i.get("mpn") or "").upper().startswith("Z")]
    has_autopilot      = any(
        kw in (i.get("product_name") or "").lower()
        for i in items for kw in ("autopilot", "intune")
    )

    return {
        "order_number":        header["order_number"],
        "org_name":            header["org_name"],
        "order_manager_email": header["order_manager_email"],
        "order_manager_name":  header["order_manager_name"],
        "procurement_manager_email": header.get("procurement_manager_email", ""),
        "procurement_manager_name":  header.get("procurement_manager_name", ""),
        "is_rush":             header["is_rush"],
        "lead_time_approved":  lead_time_approved,
        "cto_detected":        cto_detected,
        "cto_mpns":            cto_mpns,
        "checkout_notes":      header["checkout_notes"],
        "internal_notes":      header["internal_notes"],
        "enterprise_warranty": header.get("enterprise_warranty", False),
        "enterprise_warranty_notes": header.get("enterprise_warranty_notes", ""),
        "has_autopilot":       has_autopilot,
        "items":               items,
        "is_depot_order":      header.get("is_depot_order", False),
        "depot_name":          header.get("depot_name", ""),
        "shipping_country":    header.get("shipping_country", ""),
    }

def get_item_details(variant_id: str, quantity: int) -> dict:
    """
    Fetch product info for one line item (steps 3-5 of the old chain):
      3. /product-variant/{id}            → sku, price, productId
      4. /product/{productId}             → name
      5. /product-variant-attribute?...   → specs
    Returns item dict. On error includes "error" key.
    Caches result by variant_id (7 day TTL).
    """
    cached = cache_get("variants", f"item:{variant_id}")
    if cached and cached.get("allwhere_mpn"):
        # Only trust cache if it already has an MPN — otherwise re-fetch so
        # variants cached before the product-service fallback was added get fixed.
        cached["quantity"] = quantity
        return cached

    # Step 3
    try:
        r3 = requests.get(
            f"{ALLWHERE_BASE}/product-variant/{variant_id}",
            auth=ALLWHERE_AUTH,
            timeout=15,
        )
    except requests.RequestException as e:
        return {"error": f"Product-variant lookup failed: {e}"}

    if r3.status_code == 404:
        # Variant only exists in new product-service catalog (mono doesn't have it)
        ps = _ps_variant(variant_id)
        if ps:
            result = {
                "variant_id":    variant_id,
                "quantity":      quantity,
                "sku":           ps["sku"],
                "product_id":    "",
                "product_name":  ps["product_name"],
                "price_charged": ps["price_charged"],
                "specs":         ps["attributes"],
                "allwhere_mpn":  ps["mpn"],
            }
            cacheable = {k: v for k, v in result.items() if k != "quantity"}
            cache_set("variants", f"item:{variant_id}", cacheable)
            return result
        return {"error": f"Could not fetch variant {variant_id} (404 in mono, not in product-service)"}

    if r3.status_code != 200:
        return {"error": f"Could not fetch variant {variant_id} (HTTP {r3.status_code})"}

    variant       = r3.json()
    sku           = str(variant.get("sku", ""))
    price_charged = float(variant.get("price", 0) or 0)
    product_id    = variant.get("productId", "")

    # Step 4
    product_name = ""
    allwhere_mpn = ""
    try:
        r4 = requests.get(
            f"{ALLWHERE_BASE}/product/{product_id}",
            auth=ALLWHERE_AUTH,
            timeout=15,
        )
        if r4.status_code == 200:
            p4 = r4.json()
            product_name = p4.get("name", "")
            allwhere_mpn = _extract_allwhere_mpn(p4.get("description", ""))
    except requests.RequestException:
        pass

    # Step 5
    specs = {}
    try:
        r5 = requests.get(
            f"{ALLWHERE_BASE}/product-variant-attribute",
            auth=ALLWHERE_AUTH,
            params={"productVariantId": variant_id},
            timeout=15,
        )
        if r5.status_code == 200:
            for attr in r5.json().get("items", []):
                n, v = attr.get("name", ""), attr.get("value", "")
                if n and v:
                    specs[n] = v
    except requests.RequestException:
        pass

    result = {
        "variant_id":    variant_id,
        "quantity":      quantity,
        "sku":           sku,
        "product_id":    product_id,
        "product_name":  product_name,
        "price_charged": price_charged,
        "specs":         specs,
        "allwhere_mpn":  allwhere_mpn,
    }
    # Cache without quantity (runtime-specific)
    cacheable = {k: v for k, v in result.items() if k != "quantity"}
    cache_set("variants", f"item:{variant_id}", cacheable)
    return result

# ── from order_confirm_engine.py ──
ALLWHERE_BASE_V2 = "https://service.production.allwhere.co/v2"

def _clean_po(po):
    return re.sub(r"\s*\(\d+\)\s*$", "", po.strip())

def fetch_full_order(order_number):
    """Fetch everything needed from the Allwhere v2 order in one call."""
    po = _clean_po(order_number)
    try:
        r = requests.get(
            f"{ALLWHERE_BASE_V2}/order",
            auth=ALLWHERE_AUTH,
            params={"orderNumber": po},
            timeout=15,
        )
    except requests.RequestException as e:
        return {"error": f"Allwhere lookup failed: {e}"}

    if r.status_code != 200 or not r.json().get("items"):
        return {"error": f"No Allwhere order found for: {po}"}

    order = r.json()["items"][0]
    rec = order.get("recipient") or {}
    rec_addr = rec.get("address") or {}
    org = order.get("organization") or {}
    purchaser = order.get("purchaser") or {}
    ship = order.get("shippingType") or {}

    if not rec:
        sc = (order.get("serviceCountry") or "").strip().lower()
        fd = (order.get("finalDestination") or "").lower()
        is_uk = sc in ("gb", "uk", "united kingdom") or "uk" in fd or "united kingdom" in fd
        if is_uk:
            rec = {"firstName": "allwhere ZAM19", "lastName": po,
                   "phoneNumber": "3477749603",
                   "address": {"streetAddress1": "Unit 8 Oakham Drive",
                               "streetAddress2": "Greenford Park",
                               "city": "Greenford", "state": "Middlesex",
                               "zipCode": "UB6 0FD", "country": "United Kingdom"}}
        else:
            rec = {"firstName": "Zones c/o Allwhere", "lastName": po,
                   "phoneNumber": "347-774-9603",
                   "address": {"streetAddress1": "785 Center Ave",
                               "streetAddress2": "",
                               "city": "Carol Stream", "state": "IL",
                               "zipCode": "60188", "country": "United States"}}
        rec_addr = rec["address"]

    # Billing address (separate API calls)
    billing = _fetch_billing_address(org.get("id", ""))

    # Parse autopilot tenant info from org field
    autopilot_info = _parse_autopilot_info(org)

    # Check if order has autopilot item
    has_autopilot = False
    order_items = []
    for oi in order.get("orderItems", []):
        snap = oi.get("productVariantSnapshot") or {}
        title = (snap.get("title") or snap.get("productName") or "").lower()
        mpn = snap.get("mpn") or ""
        if "autopilot" in title or "intune" in title:
            has_autopilot = True
            continue
        if not mpn:
            continue
        order_items.append({
            "mpn": mpn,
            "name": snap.get("title") or snap.get("productName") or "",
            "qty": int(oi.get("quantity") or 1),
            "price": float(snap.get("price") or 0),
        })

    return {
        "order_number": po,
        "org_name": (org.get("name") or "").strip(),
        "org_id": (org.get("id") or "").strip(),
        "shipping_type": (ship.get("name") or "").strip(),
        "has_autopilot": has_autopilot,
        "autopilot_info": autopilot_info,
        "order_items": order_items,
        "recipient": {
            "first_name": (rec.get("firstName") or "").strip(),
            "last_name": (rec.get("lastName") or "").strip(),
            "phone": (rec.get("phoneNumber") or "").strip(),
            "address1": (rec_addr.get("streetAddress1") or "").strip(),
            "address2": (rec_addr.get("streetAddress2") or "").strip(),
            "city": (rec_addr.get("city") or "").strip(),
            "state": (rec_addr.get("state") or "").strip(),
            "zip": (rec_addr.get("zipCode") or "").strip(),
            "country": (rec_addr.get("country") or "United States").strip(),
        },
        "purchaser": {
            "name": f"{(purchaser.get('firstName') or '')} {(purchaser.get('lastName') or '')}".strip(),
            "email": (purchaser.get("workEmail") or purchaser.get("email") or "").strip(),
            "phone": (purchaser.get("phoneNumber") or "").strip(),
        },
        "billing": billing,
    }

def _fetch_billing_address(org_id):
    if not org_id:
        return None
    try:
        r = requests.get(
            f"{ALLWHERE_BASE}/billing-address",
            auth=ALLWHERE_AUTH,
            params={"organizationId": org_id},
            timeout=15,
        )
        if r.status_code != 200:
            return None
        items = (r.json().get("items") or [])
        if not items:
            return None

        billing = items[0]
        addr_id = billing.get("addressId")
        result = {
            "email": (billing.get("email") or "").strip(),
            "phone": (billing.get("phoneNumber") or "").strip(),
        }

        if not addr_id:
            return result

        r2 = requests.get(
            f"{ALLWHERE_BASE}/address/{addr_id}",
            auth=ALLWHERE_AUTH,
            timeout=15,
        )
        if r2.status_code != 200:
            return result

        addr = r2.json()
        result.update({
            "street1": (addr.get("streetAddress1") or "").strip(),
            "street2": (addr.get("streetAddress2") or "").strip(),
            "city": (addr.get("city") or "").strip(),
            "state": (addr.get("state") or "").strip(),
            "zip": (addr.get("zipCode") or "").strip(),
            "country": (addr.get("country") or "").strip(),
        })
        return result
    except requests.RequestException:
        return None

def _parse_autopilot_info(org):
    text = (org.get("windowsAutopilot") or "").strip()
    if not text:
        return None
    info = {}
    for line in text.split("\n"):
        line = line.strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key_lower = key.strip().lower()
        val = val.strip()
        if "domain" in key_lower:
            info["domain"] = val
        elif "id" in key_lower:
            info["id"] = val
        elif "email" in key_lower or "admin" in key_lower:
            info["admin_email"] = val
        elif "name" in key_lower:
            info["name"] = val
    return info if info else None

def build_confirmation_email(order_data, card_last4, quote_total):
    """Build the confirmation email body text."""
    po = order_data["order_number"]
    rec = order_data["recipient"]
    billing = order_data.get("billing") or {}
    purchaser = order_data["purchaser"]
    shipping = order_data.get("shipping_type", "")

    sig = "Yes"
    try:
        if quote_total and float(quote_total) <= 500:
            sig = "No"
    except (ValueError, TypeError):
        pass

    # Ship-To block
    ship_name = f"{rec['first_name']} {rec['last_name']}".strip()
    ship_lines = [ship_name, rec["address1"]]
    if rec.get("address2"):
        ship_lines.append(rec["address2"])
    ship_lines.append(f"{rec['city']}, {rec['state']}")
    ship_lines.append(rec["zip"])
    ship_lines.append(rec["country"])
    if rec.get("phone"):
        ship_lines.append(rec["phone"])

    # End User block
    eu_street = billing.get("street1", "")
    if billing.get("street2"):
        eu_street += f"\n{billing['street2']}"
    eu_city = billing.get("city", "")
    eu_state = billing.get("state", "")
    eu_zip = billing.get("zip", "")
    eu_country = billing.get("country", "United States")

    purchaser_phone = purchaser.get("phone") or "3477749603"

    lines = [
        "Hi Team,",
        "",
        "Thank you! This order is confirmed, please process!",
        "",
        f"Signature Required: {sig}",
        f"Required PO Number: {po}",
        "",
        f"Payment type (if CC, please provide the last 4 digits) : {card_last4}",
        "",
        shipping,
        "Shipped to:",
        *ship_lines,
        "",
        "End User Information",
        f"Company Name: {order_data['org_name']}",
        eu_street,
        f"{eu_city}, {eu_state} {eu_zip}",
        eu_country,
        f"End User Email: {purchaser['email']}",
        f"Phone Number: {purchaser_phone}",
        f"Contact Name: {purchaser['name']}",
        "",
        "Best,",
        "Sara",
    ]

    return "\n".join(lines)
