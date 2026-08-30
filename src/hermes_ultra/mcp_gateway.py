from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol

from .delegated_identity import DelegatedIdentity
from .skill_lifecycle import LifecycleState

MCP_PROTOCOL_VERSION = "2026-07-28"
_HEADER_NAME_RE = re.compile(r"^[\x21-\x7e]+$")


class McpGatewayError(RuntimeError):
    pass


class McpTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        params: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class McpProvider:
    provider_id: str
    transport_type: str
    profiles: frozenset[str] = frozenset()
    state: LifecycleState = LifecycleState.CANDIDATE
    authorization_context: str = "default"

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id is required")
        if self.transport_type not in {"stdio", "streamable-http", "sse", "native"}:
            raise ValueError("unsupported MCP transport type")
        object.__setattr__(self, "profiles", frozenset(item.strip() for item in self.profiles if item.strip()))


@dataclass(frozen=True)
class McpServerDiscovery:
    provider_id: str
    supported_versions: tuple[str, ...]
    capabilities: Mapping[str, object]
    instructions: str | None = None
    server_info: Mapping[str, object] | None = None
    ttl_ms: int = 0
    cache_scope: str = "private"


@dataclass(frozen=True)
class McpToolDescriptor:
    provider_id: str
    name: str
    description: str = ""
    capabilities: frozenset[str] = frozenset()
    read_only: bool = False
    destructive: bool = False
    input_schema: Mapping[str, object] = field(default_factory=dict)
    header_params: tuple[tuple[tuple[str, ...], str, str], ...] = ()


@dataclass
class _Registration:
    provider: McpProvider
    transport: McpTransport


@dataclass
class _CacheEntry:
    value: object
    expires_at: float

    def valid(self, now: float) -> bool:
        return now < self.expires_at


