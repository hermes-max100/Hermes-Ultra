from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .autonomy import ActionConsequenceClassifier, ActionContext, ApprovalRegistry
from .capability_expansion import CapabilityExpansionController
from .capability_projection import (
    CapabilityCatalog,
    CapabilityProjection,
    ConsequenceClass,
    EvidenceState,
    RuntimeCapabilityDescriptor,
)
from .contracts import CapabilityResult, FailureClass
from .delegated_identity import DelegatedIdentity
from .evidence import EvidenceRecorder
from .mcp_gateway import McpGateway, McpGatewayError, McpToolDescriptor
from .progressive_capabilities import (
    CapabilityDescription,
    CapabilityDiscoveryResult,
    CapabilityDispatchResult,
    DiscoveryTask,
    ProgressiveCapabilityRuntime,
)


@dataclass(frozen=True)
class McpCapabilityBinding:
    capability_id: str
    provider_id: str
    tool_name: str
    tool: McpToolDescriptor


class _McpCapabilityExecutor:
    def __init__(
        self,
        gateway: McpGateway,
        bindings: Mapping[str, McpCapabilityBinding],
        *,
        identity: DelegatedIdentity | None,
    ) -> None:
        self.gateway = gateway
        self.bindings = bindings
        self.identity = identity

    def execute(
        self,
        *,
        capability_id: str,
        arguments: dict[str, object],
    ) -> CapabilityResult[object]:
        binding = self.bindings.get(capability_id)
        if binding is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                f"unknown MCP capability binding: {capability_id}",
                recoverable=True,
                metadata={"capability_id": capability_id},
            )
        try:
            value = self.gateway.call_tool(
                binding.provider_id,
                binding.tool_name,
                arguments,
                identity=self.identity,
            )
        except PermissionError as exc:
            return CapabilityResult.failure(
                FailureClass.AUTHORITY_REQUIRED,
                str(exc),
                recoverable=True,
                metadata={
                    "capability_id": capability_id,
                    "provider_id": binding.provider_id,
                    "tool_name": binding.tool_name,
                },
            )
        except KeyError as exc:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                str(exc),
                recoverable=True,
                metadata={
                    "capability_id": capability_id,
                    "provider_id": binding.provider_id,
                    "tool_name": binding.tool_name,
                },
            )
        except McpGatewayError as exc:
            return CapabilityResult.failure(
                FailureClass.UPSTREAM_UNAVAILABLE,
                str(exc),
                recoverable=True,
                metadata={
                    "capability_id": capability_id,
                    "provider_id": binding.provider_id,
                    "tool_name": binding.tool_name,
                },
            )
        return CapabilityResult.success(
            value,
            metadata={
                "provider_id": binding.provider_id,
                "tool_name": binding.tool_name,
            },
        )


