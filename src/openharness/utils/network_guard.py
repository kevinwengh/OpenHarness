"""HTTP target validation helpers for outbound web tools.

Integration: This module participates in the shared OpenHarness runtime.

Event loop: Coroutines and async generators execute on their caller's loop; preserve
cancellation, ordering, task ownership, bounded synchronous work, and cleanup of every acquired
resource.

Change safety: Preserve public contracts, state ownership, error behavior, and resource cleanup.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from enum import Enum
from urllib.parse import ParseResult, urljoin, urlparse

import httpx


_DEFAULT_PORTS = {
    "http": 80,
    "https": 443,
}
_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
_SYNTHETIC_DNS_CIDRS_SETTING = "web.synthetic_dns_cidrs"
_RESOLUTION_MODE_SETTING = "web.resolution_mode"
_PROXY_SETTING = "web.proxy"
_LOCAL_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
}
_LOCAL_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".localdomain",
    ".internal",
    ".cluster.local",
)


class ResolutionMode(str, Enum):
    """How outbound web tools should interpret target DNS resolution.

    Integration: Constructed or referenced by ``get_web_resolution_mode``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve persisted and wire-visible values or provide an explicit migration
    for stored configuration and messages.
    """

    AUTO = "auto"
    DIRECT = "direct"
    PROXY = "proxy"
    SYNTHETIC_DNS = "synthetic_dns"


class NetworkGuardError(ValueError):
    """Raised when an outbound HTTP target violates security policy.

    Integration: Constructed or referenced by ``validate_http_url``,
    ``get_web_resolution_mode``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """


def validate_http_url(url: str) -> None:
    """Validate basic HTTP/HTTPS URL syntax.

    Integration: Called by ``_validate_url``, ``fetch_public_http_response`` and collaborates
    with ``urlparse``, ``NetworkGuardError``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise NetworkGuardError("only http and https URLs are allowed")
    if not parsed.netloc or not parsed.hostname:
        raise NetworkGuardError("URL must include a host")
    if parsed.username or parsed.password:
        raise NetworkGuardError("URLs with embedded credentials are not allowed")


def get_web_resolution_mode(
    proxy: str | None = None,
    *,
    configured_mode: str | None = None,
) -> ResolutionMode:
    """Resolve the configured web target validation mode.

    Integration: Called by ``fetch_public_http_response`` and collaborates with ``replace``,
    ``ResolutionMode``, ``NetworkGuardError``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract; preserve
    exception and fallback behavior expected by callers.
    """
    raw_mode = (configured_mode or "").strip().lower().replace("-", "_")
    if not raw_mode or raw_mode == ResolutionMode.AUTO.value:
        return ResolutionMode.PROXY if proxy else ResolutionMode.DIRECT
    try:
        mode = ResolutionMode(raw_mode)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in ResolutionMode)
        raise NetworkGuardError(f"{_RESOLUTION_MODE_SETTING} must be one of: {allowed}") from exc
    if mode is ResolutionMode.AUTO:
        return ResolutionMode.PROXY if proxy else ResolutionMode.DIRECT
    if mode is ResolutionMode.PROXY and not proxy:
        raise NetworkGuardError(f"{_RESOLUTION_MODE_SETTING}=proxy requires {_PROXY_SETTING}")
    return mode


