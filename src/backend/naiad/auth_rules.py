"""Pure auth predicates (no FastAPI/DB deps) so they can be reused by the REST
dependency, the WebSocket endpoint, and the auto-login route — and unit-tested."""

from urllib.parse import urlparse

from naiad.config import ForwardHeaderConfig, IngressConfig

# Header the Supervisor sets on every ingress-proxied request (the path prefix).
INGRESS_HEADER = "X-Ingress-Path"


def ingress_request_ok(client_ip: str, ingress_header: str, cfg: IngressConfig) -> bool:
    """True if the request arrived through the Supervisor ingress proxy.

    Ingress traffic originates from the Supervisor's fixed internal IP *and* carries
    the ``X-Ingress-Path`` header. The source-IP check is load-bearing (a LAN client
    cannot spoof it over TCP); the header corroborates that it is genuine ingress
    traffic rather than some other call from that address. When this holds, Home
    Assistant has already authenticated the user, so no Naiad login is required.
    """
    if not cfg.enabled:
        return False
    if not ingress_header:
        return False
    return client_ip == cfg.trusted_ip


def forward_header_ok(header_value: str, client_ip: str, cfg: ForwardHeaderConfig) -> bool:
    """True if a trusted reverse proxy asserted an authenticated user.

    Requires the configured header to be present and non-empty. If
    ``trusted_proxies`` is configured, the request must also originate from one
    of those proxy IPs (so the header can't be spoofed by an arbitrary client).
    """
    if not header_value:
        return False
    if not cfg.trusted_proxies:
        return True
    return client_ip in cfg.trusted_proxies


def referer_matches(referer: str, trusted_referers: list[str]) -> bool:
    """Match a Referer against a trusted list by origin/host, not substring.

    A substring check (``entry in referer``) is trivially bypassable
    (``https://evil.example/?x=trusted.host``). Each trusted entry is compared
    either as a full origin (when it contains ``://``) or as an exact hostname.
    """
    if not referer:
        return False
    parsed = urlparse(referer)
    host = parsed.hostname or ""
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    for entry in trusted_referers:
        e = entry.strip().rstrip("/")
        if not e:
            continue
        if "://" in e:
            if origin and origin == e:
                return True
        elif host and host == e:
            return True
    return False
