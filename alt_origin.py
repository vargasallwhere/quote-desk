"""Origin policy for review writes; forwarding headers are never authority."""
import ipaddress
import re
from urllib.parse import urlsplit

from flask import current_app, request


def valid_origin(value):
    """Accept only a single serialized HTTP(S) origin, not a URL or origin list."""
    if not isinstance(value, str) or not value or re.search(r"[\s\x00-\x1f\x7f\\]", value):
        return False
    try:
        parts = urlsplit(value)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.path or parts.query or parts.fragment
                or value != f"{parts.scheme}://{parts.netloc}"
                or parts.netloc.endswith(":")):
            return False
        port = parts.port
        if port is not None and not 1 <= port <= 65535:
            return False
        authority = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
        if port is not None:
            authority += f":{port}"
        if parts.netloc != authority:
            return False
        try:
            ipaddress.ip_address(parts.hostname)
        except ValueError:
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*",
                                parts.hostname):
                return False
        return True
    except ValueError:
        return False


def replit_origin(domain):
    # Runtime configuration, never Host/Origin/X-Forwarded-* request input.
    origin = "https://" + domain if isinstance(domain, str) else ""
    if (valid_origin(origin) and urlsplit(origin).hostname.endswith(".replit.dev")
            and urlsplit(origin).port is None):
        return origin
    return None


def public_origin(value):
    """A single operator-pinned HTTPS origin; invalid startup config fails closed."""
    if not valid_origin(value) or urlsplit(value).scheme != "https":
        raise ValueError("alternative_reviews.public_origin must be one HTTPS origin without a trailing slash.")
    return value


def allowed_write_origin():
    origin = request.headers.get("Origin")
    # Preserve non-browser JSON clients. JSON-only endpoint validation still applies.
    if origin is None:
        return True
    if not valid_origin(origin):
        return False
    for key in ("ALT_REVIEW_EXTERNAL_ORIGIN", "ALT_REVIEW_PUBLIC_ORIGIN"):
        external = current_app.config.get(key)
        if external and valid_origin(external) and origin == external:
            return True
    # Direct local operation needs no proxy trust, with exact scheme/host/port.
    direct = request.host_url.rstrip("/")
    if not valid_origin(direct) or origin != direct:
        return False
    host = urlsplit(direct).hostname
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