def parse_synthetic_dns_cidrs(value: str | None = None) -> tuple[_IPNetwork, ...]:
    """Parse user-declared synthetic DNS CIDRs.

    Integration: Called by ``fetch_public_http_response`` and collaborates with ``entry.strip``,
    ``raw_value.split``, ``networks.append``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    raw_value = "" if value is None else value
    entries = [entry.strip() for entry in raw_value.split(",") if entry.strip()]
    networks: list[_IPNetwork] = []
    for entry in entries:
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError as exc:
            raise NetworkGuardError(f"invalid {_SYNTHETIC_DNS_CIDRS_SETTING} entry: {entry}") from exc
    return tuple(networks)


async def ensure_public_http_url(url: str) -> None:
    """Reject loopback, private-network, and other non-public HTTP targets.

    Integration: Called by ``ensure_http_url_allowed`` and collaborates with
    ``_validated_parsed_http_url``, ``_normalized_hostname``, ``_parse_ip_literal``.

    Event loop: This coroutine awaits collaborators on the caller's loop and must avoid blocking
    I/O; retain lock scope and release behavior.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    parsed = _validated_parsed_http_url(url)
    hostname = _normalized_hostname(parsed.hostname)
    literal = _parse_ip_literal(hostname)
    if literal is not None:
        _ensure_global_literal_ip(literal)
        return
    _ensure_not_local_hostname(hostname)
    port = parsed.port or _DEFAULT_PORTS[parsed.scheme]
    addresses = await _resolve_host_addresses(hostname, port)
    if not addresses:
        raise NetworkGuardError(f"target host did not resolve: {hostname}")

    blocked = sorted({str(address) for address in addresses if not address.is_global})
    if blocked:
        raise NetworkGuardError(_format_blocked_addresses(blocked, include_synthetic_dns_hint=True))


async def ensure_http_url_allowed(
    url: str,
    *,
    mode: ResolutionMode,
    synthetic_cidrs: tuple[_IPNetwork, ...] = (),
) -> None:
    """Validate one outbound URL according to the configured resolution mode.

    Integration: Called by ``fetch_public_http_response`` and collaborates with
    ``_ensure_proxy_safe_http_url``, ``_ensure_synthetic_dns_safe_http_url``,
    ``ensure_public_http_url``.

    Event loop: This coroutine awaits collaborators on the caller's loop and must avoid blocking
    I/O.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    if mode is ResolutionMode.DIRECT:
        await ensure_public_http_url(url)
        return
    if mode is ResolutionMode.PROXY:
        _ensure_proxy_safe_http_url(url)
        return
    await _ensure_synthetic_dns_safe_http_url(url, synthetic_cidrs=synthetic_cidrs)


async def fetch_public_http_response(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    timeout: float = 15.0,
    max_redirects: int = 5,
    proxy: str | None = None,
) -> httpx.Response:
    """Fetch one HTTP resource while validating every redirect hop.

    Integration: Called by ``WebFetchTool.execute``, ``WebSearchTool.execute`` and collaborates
    with ``_load_configured_web_settings``, ``get_web_resolution_mode``, ``NetworkGuardError``.

    Event loop: This coroutine awaits collaborators on the caller's loop and must avoid blocking
    I/O.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    current_url = url
    current_params = params

    web_settings = _load_configured_web_settings()
    resolved_proxy = proxy if proxy is not None else web_settings.proxy
    if resolved_proxy:
        validate_http_url(resolved_proxy)
    mode = get_web_resolution_mode(
        resolved_proxy,
        configured_mode=web_settings.resolution_mode,
    )
    synthetic_cidrs = (
        parse_synthetic_dns_cidrs(",".join(web_settings.synthetic_dns_cidrs))
        if mode is ResolutionMode.SYNTHETIC_DNS
        else ()
    )

    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=timeout,
        trust_env=False,
        proxy=resolved_proxy,
    ) as client:
        for redirect_count in range(max_redirects + 1):
            await ensure_http_url_allowed(
                current_url,
                mode=mode,
                synthetic_cidrs=synthetic_cidrs,
            )
            response = await client.get(
                current_url,
                params=current_params,
                headers=headers,
            )
            if not response.has_redirect_location:
                return response

            location = response.headers.get("location")
            if not location:
                return response
            if redirect_count >= max_redirects:
                raise NetworkGuardError(f"too many redirects (>{max_redirects})")

            current_url = urljoin(str(response.url), location)
            current_params = None

    raise NetworkGuardError("request failed before receiving a response")