class McpGateway:
    """MCP 2026-07-28 control plane with progressive tool exposure.

    Provider overrides widen profile visibility only. They never promote lifecycle
    state or widen a delegated identity's provider/capability grants.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        client_name: str = "hermes-ultra",
        client_version: str = "0.1.0",
    ) -> None:
        self._clock = clock
        self._client_name = client_name
        self._client_version = client_version
        self._registrations: dict[str, _Registration] = {}
        self._discover_public: dict[str, _CacheEntry] = {}
        self._discover_private: dict[tuple[str, str], _CacheEntry] = {}
        self._tools_public: dict[str, _CacheEntry] = {}
        self._tools_private: dict[tuple[str, str], _CacheEntry] = {}

    def register(self, provider: McpProvider, transport: McpTransport) -> None:
        if provider.provider_id in self._registrations:
            raise ValueError(f"MCP provider already registered: {provider.provider_id}")
        self._registrations[provider.provider_id] = _Registration(provider, transport)

    def provider(self, provider_id: str) -> McpProvider:
        try:
            return self._registrations[provider_id].provider
        except KeyError as exc:
            raise KeyError(f"unknown MCP provider: {provider_id}") from exc

    def discover(
        self,
        provider_id: str,
        *,
        identity: DelegatedIdentity | None = None,
        authorization_context: str | None = None,
        force: bool = False,
    ) -> McpServerDiscovery:
        registration = self._active_registration(provider_id)
        self._authorize_identity(registration.provider, identity)
        context = authorization_context or registration.provider.authorization_context
        if not force:
            cached = self._get_cache(provider_id, context, public=self._discover_public, private=self._discover_private)
            if cached is not None:
                return cached  # type: ignore[return-value]

        result = self._request(registration, "server/discover", identity=identity)
        versions = result.get("supportedVersions")
        capabilities = result.get("capabilities")
        if not isinstance(versions, list) or any(not isinstance(item, str) for item in versions):
            raise McpGatewayError("server/discover returned invalid supportedVersions")
        if MCP_PROTOCOL_VERSION not in versions:
            raise McpGatewayError(f"server does not support MCP {MCP_PROTOCOL_VERSION}")
        if not isinstance(capabilities, dict):
            raise McpGatewayError("server/discover returned invalid capabilities")
        meta = result.get("_meta")
        server_info = None
        if isinstance(meta, dict) and isinstance(meta.get("io.modelcontextprotocol/serverInfo"), dict):
            server_info = dict(meta["io.modelcontextprotocol/serverInfo"])
        ttl_ms, scope = self._cache_hints(result)
        value = McpServerDiscovery(
            provider_id=provider_id,
            supported_versions=tuple(versions),
            capabilities=dict(capabilities),
            instructions=result.get("instructions") if isinstance(result.get("instructions"), str) else None,
            server_info=server_info,
            ttl_ms=ttl_ms,
            cache_scope=scope,
        )
        self._put_cache(
            provider_id, context, value, ttl_ms=ttl_ms, scope=scope,
            public=self._discover_public, private=self._discover_private,
        )
        return value

    def refresh_tools(
        self,
        provider_id: str,
        *,
        identity: DelegatedIdentity | None = None,
        authorization_context: str | None = None,
        force: bool = False,
    ) -> tuple[McpToolDescriptor, ...]:
        registration = self._active_registration(provider_id)
        self._authorize_identity(registration.provider, identity)
        context = authorization_context or registration.provider.authorization_context
        if not force:
            cached = self._get_cache(provider_id, context, public=self._tools_public, private=self._tools_private)
            if cached is not None:
                return cached  # type: ignore[return-value]

        cursor: str | None = None
        descriptors: list[McpToolDescriptor] = []
        ttl_values: list[int] = []
        scopes: list[str] = []
        while True:
            params = {} if cursor is None else {"cursor": cursor}
            result = self._request(registration, "tools/list", identity=identity, extra_params=params)
            raw_tools = result.get("tools")
            if not isinstance(raw_tools, list):
                raise McpGatewayError("tools/list returned invalid tools")
            for raw in raw_tools:
                descriptor = self._parse_tool(provider_id, raw, registration.provider.transport_type)
                if descriptor is not None:
                    descriptors.append(descriptor)
            ttl_ms, scope = self._cache_hints(result)
            ttl_values.append(ttl_ms)
            scopes.append(scope)
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or not next_cursor:
                raise McpGatewayError("tools/list returned invalid nextCursor")
            cursor = next_cursor

        deduped = {item.name: item for item in descriptors}
        value = tuple(sorted(deduped.values(), key=lambda item: item.name))
        ttl_ms = min(ttl_values) if ttl_values and all(value > 0 for value in ttl_values) else 0
        scope = "public" if scopes and all(value == "public" for value in scopes) else "private"
        self._put_cache(
            provider_id, context, value, ttl_ms=ttl_ms, scope=scope,
            public=self._tools_public, private=self._tools_private,
        )
        return value

    def visible_tools(
        self,
        *,
        profile: str,
        capabilities: set[str] | frozenset[str] = frozenset(),
        provider_overrides: set[str] | frozenset[str] = frozenset(),
        identity: DelegatedIdentity | None = None,
        limit: int = 32,
    ) -> tuple[McpToolDescriptor, ...]:
        if limit <= 0:
            return ()
        requested = frozenset(item.strip() for item in capabilities if item.strip())
        overrides = frozenset(provider_overrides)
        visible: list[McpToolDescriptor] = []
        for provider_id in sorted(self._registrations):
            registration = self._registrations[provider_id]
            provider = registration.provider
            if provider.state is not LifecycleState.ACTIVE:
                continue
            if profile not in provider.profiles and provider_id not in overrides:
                continue
            self._authorize_identity(provider, identity, profile=profile)
            for tool in self.refresh_tools(provider_id, identity=identity):
                if identity is not None and not any(
                    self._grant_matches_tool(grant, tool.capabilities) for grant in identity.capabilities
                ):
                    continue
                if requested and not self._requested_matches_tool(requested, tool.capabilities):
                    continue
                visible.append(tool)
        visible.sort(
            key=lambda tool: (
                -sum(1 for request in requested if self._grant_matches_tool(request, tool.capabilities)),
                tool.provider_id,
                tool.name,
            )
        )
        return tuple(visible[:limit])

    def call_tool(
        self,
        provider_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        identity: DelegatedIdentity | None = None,
        authorization_context: str | None = None,
    ) -> Mapping[str, object]:
        registration = self._active_registration(provider_id)
        self._authorize_identity(registration.provider, identity)
        tools = self.refresh_tools(provider_id, identity=identity, authorization_context=authorization_context)
        tool = next((item for item in tools if item.name == tool_name), None)
        if tool is None:
            raise McpGatewayError(f"tool is not advertised by provider {provider_id}: {tool_name}")
        if identity is not None and not any(
            self._grant_matches_tool(grant, tool.capabilities) for grant in identity.capabilities
        ):
            raise PermissionError("delegated capability scope does not allow requested MCP tool")
        extra_headers = self._parameter_headers(tool, arguments) if registration.provider.transport_type == "streamable-http" else {}
        return self._request(
            registration,
            "tools/call",
            identity=identity,
            name=tool_name,
            extra_params={"name": tool_name, "arguments": dict(arguments)},
            extra_headers=extra_headers,
        )

    def _active_registration(self, provider_id: str) -> _Registration:
        try:
            registration = self._registrations[provider_id]
        except KeyError as exc:
            raise KeyError(f"unknown MCP provider: {provider_id}") from exc
        if registration.provider.state is not LifecycleState.ACTIVE:
            raise PermissionError(f"MCP provider is not active: {provider_id}")
        return registration

    @staticmethod
    def _authorize_identity(
        provider: McpProvider,
        identity: DelegatedIdentity | None,
        *,
        profile: str | None = None,
    ) -> None:
        if identity is None:
            return
        if identity.expired():
            raise PermissionError("delegated identity is expired")
        if provider.provider_id not in identity.providers:
            raise PermissionError("delegated provider scope does not allow requested MCP provider")
        if profile is not None and profile not in identity.profiles:
            raise PermissionError("delegated profile scope does not allow requested profile")

    def _request(
        self,
        registration: _Registration,
        method: str,
        *,
        identity: DelegatedIdentity | None,
        name: str | None = None,
        extra_params: Mapping[str, object] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, object]:
        meta: dict[str, object] = {
            "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
            "io.modelcontextprotocol/clientInfo": {"name": self._client_name, "version": self._client_version},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
        if identity is not None:
            meta.update(identity.to_mcp_meta())
        params = dict(extra_params or {})
        params["_meta"] = meta
        headers = {"MCP-Protocol-Version": MCP_PROTOCOL_VERSION, "Mcp-Method": method}
        if name is not None:
            headers["Mcp-Name"] = name
        if extra_headers:
            headers.update(extra_headers)
        response = registration.transport.request(method=method, params=params, headers=headers)
        if not isinstance(response, Mapping):
            raise McpGatewayError(f"{method} returned a non-object response")
        if response.get("error") is not None:
            raise McpGatewayError(f"{method} failed: {response['error']}")
        result = response.get("result", response)
        if not isinstance(result, Mapping):
            raise McpGatewayError(f"{method} returned an invalid result")
        return dict(result)

    @classmethod
    def _parse_tool(
        cls,
        provider_id: str,
        raw: object,
        transport_type: str,
    ) -> McpToolDescriptor | None:
        if not isinstance(raw, dict):
            return None
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            return None
        description = raw.get("description") if isinstance(raw.get("description"), str) else ""
        annotations = raw.get("annotations") if isinstance(raw.get("annotations"), dict) else {}
        input_schema = raw.get("inputSchema") if isinstance(raw.get("inputSchema"), dict) else {}
        try:
            header_params = cls._header_annotations(input_schema) if transport_type == "streamable-http" else ()
        except ValueError:
            return None
        capabilities = {name}
        capabilities.update(part for part in re.split(r"[._:/-]+", name) if part)
        meta = raw.get("_meta")
        if isinstance(meta, dict):
            extra = meta.get("com.hermes.ultra/capabilities")
            if isinstance(extra, list):
                capabilities.update(item.strip() for item in extra if isinstance(item, str) and item.strip())
        return McpToolDescriptor(
            provider_id=provider_id,
            name=name,
            description=description,
            capabilities=frozenset(capabilities),
            read_only=annotations.get("readOnlyHint") is True,
            destructive=annotations.get("destructiveHint") is True,
            input_schema=dict(input_schema),
            header_params=header_params,
        )

    @classmethod
    def _header_annotations(cls, schema: Mapping[str, object]) -> tuple[tuple[tuple[str, ...], str, str], ...]:
        found: list[tuple[tuple[str, ...], str, str]] = []
        names: set[str] = set()

        def walk(node: object, path: tuple[str, ...]) -> None:
            if not isinstance(node, Mapping):
                return
            properties = node.get("properties")
            if not isinstance(properties, Mapping):
                return
            for key, child in properties.items():
                if not isinstance(key, str) or not isinstance(child, Mapping):
                    continue
                current = (*path, key)
                header = child.get("x-mcp-header")
                if header is not None:
                    primitive = child.get("type")
                    if primitive not in {"string", "integer", "number", "boolean"}:
                        raise ValueError("x-mcp-header requires primitive parameter type")
                    if not isinstance(header, str) or not header or not _HEADER_NAME_RE.fullmatch(header) or " " in header or ":" in header:
                        raise ValueError("invalid x-mcp-header name")
                    lowered = header.lower()
                    if lowered in names:
                        raise ValueError("duplicate x-mcp-header name")
                    names.add(lowered)
                    found.append((current, header, str(primitive)))
                walk(child, current)

        walk(schema, ())
        return tuple(found)

    @classmethod
    def _parameter_headers(
        cls,
        tool: McpToolDescriptor,
        arguments: Mapping[str, object],
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        for path, header_name, primitive in tool.header_params:
            exists, value = cls._lookup(arguments, path)
            if not exists:
                continue
            if primitive == "boolean":
                if not isinstance(value, bool):
                    raise McpGatewayError(f"annotated MCP parameter {'.'.join(path)} must be boolean")
                text = "true" if value else "false"
            elif primitive == "integer":
                if not isinstance(value, int) or isinstance(value, bool):
                    raise McpGatewayError(f"annotated MCP parameter {'.'.join(path)} must be integer")
                text = str(value)
            elif primitive == "number":
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise McpGatewayError(f"annotated MCP parameter {'.'.join(path)} must be number")
                text = str(value)
            else:
                if not isinstance(value, str):
                    raise McpGatewayError(f"annotated MCP parameter {'.'.join(path)} must be string")
                text = value
            headers[f"Mcp-Param-{header_name}"] = cls._safe_header_value(text)
        return headers

    @staticmethod
    def _lookup(arguments: Mapping[str, object], path: tuple[str, ...]) -> tuple[bool, object | None]:
        current: object = arguments
        for part in path:
            if not isinstance(current, Mapping) or part not in current:
                return False, None
            current = current[part]
        return True, current

    @staticmethod
    def _safe_header_value(value: str) -> str:
        safe = value == value.strip() and all(0x20 <= ord(char) <= 0x7E and char not in "\r\n" for char in value)
        if safe:
            return value
        encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
        return f"=?base64?{encoded}?="

    @staticmethod
    def _cache_hints(result: Mapping[str, object]) -> tuple[int, str]:
        ttl_raw = result.get("ttlMs", 0)
        ttl_ms = int(ttl_raw) if isinstance(ttl_raw, int) and ttl_raw > 0 else 0
        scope = result.get("cacheScope")
        return ttl_ms, str(scope) if scope in {"public", "private"} else "private"

    def _get_cache(
        self,
        provider_id: str,
        context: str,
        *,
        public: dict[str, _CacheEntry],
        private: dict[tuple[str, str], _CacheEntry],
    ) -> object | None:
        now = self._clock()
        public_entry = public.get(provider_id)
        if public_entry is not None:
            if public_entry.valid(now):
                return public_entry.value
            public.pop(provider_id, None)
        key = (provider_id, context)
        private_entry = private.get(key)
        if private_entry is not None:
            if private_entry.valid(now):
                return private_entry.value
            private.pop(key, None)
        return None

    def _put_cache(
        self,
        provider_id: str,
        context: str,
        value: object,
        *,
        ttl_ms: int,
        scope: str,
        public: dict[str, _CacheEntry],
        private: dict[tuple[str, str], _CacheEntry],
    ) -> None:
        if ttl_ms <= 0:
            return
        entry = _CacheEntry(value=value, expires_at=self._clock() + ttl_ms / 1000.0)
        if scope == "public":
            public[provider_id] = entry
        else:
            private[(provider_id, context)] = entry

    @staticmethod
    def _grant_matches_tool(grant: str, tool_capabilities: frozenset[str]) -> bool:
        return any(
            capability == grant or capability.startswith(grant + ".")
            for capability in tool_capabilities
        )

    @classmethod
    def _requested_matches_tool(cls, requested: frozenset[str], tool_capabilities: frozenset[str]) -> bool:
        return any(cls._grant_matches_tool(item, tool_capabilities) for item in requested)
