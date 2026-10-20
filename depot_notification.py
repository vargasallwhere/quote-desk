"""Australia depot eligibility and read-only arrival template. No Gmail operations."""
import json
import re

DESTINATION = "allwhere storage Australia"
TO = ('Marc.Breynart@systemsgo.asia, Support Centre - systemsGo AU <Support.AU@systemsgo.asia>, '
      '"Garcia, Gener (systemsGo)" <Gener.Garcia@systemsgo.asia>, '
      '"Yu, Wendy (systemsGo)" <Wendy.Yu@systemsgo.asia>')
CC = "sourcing@allwhere.co"
NONPHYSICAL = re.compile(
    r"apple\s*care|warranty|protection\s*plan|extended\s*service|service\s*agreement|"
    r"enroll?ment|autopilot|intune|abm\s*(?:service|registration)|"
    r"software|subscription|licen[cs]e|insurance|configuration\s*service|deployment\s*service",
    re.I)
SPEC_KEYS = ("Color", "Colour", "Finish", "Memory", "RAM", "Storage", "Keyboard",
             "Processor", "CPU", "Graphics", "GPU", "Display", "Screen", "Screen Size")


def normalized(value):
    return " ".join(value.casefold().split()) if isinstance(value, str) else ""


def eligibility(order):
    kind = order.get("orderType")
    depot = order.get("depot")
    flag = kind.get("toDepot") if isinstance(kind, dict) else None
    name = depot.get("name") if isinstance(depot, dict) else None
    final = order.get("finalDestination")
    eligible = flag is True and normalized(name) == normalized(DESTINATION)
    reason = ""
    if flag is not True:
        reason = "Depot notification unavailable: the source does not explicitly mark this as a to-depot order."
    elif not normalized(name):
        reason = "Depot notification unavailable: depot identity is missing."
    elif not eligible:
        reason = "Depot notification unavailable: this is a different depot."
    elif normalized(final) and normalized(final) != normalized(name):
        eligible = False
        reason = "Depot notification unavailable: destination and depot identity conflict. Check the order source."
    return {"eligible": eligible, "destination": DESTINATION if eligible else (name or ""),
            "reason": reason, "is_depot_order": flag is True}


def preview(order):
    from scout_port import get_item_details
    check = eligibility(order)
    if not check["eligible"]:
        raise ValueError(check["reason"])
    blocks, groups, warnings = [], {}, []
    for index, line in enumerate(order.get("orderItems") or []):
        snap = line.get("productVariantSnapshot")
        snap = snap if isinstance(snap, dict) else {}
        snapshot_name = snap.get("title") or snap.get("productName") or ""
        if NONPHYSICAL.search(snapshot_name):
            continue
        qty = line.get("quantity", 1)
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValueError("An item has an invalid quantity. Correct the order before preparing a notification.")
        variant = line.get("productVariantId") or (line.get("asset") or {}).get("productVariantId")
        if variant:
            details = get_item_details(variant, qty, snap)
        else:
            details = {"product_name": snapshot_name, "sku": snap.get("sku"),
                       "allwhere_mpn": snap.get("mpn"), "specs": snap.get("attributes") or {},
                       "mpn_source": "order_snapshot"}
        name = details.get("product_name") or snapshot_name
        if NONPHYSICAL.search(name):
            continue
        label = f"Item {index + 1}"
        if not name or name.startswith("Variant "):
            name = "[Product name unavailable — review]"
            warnings.append(f"{label}: product name is unavailable; verify this is a physical item.")
        mpn = details.get("allwhere_mpn") or "[MPN unavailable — review]"
        source = details.get("mpn_source")
        specs = details.get("specs") or {}
        specs = specs if isinstance(specs, dict) else {}
        parts = [str(specs[k]).strip() for k in SPEC_KEYS
                 if isinstance(specs.get(k), str) and specs[k].strip()]
        parts = list(dict.fromkeys(parts))
        if source != "catalog":
            warnings.append(f"{label}: MPN and specifications are unverified against the current catalog. Review before sending.")
        if not details.get("allwhere_mpn"):
            warnings.append(f"{label}: MPN unavailable. Review before sending.")
        if not parts:
            warnings.append(f"{label}: specifications unavailable. Review before sending.")
        sku = details.get("sku")
        # Include ALL metadata, even attributes not rendered; never merge conflicts.
        source_metadata = {k: snap.get(k) for k in ("title", "productName", "mpn", "attributes")}
        key = (sku, name, mpn, source, json.dumps(specs, sort_keys=True),
               json.dumps(source_metadata, sort_keys=True)) if isinstance(sku, str) and sku.strip() else object()
        if snap.get("attributes") and snap.get("attributes") != specs:
            warnings.append(f"{label}: source specifications differ from the catalog; current catalog specifications are shown. Review this source line separately.")
        if key in groups:
            groups[key]["quantity"] += qty
        else:
            group = {"quantity": qty, "mpn": mpn, "name": name, "parts": parts}
            groups[key] = group
            blocks.append(group)
    if not blocks:
        raise ValueError("No physical items were found for this depot notification.")
    text = "\n\n".join(
        f"{g['quantity']}X {g['mpn']}\n{g['name']}" +
        ("\n" + ", ".join(g["parts"]) if g["parts"] else "") for g in blocks)
    return {"order_number": order["orderNumber"], "to": TO, "cc": CC,
            "subject": f"{order['orderNumber']} - Order coming to warehouse",
            "body": "Hi Team,\n\nPlease expect the following devices at your warehouse!\n\n" +
                    text + "\n\nBest,\nSara", "warnings": warnings}
