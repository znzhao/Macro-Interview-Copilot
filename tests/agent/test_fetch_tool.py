"""SSRF containment tests for core.agent.tools.fetch. See docs/AI_SPEC.md #7.1
and docs/IMPLEMENTATION_GUIDE.md #5.3a.

No live network calls. Blocklist logic is tested as pure functions (no
sockets at all); HTTP-level behavior (redirects, size cap, content-type
filtering) is tested against a local stub server on 127.0.0.1, with the
loopback check patched to allow reaching *only* that stub server — every
other address, including a redirect target, is still checked for real.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from core.agent.errors import ToolBlocked
from core.agent.tools import fetch as fetch_module
from core.agent.tools.fetch import (
    FetchResult,
    _is_blocked,
    _validate_host,
    _validate_url,
    fetch_url,
)

# ── Pure blocklist logic — no network, no mocking ──────────────────────────


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.1",  # RFC1918
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",  # link-local, the cloud metadata endpoint
        "100.64.0.1",  # CGNAT
        "224.0.0.1",  # multicast
        "240.0.0.1",  # reserved
        "0.0.0.0",
        "192.0.2.1",  # TEST-NET-1
        "255.255.255.255",
    ],
)
def test_blocked_ipv4_addresses(ip: str) -> None:
    assert _is_blocked(ipaddress.ip_address(ip)) is True


@pytest.mark.parametrize(
    "ip",
    [
        "::1",  # loopback
        "fe80::1",  # link-local
        "fc00::1",  # unique local
        "ff02::1",  # multicast
        "::",  # unspecified
        "2001:db8::1",  # documentation
        "64:ff9b::a00:1",  # NAT64-mapped 10.0.0.1
    ],
)
def test_blocked_ipv6_addresses(ip: str) -> None:
    assert _is_blocked(ipaddress.ip_address(ip)) is True


def test_ipv4_mapped_ipv6_of_a_blocked_address_is_blocked() -> None:
    # ::ffff:10.0.0.1 — an IPv6-mapped view of a private IPv4 address. A
    # validator that only checks the IPv6 blocklist and misses the mapped
    # address is a real bypass.
    mapped = ipaddress.ip_address("::ffff:10.0.0.1")
    assert _is_blocked(mapped) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34"])
def test_public_addresses_are_not_blocked(ip: str) -> None:
    assert _is_blocked(ipaddress.ip_address(ip)) is False


@pytest.mark.parametrize(
    "scheme_url", ["file:///etc/passwd", "gopher://x", "data:text/plain,x", "ftp://x"]
)
def test_disallowed_scheme_rejected(scheme_url: str) -> None:
    with pytest.raises(ToolBlocked, match="scheme"):
        _validate_url(scheme_url)


def test_url_with_no_host_rejected() -> None:
    with pytest.raises(ToolBlocked, match="no host"):
        _validate_url("http:///path")


def test_validate_host_rejects_when_dns_resolves_to_a_blocked_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(host: str, *_a: object, **_k: object) -> list[tuple]:  # type: ignore[type-arg]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]

    monkeypatch.setattr(fetch_module.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ToolBlocked, match="non-public address"):
        _validate_host("attacker-controlled.example")


def test_validate_host_rejects_if_any_resolved_address_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host resolving to one public and one private address is refused
    outright rather than gambled on which address the connection actually
    uses.
    """

    def fake_getaddrinfo(host: str, *_a: object, **_k: object) -> list[tuple]:  # type: ignore[type-arg]
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80)),
        ]

    monkeypatch.setattr(fetch_module.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ToolBlocked):
        _validate_host("multi-homed.example")


def test_validate_host_allows_a_genuinely_public_address(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, *_a: object, **_k: object) -> list[tuple]:  # type: ignore[type-arg]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]

    monkeypatch.setattr(fetch_module.socket, "getaddrinfo", fake_getaddrinfo)
    _validate_host("example.com")  # does not raise


def test_dns_failure_is_blocked_not_crashed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, *_a: object, **_k: object) -> list[tuple]:  # type: ignore[type-arg]
        raise socket.gaierror("name resolution failed")

    monkeypatch.setattr(fetch_module.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ToolBlocked, match="could not resolve"):
        _validate_host("does-not-exist.invalid")


