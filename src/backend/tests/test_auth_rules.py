from naiad.auth_rules import forward_header_ok, referer_matches
from naiad.config import ForwardHeaderConfig


def test_forward_header_requires_header() -> None:
    assert forward_header_ok("", "1.2.3.4", ForwardHeaderConfig()) is False
    assert forward_header_ok("alice", "1.2.3.4", ForwardHeaderConfig()) is True


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
