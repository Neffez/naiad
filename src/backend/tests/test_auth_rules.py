from naiad.auth_rules import forward_header_ok, ingress_request_ok, referer_matches
from naiad.config import ForwardHeaderConfig, IngressConfig


def test_forward_header_requires_header() -> None:
    # No header → reject. A present header without a trusted-proxy allowlist also
    # fails closed (the header is client-supplied and spoofable from the direct port).
    assert forward_header_ok("", "1.2.3.4", ForwardHeaderConfig()) is False
    assert forward_header_ok("alice", "1.2.3.4", ForwardHeaderConfig()) is False


def test_forward_header_fails_closed_without_trusted_proxies() -> None:
    # Default trusted_proxies is empty → no proxy can vouch for the header → reject,
    # regardless of source IP. Prevents an X-Forwarded-User spoof on the direct port.
    cfg = ForwardHeaderConfig()
    assert cfg.trusted_proxies == []
    assert forward_header_ok("alice", "10.0.0.1", cfg) is False
    assert forward_header_ok("alice", "172.30.32.2", cfg) is False


def test_forward_header_trusted_proxy() -> None:
    cfg = ForwardHeaderConfig(trusted_proxies=["10.0.0.1"])
    assert forward_header_ok("alice", "10.0.0.1", cfg) is True
    assert forward_header_ok("alice", "9.9.9.9", cfg) is False
    assert forward_header_ok("", "10.0.0.1", cfg) is False


def test_referer_substring_bypass_rejected() -> None:
    # The old substring check accepted this; origin matching must not.
    assert referer_matches("https://evil.example/?x=naiad.local", ["naiad.local"]) is False


def test_referer_exact_host_match() -> None:
    assert referer_matches("https://naiad.local/dashboard", ["naiad.local"]) is True
    assert referer_matches("https://naiad.local:8123/x", ["naiad.local"]) is True


def test_referer_origin_match() -> None:
    assert referer_matches("https://ha.local:8123/lovelace", ["https://ha.local:8123"]) is True
    assert referer_matches("http://ha.local:8123/lovelace", ["https://ha.local:8123"]) is False


def test_referer_empty_inputs() -> None:
    assert referer_matches("", ["naiad.local"]) is False
    assert referer_matches("https://naiad.local/", []) is False


# ── Ingress trust ──────────────────────────────────────────────────────────────


def test_ingress_trusts_supervisor_with_header() -> None:
    cfg = IngressConfig()  # enabled, trusted_ip = 172.30.32.2
    assert ingress_request_ok("172.30.32.2", "/api/hassio_ingress/abc", cfg) is True


def test_ingress_requires_header() -> None:
    # The Supervisor always sets X-Ingress-Path; a bare request from that IP without
    # it is not treated as ingress.
    assert ingress_request_ok("172.30.32.2", "", IngressConfig()) is False


def test_ingress_requires_supervisor_ip() -> None:
    # A LAN client (e.g. the direct port) cannot spoof the source IP, so even with a
    # forged header it is not trusted.
    assert ingress_request_ok("192.168.1.50", "/api/hassio_ingress/abc", IngressConfig()) is False


def test_ingress_can_be_disabled() -> None:
    cfg = IngressConfig(enabled=False)
    assert ingress_request_ok("172.30.32.2", "/api/hassio_ingress/abc", cfg) is False


def test_ingress_custom_trusted_ip() -> None:
    cfg = IngressConfig(trusted_ip="10.0.0.2")
    assert ingress_request_ok("10.0.0.2", "/x", cfg) is True
    assert ingress_request_ok("172.30.32.2", "/x", cfg) is False