class McpProgressiveCapabilityFacade:
    """Compact discover/describe/dispatch surface over the governed MCP gateway.

    Only tools already visible through `McpGateway.visible_tools` enter the
    transient capability catalog. That keeps candidate/inactive providers and
    delegated-identity-excluded tools outside model-facing discovery. Dispatch
    still flows through `McpGateway.call_tool`; this facade never promotes or
    activates providers and never widens delegated scopes.
    """

    def __init__(
        self,
        gateway: McpGateway,
        *,
        approval_registry: ApprovalRegistry,
        evidence_recorder: EvidenceRecorder,
        consequence_classifier: ActionConsequenceClassifier | None = None,
        max_catalog_size: int = 4096,
        discovery_token_budget: int = 512,
    ) -> None:
        if max_catalog_size <= 0:
            raise ValueError("max_catalog_size must be positive")
        self.gateway = gateway
        self.approval_registry = approval_registry
        self.evidence_recorder = evidence_recorder
        self.consequence_classifier = consequence_classifier or ActionConsequenceClassifier()
        self.max_catalog_size = max_catalog_size
        self.discovery_token_budget = discovery_token_budget

    @staticmethod
    def capability_id(tool: McpToolDescriptor) -> str:
        return f"mcp:{tool.provider_id}:{tool.name}"

    @staticmethod
    def _descriptor(tool: McpToolDescriptor) -> RuntimeCapabilityDescriptor:
        consequence = (
            ConsequenceClass.CONSEQUENTIAL
            if tool.destructive
            else ConsequenceClass.REVERSIBLE_REMOTE
        )
        match_terms = set(tool.capabilities)
        match_terms.add(tool.provider_id)
        match_terms.add(tool.name)
        return RuntimeCapabilityDescriptor(
            capability_id=McpProgressiveCapabilityFacade.capability_id(tool),
            family="mcp",
            purpose=tool.description or f"MCP tool {tool.provider_id}/{tool.name}",
            match_terms=tuple(sorted(match_terms)),
            base_utility=0.25 if tool.read_only else 0.2,
            consequence_class=consequence,
            reversible=not tool.destructive,
            interface="mcp",
            provider=tool.provider_id,
            evidence_state=EvidenceState.OBSERVED,
            provenance=(
                ("source", "mcp_gateway"),
                ("provider_id", tool.provider_id),
                ("tool_name", tool.name),
            ),
            detail_token_estimate=96,
            summary_token_estimate=18,
            available=True,
        )

    def _catalog_and_bindings(
        self,
        *,
        profile: str,
        capabilities: Iterable[str],
        provider_overrides: Iterable[str],
        identity: DelegatedIdentity | None,
    ) -> tuple[CapabilityCatalog, dict[str, McpCapabilityBinding]]:
        tools = self.gateway.visible_tools(
            profile=profile,
            capabilities=frozenset(capabilities),
            provider_overrides=frozenset(provider_overrides),
            identity=identity,
            limit=self.max_catalog_size,
        )
        descriptors: list[RuntimeCapabilityDescriptor] = []
        bindings: dict[str, McpCapabilityBinding] = {}
        for tool in tools:
            capability_id = self.capability_id(tool)
            descriptor = self._descriptor(tool)
            descriptors.append(descriptor)
            bindings[capability_id] = McpCapabilityBinding(
                capability_id=capability_id,
                provider_id=tool.provider_id,
                tool_name=tool.name,
                tool=tool,
            )
        return CapabilityCatalog(tuple(descriptors)), bindings

    def _runtime(
        self,
        *,
        profile: str,
        capabilities: Iterable[str],
        provider_overrides: Iterable[str],
        identity: DelegatedIdentity | None,
    ) -> tuple[ProgressiveCapabilityRuntime, dict[str, McpCapabilityBinding]]:
        catalog, bindings = self._catalog_and_bindings(
            profile=profile,
            capabilities=capabilities,
            provider_overrides=provider_overrides,
            identity=identity,
        )
        expansion = CapabilityExpansionController(
            catalog,
            self.approval_registry,
            self.evidence_recorder,
            consequence_classifier=self.consequence_classifier,
        )
        runtime = ProgressiveCapabilityRuntime(
            catalog,
            executor=_McpCapabilityExecutor(
                self.gateway,
                bindings,
                identity=identity,
            ),
            expansion_controller=expansion,
            discovery_token_budget=self.discovery_token_budget,
        )
        return runtime, bindings

    def discover(
        self,
        *,
        task: DiscoveryTask,
        profile: str,
        query: str = "",
        capabilities: Iterable[str] = (),
        provider_overrides: Iterable[str] = (),
        identity: DelegatedIdentity | None = None,
        limit: int = 5,
    ) -> CapabilityResult[CapabilityDiscoveryResult]:
        runtime, _ = self._runtime(
            profile=profile,
            capabilities=capabilities,
            provider_overrides=provider_overrides,
            identity=identity,
        )
        return runtime.discover(task=task, query=query, limit=limit)

    def describe(
        self,
        capability_id: str,
        *,
        profile: str,
        capabilities: Iterable[str] = (),
        provider_overrides: Iterable[str] = (),
        identity: DelegatedIdentity | None = None,
    ) -> CapabilityResult[CapabilityDescription]:
        runtime, _ = self._runtime(
            profile=profile,
            capabilities=capabilities,
            provider_overrides=provider_overrides,
            identity=identity,
        )
        return runtime.describe(capability_id)

    def dispatch(
        self,
        *,
        task_id: str,
        capability_id: str,
        arguments: Mapping[str, object],
        profile: str,
        reason: str,
        expected_utility: float,
        capabilities: Iterable[str] = (),
        provider_overrides: Iterable[str] = (),
        identity: DelegatedIdentity | None = None,
        action: ActionContext | None = None,
        projection: CapabilityProjection | None = None,
    ) -> CapabilityResult[CapabilityDispatchResult]:
        runtime, bindings = self._runtime(
            profile=profile,
            capabilities=capabilities,
            provider_overrides=provider_overrides,
            identity=identity,
        )
        binding = bindings.get(capability_id)
        if binding is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                f"MCP capability is not visible in the governed scope: {capability_id}",
                recoverable=True,
                metadata={"capability_id": capability_id, "profile": profile},
            )
        if action is None:
            tool = binding.tool
            action = ActionContext(
                action_category=f"mcp:{binding.provider_id}:{binding.tool_name}",
                reversible=not tool.destructive,
                remote=True,
                destructive=tool.destructive,
                external_irreversible_effect=tool.destructive,
            )
        return runtime.dispatch(
            task_id=task_id,
            capability_id=capability_id,
            arguments=arguments,
            action=action,
            reason=reason,
            expected_utility=expected_utility,
            projection=projection,
        )
