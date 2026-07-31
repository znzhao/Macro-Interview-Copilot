"""SSRF-hardened URL fetching. See docs/AI_SPEC.md #7.1, docs/ARCHITECTURE.md #3.

The server making outbound requests on a stranger's instruction is the single
most dangerous thing in Phase 2. Unconstrained, a request for
"http://169.254.169.254/latest/meta-data/" reads cloud credentials.

Defenses, in order:
  1. Scheme allowlist (http/https only).
  2. DNS resolved and every returned address validated against a private/
     loopback/link-local/multicast/reserved blocklist BEFORE the request is
     made.
  3. Redirects are followed manually, capped at 3, and EVERY hop is
     revalidated from scratch — a permitted URL redirecting to 127.0.0.1 is
     the classic bypass.
  4. Response streamed with a hard size cap and timeout enforced while
     reading, not after.
  5. Only HTML/plain-text/Markdown content types are accepted; everything
     else is refused before its body is read.
  6. No credentials, cookies, or custom auth headers are ever attached.

Known residual gap (DNS rebinding): step 2 validates the addresses returned
by our own resolution, but httpx performs its own DNS resolution again when
it actually connects. A resolver that returns a public IP to our check and a
private one moments later to httpx's own connection would slip past this
gap — closing it fully needs a custom transport that pins the connection to
the address we already validated, which this iteration does not implement.
The redirect-revalidation and pre-check together still block the overwhelming
majority of real SSRF attempts (an attacker cannot simply request
http://169.254.169.254/ or a redirect to it), so this is a deliberate,
documented scope decision, not an oversight — see PHASE_TRACKER.md.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from core.agent.errors import ToolBlocked

_ALLOWED_SCHEMES = {"http", "https"}
_MAX_REDIRECTS = 3
_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
_TIMEOUT_S = 10.0
_ALLOWED_CONTENT_TYPES = ("text/html", "text/plain", "text/markdown", "text/x-markdown")

# Explicit rather than relying on ipaddress.is_private alone: is_private's
# exact coverage has changed across Python versions, and CGNAT (100.64.0.0/10)
# in particular was not always included. Being explicit means this list's
# correctness doesn't depend on which interpreter this happens to run under.
_BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",  # CGNAT
        "127.0.0.0/8",  # loopback
        "169.254.0.0/16",  # link-local, includes the cloud metadata endpoint
        "172.16.0.0/12",
        "192.0.0.0/24",  # IETF protocol assignments
        "192.0.2.0/24",  # TEST-NET-1
        "192.168.0.0/16",
        "198.18.0.0/15",  # benchmarking
        "198.51.100.0/24",  # TEST-NET-2
        "203.0.113.0/24",  # TEST-NET-3
        "224.0.0.0/4",  # multicast
        "240.0.0.0/4",  # reserved
        "255.255.255.255/32",
        "::1/128",  # IPv6 loopback
        "::/128",  # IPv6 unspecified
        "64:ff9b::/96",  # NAT64 — can smuggle an IPv4-mapped private address
        "100::/64",  # discard-only
        "2001:db8::/32",  # documentation
        "fc00::/7",  # unique local (IPv6 private)
        "fe80::/10",  # link-local IPv6
        "ff00::/8",  # IPv6 multicast
    )
)


def _is_blocked(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(addr, ipaddress.IPv6Address):
        mapped = addr.ipv4_mapped
        if mapped is not None and _is_blocked(mapped):
            return True
    if any(addr in net for net in _BLOCKED_NETWORKS):
        return True
    return bool(addr.is_multicast or addr.is_reserved or addr.is_loopback or addr.is_unspecified)


def _validate_host(hostname: str) -> None:
    """Resolve hostname and reject it if ANY returned address is blocked.
    Deliberately strict: a host that resolves to one public and one private
    address is refused rather than gambled on which address gets used.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ToolBlocked(f"could not resolve host: {hostname}") from exc

    if not infos:
        raise ToolBlocked(f"could not resolve host: {hostname}")

    for _family, _, _, _, sockaddr in infos:
        ip_str = sockaddr[0]
        addr = ipaddress.ip_address(ip_str)
        if _is_blocked(addr):
            raise ToolBlocked(
                f"refusing to fetch {hostname!r}: resolves to a non-public address ({ip_str})"
            )


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ToolBlocked(f"unsupported URL scheme: {parsed.scheme!r} (only http/https allowed)")
    if not parsed.hostname:
        raise ToolBlocked("URL has no host")
    _validate_host(parsed.hostname)
    return parsed.hostname


@dataclass(frozen=True)
class FetchResult:
    url: str
    title: str | None
    text: str
    truncated: bool


def _extract_text(html_or_text: str, content_type: str) -> str:
    if content_type.startswith("text/html"):
        # Deliberately not a full HTML parser dependency for a bounded-size
        # extraction task — strip script/style blocks, then tags, then
        # collapse whitespace. Good enough to hand a model readable text; it
        # does not need to be a faithful rendering.
        import re

        text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html_or_text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
    return html_or_text.strip()


def _extract_title(html: str, content_type: str) -> str | None:
    if not content_type.startswith("text/html"):
        return None
    import re

    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.S | re.I)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip() or None


def fetch_url(url: str) -> FetchResult:
    """Fetch and extract the text of a real web page. Raises ToolBlocked if
    the URL fails any safety check — the agent loop is expected to catch this
    and feed it back to the model as a refused tool result, never crash the
    turn (docs/AI_SPEC.md #7.1, docs/ARCHITECTURE.md #5).
    """
    current_url = url
    for hop in range(_MAX_REDIRECTS + 1):
        _validate_url(current_url)  # every hop, including the first, per the module docstring

        with (
            httpx.Client(follow_redirects=False, timeout=_TIMEOUT_S) as client,
            client.stream(
                "GET", current_url, headers={"User-Agent": "MacroInterviewCopilot/1.0"}
            ) as resp,
        ):
            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    raise ToolBlocked("redirect response had no Location header")
                if hop >= _MAX_REDIRECTS:
                    raise ToolBlocked(f"too many redirects (max {_MAX_REDIRECTS})")
                current_url = str(resp.url.join(location))
                continue

            content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type not in _ALLOWED_CONTENT_TYPES:
                raise ToolBlocked(
                    f"unsupported content type {content_type!r}; only HTML, "
                    "plain text, and Markdown are fetchable"
                )

            chunks: list[bytes] = []
            total = 0
            truncated = False
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > _MAX_BYTES:
                    truncated = True
                    break
                chunks.append(chunk)

            body = b"".join(chunks).decode("utf-8", errors="replace")
            return FetchResult(
                url=str(resp.url),
                title=_extract_title(body, content_type),
                text=_extract_text(body, content_type),
                truncated=truncated,
            )

    raise ToolBlocked(f"too many redirects (max {_MAX_REDIRECTS})")