class _ConfiguredWebSettings:
    """Coordinate the configured web settings responsibilities for this subsystem.

    Integration: Constructed or referenced by ``_load_configured_web_settings``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """
    def __init__(
        self,
        *,
        proxy: str | None,
        resolution_mode: str,
        synthetic_dns_cidrs: list[str],
    ) -> None:
        """Initialize ``_ConfiguredWebSettings`` and bind its runtime dependencies.

        Integration: Exposed through ``_ConfiguredWebSettings``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.proxy = proxy
        self.resolution_mode = resolution_mode
        self.synthetic_dns_cidrs = synthetic_dns_cidrs


def _load_configured_web_settings() -> _ConfiguredWebSettings:
    """Load persisted web settings, including environment overrides.

    Integration: Called by ``fetch_public_http_response`` and collaborates with
    ``_ConfiguredWebSettings``, ``load_settings``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    from openharness.config import load_settings

    web = load_settings().web
    return _ConfiguredWebSettings(
        proxy=web.proxy,
        resolution_mode=web.resolution_mode,
        synthetic_dns_cidrs=list(web.synthetic_dns_cidrs),
    )


def _ensure_proxy_safe_http_url(url: str) -> None:
    """Validate a URL whose hostname will be resolved by an explicit proxy.

    Integration: Called by ``ensure_http_url_allowed`` and collaborates with
    ``_validated_parsed_http_url``, ``_normalized_hostname``, ``_parse_ip_literal``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    parsed = _validated_parsed_http_url(url)
    hostname = _normalized_hostname(parsed.hostname)
    literal = _parse_ip_literal(hostname)
    if literal is not None:
        _ensure_global_literal_ip(literal)
        return
    _ensure_not_local_hostname(hostname)


async def _ensure_synthetic_dns_safe_http_url(
    url: str,
    *,
    synthetic_cidrs: tuple[_IPNetwork, ...],
) -> None:
    """Validate a URL in a user-declared synthetic DNS environment.

    Integration: Called by ``ensure_http_url_allowed`` and collaborates with
    ``_validated_parsed_http_url``, ``_normalized_hostname``, ``_parse_ip_literal``.

    Event loop: This coroutine awaits collaborators on the caller's loop and must avoid blocking
    I/O; retain lock scope and release behavior.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if not synthetic_cidrs:
        raise NetworkGuardError(
            f"{ResolutionMode.SYNTHETIC_DNS.value} mode requires {_SYNTHETIC_DNS_CIDRS_SETTING}"
        )
    parsed = _validated_parsed_http_url(url)
    hostname = _normalized_hostname(parsed.hostname)
    literal = _parse_ip_literal(hostname)
    if literal is not None:
        _ensure_global_literal_ip(literal)
        return
    _ensure_not_local_hostname(hostname)
    port = parsed.port or _DEFAULT_PORTS[parsed.scheme]
    addresses = await _resolve_host_addresses(hostname, port)
    if not addresses:
        raise NetworkGuardError(f"target host did not resolve: {hostname}")

    blocked = sorted(
        {
            str(address)
            for address in addresses
            if not address.is_global and not _address_in_networks(address, synthetic_cidrs)
        }
    )
    if blocked:
        raise NetworkGuardError(_format_blocked_addresses(blocked))


