#!/usr/bin/env python3
"""Fail-closed public HTTP(S) fetcher for Hermes Agent Reach.

This helper intentionally ignores proxy environment variables, resolves every
redirect itself, rejects any non-public address, pins the connection to an
approved resolved address, restricts ports to 80/443, and bounds redirects,
time, and response size.
"""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import sys
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import SplitResult, urljoin, urlsplit

MAX_URL_LENGTH = 4096
MAX_REDIRECTS = 5
MAX_BYTES = 2 * 1024 * 1024
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 10.0
REDIRECT_CODES = {301, 302, 303, 307, 308}
TEXTUAL_TYPES = {
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/rss+xml",
    "application/atom+xml",
    "application/javascript",
    "application/ld+json",
}


class FetchPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    url: str
    parsed: SplitResult
    host: str
    port: int


def _public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return bool(address.is_global)


def validate_target(url: str) -> Target:
    if not isinstance(url, str) or not url:
        raise FetchPolicyError("URL is required")
    if len(url) > MAX_URL_LENGTH:
        raise FetchPolicyError("URL is too long")
    if "\\" in url:
        raise FetchPolicyError("backslashes are blocked in URLs")

    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise FetchPolicyError(f"invalid URL: {exc}") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise FetchPolicyError("only http(s) URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise FetchPolicyError("embedded URL credentials are blocked")
    if not parsed.hostname:
        raise FetchPolicyError("URL hostname is required")

    host = parsed.hostname.rstrip(".").lower()
    if not host:
        raise FetchPolicyError("URL hostname is required")
    if host == "localhost" or host.endswith(".localhost"):
        raise FetchPolicyError("localhost targets are blocked")
    if "%" in host:
        raise FetchPolicyError("scoped IP literals are blocked")

    try:
        port = parsed.port
    except ValueError as exc:
        raise FetchPolicyError(f"invalid URL port: {exc}") from exc
    default_port = 443 if scheme == "https" else 80
    if port is None:
        port = default_port
    if port != default_port:
        raise FetchPolicyError(f"nonstandard port {port} is blocked")

    return Target(url=url, parsed=parsed, host=host, port=port)


def resolve_public_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        if not literal.is_global:
            raise FetchPolicyError(f"blocked non-public address: {literal}")
        return (str(literal),)

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise FetchPolicyError(f"DNS resolution failed: {exc}") from exc

    addresses: list[str] = []
    for info in infos:
        raw = str(info[4][0]).split("%", 1)[0]
        if raw not in addresses:
            addresses.append(raw)
    if not addresses:
        raise FetchPolicyError("DNS resolution returned no addresses")
    blocked = [addr for addr in addresses if not _public_ip(addr)]
    if blocked:
        raise FetchPolicyError("blocked non-public address: " + ", ".join(blocked))
    return tuple(addresses)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, connect_ip: str) -> None:
        super().__init__(host=host, port=port, timeout=READ_TIMEOUT)
        self._connect_ip = connect_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._connect_ip, self.port), CONNECT_TIMEOUT)
        self.sock.settimeout(READ_TIMEOUT)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, connect_ip: str) -> None:
        context = ssl.create_default_context()
        super().__init__(host=host, port=port, timeout=READ_TIMEOUT, context=context)
        self._connect_ip = connect_ip

    def connect(self) -> None:
        raw = socket.create_connection((self._connect_ip, self.port), CONNECT_TIMEOUT)
        raw.settimeout(READ_TIMEOUT)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def _request_path(parsed: SplitResult) -> str:
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return path


def _is_textual_content_type(value: str | None) -> bool:
    if not value:
        return True
    media_type = value.split(";", 1)[0].strip().lower()
    return media_type.startswith("text/") or media_type in TEXTUAL_TYPES or media_type.endswith("+json") or media_type.endswith("+xml")


def _fetch_once(target: Target) -> tuple[int, dict[str, str], bytes]:
    addresses = resolve_public_addresses(target.host, target.port)
    last_error: BaseException | None = None
    for address in addresses:
        connection: http.client.HTTPConnection
        if target.parsed.scheme.lower() == "https":
            connection = _PinnedHTTPSConnection(target.host, target.port, address)
        else:
            connection = _PinnedHTTPConnection(target.host, target.port, address)
        try:
            connection.request(
                "GET",
                _request_path(target.parsed),
                headers={
                    "Host": target.host,
                    "User-Agent": "Mozilla/5.0 Hermes-Agent-Reach/2.0",
                    "Accept": "text/html,application/xhtml+xml,application/json,application/xml,text/plain,*/*;q=0.2",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            headers = {key.lower(): value for key, value in response.getheaders()}
            length_header = headers.get("content-length")
            if length_header:
                try:
                    declared = int(length_header)
                except ValueError:
                    declared = -1
                if declared > MAX_BYTES:
                    raise FetchPolicyError(f"response exceeds {MAX_BYTES} byte limit")
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise FetchPolicyError(f"response exceeds {MAX_BYTES} byte limit")
            return response.status, headers, body
        except FetchPolicyError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            last_error = exc
        finally:
            connection.close()
    raise FetchPolicyError(f"connection failed: {last_error}")


def fetch_public(url: str) -> bytes:
    current = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        target = validate_target(current)
        status, headers, body = _fetch_once(target)
        if status in REDIRECT_CODES:
            if redirect_count >= MAX_REDIRECTS:
                raise FetchPolicyError("redirect limit exceeded")
            location = headers.get("location")
            if not location:
                raise FetchPolicyError("redirect response missing Location header")
            current = urljoin(current, location)
            continue
        if status < 200 or status >= 300:
            raise FetchPolicyError(f"HTTP status {status}")
        if not _is_textual_content_type(headers.get("content-type")):
            raise FetchPolicyError("non-text response type is blocked")
        return body
    raise FetchPolicyError("redirect limit exceeded")


def main(argv: Iterable[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) != 1:
        print("usage: agent-reach-safe-fetch.py <url>", file=sys.stderr)
        return 2
    try:
        body = fetch_public(args[0])
    except FetchPolicyError as exc:
        print(f"Agent Reach read blocked: {exc}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