# NOTE on DNS rebinding (TOCTOU): _validate_host validates the addresses OUR
# OWN resolution returns, but httpx performs its own resolution again when it
# actually connects. A resolver that answers differently between those two
# lookups would slip past this check. Closing that fully needs a transport
# that pins the connection to the address already validated here, which this
# iteration does not implement — see the module docstring in
# core/agent/tools/fetch.py and PHASE_TRACKER.md. Not asserted as covered
# here because it genuinely isn't.


# ── HTTP-level behavior against a local stub server ────────────────────────


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:  # silence test output
        pass

    def do_GET(self) -> None:  # noqa: N802 - stdlib method name
        if self.path == "/normal":
            body = b"<html><head><title>Test Page</title></head><body>Hello world</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/big":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            chunk = b"x" * 65536
            for _ in range(40):  # 40 * 64KB = 2.5MB, over the 2MB cap
                self.wfile.write(chunk)
        elif self.path == "/wrong-content-type":
            body = b'{"not": "html"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redirect-once":
            self.send_response(302)
            self.send_header("Location", "/normal")
            self.end_headers()
        elif self.path.startswith("/redirect-chain-"):
            n = int(self.path.rsplit("-", 1)[1])
            self.send_response(302)
            target = "/normal" if n <= 0 else f"/redirect-chain-{n - 1}"
            self.send_header("Location", target)
            self.end_headers()
        elif self.path == "/redirect-to-metadata":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture(scope="module")
def stub_server() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture()
def allow_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass the loopback block ONLY for the local stub server, so HTTP-level
    behavior (redirects, caps, content-type) can be exercised without
    disabling SSRF protection for anything else in the same test run.
    """
    real_is_blocked = fetch_module._is_blocked

    def patched(addr: object) -> bool:
        if str(addr) in ("127.0.0.1", "::1"):
            return False
        return real_is_blocked(addr)  # type: ignore[arg-type]

    monkeypatch.setattr(fetch_module, "_is_blocked", patched)


def test_fetches_and_extracts_title_and_text(stub_server: str, allow_loopback: None) -> None:
    result = fetch_url(f"{stub_server}/normal")
    assert isinstance(result, FetchResult)
    assert result.title == "Test Page"
    assert "Hello world" in result.text
    assert not result.truncated


def test_oversized_response_is_truncated_not_unbounded(
    stub_server: str, allow_loopback: None
) -> None:
    result = fetch_url(f"{stub_server}/big")
    assert result.truncated is True
    assert len(result.text.encode("utf-8")) <= fetch_module._MAX_BYTES + 65536  # last chunk slack


def test_disallowed_content_type_is_blocked(stub_server: str, allow_loopback: None) -> None:
    with pytest.raises(ToolBlocked, match="content type"):
        fetch_url(f"{stub_server}/wrong-content-type")


def test_single_redirect_is_followed(stub_server: str, allow_loopback: None) -> None:
    result = fetch_url(f"{stub_server}/redirect-once")
    assert result.title == "Test Page"


def test_redirect_chain_within_limit_succeeds(stub_server: str, allow_loopback: None) -> None:
    # 3 hops -> /redirect-chain-2 -> -chain-1 -> -chain-0 -> /normal is 4 requests total,
    # i.e. 3 redirects, exactly at _MAX_REDIRECTS.
    result = fetch_url(f"{stub_server}/redirect-chain-2")
    assert result.title == "Test Page"


def test_redirect_chain_exceeding_limit_is_blocked(stub_server: str, allow_loopback: None) -> None:
    with pytest.raises(ToolBlocked, match="redirects"):
        fetch_url(f"{stub_server}/redirect-chain-5")


def test_redirect_to_a_blocked_address_is_caught_on_the_hop(
    stub_server: str, allow_loopback: None
) -> None:
    """The classic bypass: a permitted URL redirects to an internal address.
    allow_loopback only special-cases 127.0.0.1/::1 — the metadata address
    this redirects to is still checked for real.
    """
    with pytest.raises(ToolBlocked, match="non-public address"):
        fetch_url(f"{stub_server}/redirect-to-metadata")


def test_loopback_is_blocked_without_the_bypass_fixture(stub_server: str) -> None:
    # No allow_loopback fixture here — proves the bypass in other tests is
    # doing real work, not that the check is broken.
    with pytest.raises(ToolBlocked, match="non-public address"):
        fetch_url(f"{stub_server}/normal")