async def _resolve_host_addresses(host: str, port: int) -> set[_IPAddress]:
    """Resolve a host into concrete IP addresses.

    Integration: Called by ``ensure_public_http_url``, ``_ensure_synthetic_dns_safe_http_url``
    and collaborates with ``_parse_ip_literal``, ``asyncio.to_thread``, ``NetworkGuardError``.

    Event loop: This coroutine coordinates child tasks; preserve cancellation, completion, and
    exception ownership.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    literal = _parse_ip_literal(host)
    if literal is not None:
        return {literal}

    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo,
            host,
            port,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise NetworkGuardError(f"could not resolve target host {host}: {exc}") from exc

    addresses: set[_IPAddress] = set()
    for family, _, _, _, sockaddr in infos:
        if family == socket.AF_INET:
            candidate = sockaddr[0]
        elif family == socket.AF_INET6:
            candidate = sockaddr[0]
        else:
            continue
        if not isinstance(candidate, str):
            continue
        parsed = _parse_ip_literal(candidate)
        if parsed is not None:
            addresses.add(parsed)
    return addresses


def _parse_ip_literal(value: str) -> _IPAddress | None:
    """Parse ip literal for the enclosing subsystem.

    Integration: Called by ``ensure_public_http_url``, ``_ensure_proxy_safe_http_url`` and
    collaborates with ``ipaddress.ip_address``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _validated_parsed_http_url(url: str) -> ParseResult:
    """Derive validated parsed http URL from the current inputs and subsystem state.

    Integration: Called by ``ensure_public_http_url``, ``_ensure_proxy_safe_http_url`` and
    collaborates with ``validate_http_url``, ``urlparse``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    validate_http_url(url)
    parsed = urlparse(url)
    assert parsed.hostname is not None  # covered by validate_http_url
    return parsed


def _normalized_hostname(hostname: str | None) -> str:
    """Derive normalized hostname from the current inputs and subsystem state.

    Integration: Called by ``ensure_public_http_url``, ``_ensure_proxy_safe_http_url`` and
    collaborates with ``lower``, ``hostname.rstrip``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    assert hostname is not None  # covered by validate_http_url
    return hostname.rstrip(".").lower()


def _ensure_global_literal_ip(address: _IPAddress) -> None:
    """Ensure global literal ip for the enclosing subsystem.

    Integration: Called by ``ensure_public_http_url``, ``_ensure_proxy_safe_http_url`` and
    collaborates with ``NetworkGuardError``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if not address.is_global:
        raise NetworkGuardError(f"target resolves to non-public address(es): {address}")


def _ensure_not_local_hostname(hostname: str) -> None:
    """Ensure not local hostname for the enclosing subsystem.

    Integration: Called by ``ensure_public_http_url``, ``_ensure_proxy_safe_http_url`` and
    collaborates with ``any``, ``NetworkGuardError``, ``hostname.endswith``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve exception and fallback behavior expected by callers.
    """
    if hostname in _LOCAL_HOSTNAMES or any(hostname.endswith(suffix) for suffix in _LOCAL_HOST_SUFFIXES):
        raise NetworkGuardError(f"local hostnames are not allowed: {hostname}")
    if "." not in hostname:
        raise NetworkGuardError(f"single-label hostnames are not allowed: {hostname}")


def _address_in_networks(address: _IPAddress, networks: tuple[_IPNetwork, ...]) -> bool:
    """Determine whether address in networks holds for the current inputs.

    Integration: Called by ``_ensure_synthetic_dns_safe_http_url`` and collaborates with
    ``any``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    return any(address.version == network.version and address in network for network in networks)


def _format_blocked_addresses(
    blocked: list[str],
    *,
    include_synthetic_dns_hint: bool = False,
) -> str:
    """Format blocked addresses for the enclosing subsystem.

    Integration: Called by ``ensure_public_http_url``, ``_ensure_synthetic_dns_safe_http_url``
    and collaborates with ``join``.

    Event loop: Async callers invoke this synchronous helper inline, so keep its work bounded
    and non-blocking.

    Change safety: Preserve the signature, return value, and side-effect contract expected by
    callers.
    """
    rendered = ", ".join(blocked[:3])
    if len(blocked) > 3:
        rendered += ", ..."
    message = f"target resolves to non-public address(es): {rendered}"
    if include_synthetic_dns_hint:
        message += (
            "; if this domain intentionally resolves through synthetic DNS, configure "
            "web.resolution_mode=synthetic_dns and web.synthetic_dns_cidrs=<cidr>"
        )
    return message
