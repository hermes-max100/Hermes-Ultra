from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from .skill_lifecycle import (
    AuthorityProfile,
    CapabilityDescriptor,
    LifecycleState,
    Provenance,
    SkillCandidate,
)

PLUGIN_SCHEMA_1_0 = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA_1_0 = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
_NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_ALLOWED_MANIFEST_FIELDS = {
    "$schema", "name", "version", "description", "author", "homepage",
    "repository", "license", "keywords", "extensions",
}


class AgentPluginError(ValueError):
    pass


@dataclass(frozen=True)
class AgentPluginSkill:
    name: str
    path: Path


@dataclass(frozen=True)
class AgentPluginMcpServer:
    name: str
    transport_type: str
    config: Mapping[str, object]


@dataclass(frozen=True)
class AgentPluginPackage:
    root: Path
    manifest: Mapping[str, object]
    skills: tuple[AgentPluginSkill, ...] = ()
    mcp_servers: tuple[AgentPluginMcpServer, ...] = ()
    warnings: tuple[str, ...] = ()


class AgentPluginLoader:
    """Offline Agent Plugins 1.0.0 loader with spec failure boundaries.

    The loader validates recognized fields locally and never retrieves remote schemas.
    Component failures are isolated; only a fatal manifest failure rejects the package.
    """

    def load(self, root: str | Path) -> AgentPluginPackage:
        plugin_root = Path(root).resolve()
        if not plugin_root.is_dir():
            raise AgentPluginError("plugin root must be a directory")
        manifest_path = plugin_root / "plugin.json"
        if not manifest_path.exists():
            raise AgentPluginError("plugin.json is required")
        if not self._contained(plugin_root, manifest_path):
            raise AgentPluginError("plugin.json must resolve within plugin root")
        if not manifest_path.resolve().is_file():
            raise AgentPluginError("plugin.json must be a regular file")

        manifest = self._read_object(manifest_path, fatal="plugin.json must contain a JSON object")
        self._validate_manifest(manifest)
        warnings: list[str] = []
        unknown = sorted(set(manifest) - _ALLOWED_MANIFEST_FIELDS)
        warnings.extend(f"ignored unknown plugin.json field: {field}" for field in unknown)
        if "extensions" in manifest and not isinstance(manifest.get("extensions"), dict):
            warnings.append("ignored non-object plugin.json extensions")

        skills = self._load_skills(plugin_root, warnings)
        servers = self._load_mcp(plugin_root, manifest, warnings)
        return AgentPluginPackage(
            root=plugin_root,
            manifest=dict(manifest),
            skills=skills,
            mcp_servers=servers,
            warnings=tuple(warnings),
        )

    def to_candidate(self, package: AgentPluginPackage, *, provenance: Provenance) -> SkillCandidate:
        capabilities = {"agent-plugin"}
        tools = {f"skill:{item.name}" for item in package.skills}
        tools.update(f"mcp:{item.name}" for item in package.mcp_servers)
        network = any(item.transport_type in {"streamable-http", "sse"} for item in package.mcp_servers)
        shell = any(item.transport_type == "stdio" for item in package.mcp_servers)
        name = str(package.manifest["name"])
        return SkillCandidate(
            candidate_id=f"agent-plugin:{name}",
            name=name,
            provenance=provenance,
            authority=AuthorityProfile(network=network, filesystem_read=True, shell=shell),
            capability=CapabilityDescriptor(
                capability_id=name,
                capabilities=frozenset(capabilities),
                tools=frozenset(tools),
                outputs=frozenset({"agent-plugin-package"}),
            ),
            state=LifecycleState.CANDIDATE,
        )

    def export(self, package: AgentPluginPackage, destination: str | Path) -> Path:
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=False)
        manifest = {key: value for key, value in package.manifest.items() if key in _ALLOWED_MANIFEST_FIELDS}
        manifest["$schema"] = PLUGIN_SCHEMA_1_0
        (target / "plugin.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if package.skills:
            skills_dir = target / "skills"
            skills_dir.mkdir()
            for skill in package.skills:
                out = skills_dir / skill.name
                out.mkdir()
                (out / "SKILL.md").write_text(skill.path.read_text(encoding="utf-8"), encoding="utf-8")
        if package.mcp_servers:
            payload = {
                "$schema": MCP_SCHEMA_1_0,
                "mcpServers": {item.name: dict(item.config) for item in package.mcp_servers},
            }
            (target / "mcp.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return target

    def _load_skills(self, root: Path, warnings: list[str]) -> tuple[AgentPluginSkill, ...]:
        skills_dir = root / "skills"
        if not skills_dir.exists():
            return ()
        if not self._contained(root, skills_dir) or not skills_dir.resolve().is_dir():
            warnings.append("skills component invalid: skills/ must resolve to a directory inside plugin root")
            return ()
        skills: list[AgentPluginSkill] = []
        for child in sorted(skills_dir.iterdir(), key=lambda item: item.name):
            skill_file = child / "SKILL.md"
            if not child.is_dir() or not skill_file.exists():
                continue
            if not self._contained(root, skill_file) or not skill_file.resolve().is_file():
                warnings.append(f"skipped invalid skill: {child.name}")
                continue
            text = skill_file.read_text(encoding="utf-8")
            match = re.search(r"(?m)^name:\s*([^\n]+)$", text)
            skill_name = match.group(1).strip().strip("\"'") if match else child.name
            if not skill_name:
                warnings.append(f"skipped invalid skill: {child.name}")
                continue
            skills.append(AgentPluginSkill(skill_name, skill_file.resolve()))
        return tuple(skills)

    def _load_mcp(
        self,
        root: Path,
        manifest: Mapping[str, object],
        warnings: list[str],
    ) -> tuple[AgentPluginMcpServer, ...]:
        path = root / "mcp.json"
        if not path.exists():
            return ()
        if not self._contained(root, path) or not path.resolve().is_file():
            warnings.append("MCP component invalid: mcp.json must resolve to a regular file inside plugin root")
            return ()
        try:
            payload = self._read_object(path, fatal="mcp.json must contain a JSON object")
        except AgentPluginError as exc:
            warnings.append(f"MCP component invalid: {exc}")
            return ()
        if set(payload) != {"$schema", "mcpServers"}:
            warnings.append("MCP component invalid: mcp.json has invalid top-level fields")
            return ()
        if payload.get("$schema") != MCP_SCHEMA_1_0 or manifest.get("$schema") != PLUGIN_SCHEMA_1_0:
            warnings.append("MCP component invalid: unsupported or mismatched Agent Plugins schema")
            return ()
        raw_servers = payload.get("mcpServers")
        if not isinstance(raw_servers, dict):
            warnings.append("MCP component invalid: mcpServers must be an object")
            return ()
        servers: list[AgentPluginMcpServer] = []
        for name, config in raw_servers.items():
            try:
                servers.append(self._validate_server(root, str(name), config))
            except AgentPluginError as exc:
                warnings.append(f"skipped MCP server {name}: {exc}")
        return tuple(servers)

    def _validate_server(self, root: Path, name: str, raw: object) -> AgentPluginMcpServer:
        if not isinstance(raw, dict):
            raise AgentPluginError("server config must be an object")
        kind = raw.get("type")
        if kind == "stdio":
            allowed = {"type", "command", "args", "env", "cwd"}
            if set(raw) - allowed:
                raise AgentPluginError("unknown stdio field")
            command = raw.get("command")
            if not isinstance(command, str) or not command or any(char.isspace() for char in command):
                raise AgentPluginError("stdio command must be one executable token")
            if command.startswith("./"):
                self._validate_plugin_relative(root, command, "command")
            elif "/" in command or "\\" in command:
                raise AgentPluginError("stdio command must be bare or plugin-relative")
            args = raw.get("args", [])
            env = raw.get("env", {})
            if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
                raise AgentPluginError("stdio args must be strings")
            if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
                raise AgentPluginError("stdio env must map strings to strings")
            if any(key in {"PLUGIN_ROOT", "PLUGIN_DATA"} for key in env):
                raise AgentPluginError("stdio env cannot override reserved plugin variables")
            cwd = raw.get("cwd")
            if cwd is not None and not isinstance(cwd, str):
                raise AgentPluginError("stdio cwd must be a string")
            if isinstance(cwd, str) and cwd.startswith("./"):
                self._validate_plugin_relative(root, cwd, "cwd")
            elif isinstance(cwd, str) and not (
                cwd == "${PLUGIN_ROOT}" or cwd.startswith("${PLUGIN_ROOT}/")
                or cwd == "${PLUGIN_DATA}" or cwd.startswith("${PLUGIN_DATA}/")
            ):
                raise AgentPluginError("stdio cwd must be plugin-relative or use PLUGIN_ROOT/PLUGIN_DATA")
            return AgentPluginMcpServer(name, kind, dict(raw))

        if kind in {"streamable-http", "sse"}:
            allowed = {"type", "url", "headers"}
            if set(raw) - allowed:
                raise AgentPluginError("unknown remote MCP field")
            url = raw.get("url")
            if not isinstance(url, str):
                raise AgentPluginError("remote MCP url is required")
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise AgentPluginError("remote MCP url must be an absolute HTTP(S) URL without userinfo or fragment")
            loopback = parsed.hostname == "localhost" or parsed.hostname in {"127.0.0.1", "::1"}
            if parsed.scheme != "https" and not loopback:
                raise AgentPluginError("non-loopback remote MCP endpoints must use HTTPS")
            headers = raw.get("headers", {})
            if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()):
                raise AgentPluginError("remote MCP headers must map strings to strings")
            lowered = [key.lower() for key in headers]
            if len(lowered) != len(set(lowered)):
                raise AgentPluginError("remote MCP header names must be case-insensitively unique")
            return AgentPluginMcpServer(name, kind, dict(raw))
        raise AgentPluginError("unsupported MCP transport")

    @staticmethod
    def _read_object(path: Path, *, fatal: str) -> dict[str, object]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AgentPluginError(f"invalid JSON in {path.name}: {exc}") from exc
        if not isinstance(value, dict):
            raise AgentPluginError(fatal)
        return value

    @staticmethod
    def _validate_manifest(manifest: Mapping[str, object]) -> None:
        if manifest.get("$schema") != PLUGIN_SCHEMA_1_0:
            raise AgentPluginError("unsupported Agent Plugins manifest schema")
        name = manifest.get("name")
        if not isinstance(name, str) or not 1 <= len(name) <= 64 or not _NAME_RE.fullmatch(name):
            raise AgentPluginError("invalid Agent Plugins manifest name")
        for key, value in manifest.items():
            if key in _ALLOWED_MANIFEST_FIELDS and key != "extensions" and value is None:
                raise AgentPluginError(f"invalid plugin.json field: {key}")

    @staticmethod
    def _contained(root: Path, path: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(root.resolve(strict=True))
            return True
        except (OSError, ValueError):
            return False

    @classmethod
    def _validate_plugin_relative(cls, root: Path, value: str, field: str) -> None:
        if not value.startswith("./"):
            raise AgentPluginError(f"{field} must be plugin-relative")
        if not cls._contained(root, root / value[2:]):
            raise AgentPluginError(f"{field} escapes plugin root")
