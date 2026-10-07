"""Read-only product-service client. Never expose credentials or upstream bodies."""
import math
import os
from urllib.parse import quote

import requests

BASE = "https://product.allwhere.co/v1"
MESSAGES = {
    "missing_configuration": "Catalog credentials are missing. Configure PS_USER and PS_PASS in Replit Secrets.",
    "invalid_configuration": "Catalog credentials have invalid formatting. Check PS_USER and PS_PASS in Replit Secrets.",
    "authentication_rejected": "Catalog authentication was rejected (HTTP 401). Check product-service credentials.",
    "access_denied": "Catalog access was denied (HTTP 403). Check product-service permissions.",
    "not_found": "The catalog did not find this exact variant (HTTP 404).",
    "temporary_failure": "The catalog is temporarily unavailable. Retry the lookup.",
    "invalid_response": "The catalog returned invalid product data.",
    "identity_mismatch": "Catalog variant or SKU does not match this order item. Catalog data was not used.",
    "http_error": "The catalog request failed.",
}


def failure(status, variant_id, http_status=None):
    result = {"found": False, "status": status, "variant_id": variant_id,
              "message": MESSAGES[status]}
    if http_status is not None:
        result["http_status"] = http_status
    return result


def lookup_variant(variant_id, expected_sku=None):
    """Validate exact identity and structured MPN, including authoritative null.

    Load credentials for each request; missing/invalid config never sends a request.
    Do not cache failures or mix successful responses across credential changes.
    """
    user, password = os.environ.get("PS_USER", ""), os.environ.get("PS_PASS", "")
    if not user.strip() or not password.strip():
        return failure("missing_configuration", variant_id)
    if ":" in user or any(c in user + password for c in "\r\n"):
        return failure("invalid_configuration", variant_id)
    try:
        # requests' Basic-auth contract requires Latin-1 strings.
        (user + password).encode("latin-1")
    except UnicodeEncodeError:
        return failure("invalid_configuration", variant_id)
    try:
        response = requests.get(
            f"{BASE}/product-variants/{quote(str(variant_id), safe='')}",
            auth=(user, password), timeout=15,
        )
    except requests.RequestException:
        return failure("temporary_failure", variant_id)
    code = response.status_code
    if code != 200:
        status = {401: "authentication_rejected", 403: "access_denied", 404: "not_found"}.get(code)
        if not status:
            status = "temporary_failure" if code in (408, 425, 429) or code >= 500 else "http_error"
        return failure(status, variant_id, code)
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError
        sku = data.get("sku")
        if isinstance(sku, bool) or not isinstance(sku, (str, int)) or not str(sku).strip():
            raise ValueError
        if not isinstance(data.get("id"), str) or not data["id"]:
            raise ValueError
        if data["id"] != str(variant_id) or (
            expected_sku not in (None, "") and str(sku) != str(expected_sku)
        ):
            return failure("identity_mismatch", variant_id)
        if "mpn" not in data:
            raise ValueError
        mpn = data["mpn"]
        if mpn is not None and (not isinstance(mpn, str) or not mpn.strip()
                                or any(c in mpn for c in "\r\n")):
            raise ValueError
        title = data.get("title")
        attrs = data.get("attributes", {})
        if not isinstance(title, str) or not title.strip() or not isinstance(attrs, dict):
            raise ValueError
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in attrs.items()):
            raise ValueError
        raw_price = data.get("price")
        if isinstance(raw_price, bool):
            raise ValueError
        price = float(raw_price) if raw_price is not None else 0
        if not math.isfinite(price) or price < 0:
            raise ValueError
        if not isinstance(data.get("is_build_to_order", False), bool):
            raise ValueError
        return {
            "found": True, "status": "no_mpn" if mpn is None else "ok",
            "variant_id": data["id"], "sku": str(sku), "mpn": mpn,
            "product_name": title, "price_charged": price, "attributes": attrs,
            "price_available": raw_price is not None,
            "is_build_to_order": data.get("is_build_to_order", False),
        }
    except (ValueError, TypeError, OverflowError):
        return failure("invalid_response", variant_id)
