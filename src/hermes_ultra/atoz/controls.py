from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..autonomy import ActionContext, ApprovalRegistry


class DispatchState(str, Enum):
    BLOCKED_PRE_DISPATCH = "blocked_pre_dispatch"
    DISPATCHED = "dispatched"
    EXTERNAL_ACCEPTED = "external_accepted"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    COMPENSATION_REQUIRED = "compensation_required"


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    tenant_id: str
    owner_id: str
    permissions: frozenset[str]
    credential_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class SpendPolicy:
    budget_minor: int
    currency: str = "USD"

    def __post_init__(self) -> None:
        if self.budget_minor < 0:
            raise ValueError("budget_minor cannot be negative")
        if len(self.currency) != 3:
            raise ValueError("currency must be a three-letter code")


@dataclass(frozen=True)
class DataHandlingPolicy:
    permitted_tags: frozenset[str]
    forbidden_tags: frozenset[str] = frozenset({"host_credentials", "raw_payment_card"})


@dataclass(frozen=True)
class ActionRequest:
    action_id: str
    agent_id: str
    tenant_id: str
    run_id: str
    permission: str
    action_category: str
    reversible: bool
    remote: bool
    estimated_cost_minor: int = 0
    data_tags: frozenset[str] = frozenset()
    material_spend: bool = False
    external_irreversible_effect: bool = False


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    state: DispatchState
    reason: str


class ExecutionPolicyGateway:
    """Fail-closed execution boundary for AtoZ runs.

    It composes Hermes ApprovalRegistry rather than inventing a second approval
    system. Pause/revocation only prevent *new* dispatch; accepted external work
    must be reconciled or compensated explicitly.
    """

    def __init__(self, *, approval_registry: ApprovalRegistry, spend_policy: SpendPolicy, data_policy: DataHandlingPolicy) -> None:
        self.approval_registry = approval_registry
        self.spend_policy = spend_policy
        self.data_policy = data_policy
        self._agents: dict[str, AgentIdentity] = {}
        self._revoked: set[str] = set()
        self._paused = False
        self._spent_minor_by_run: dict[str, int] = {}
        self._cancelled_runs: set[str] = set()
        self._states: dict[str, DispatchState] = {}
        self._request_fingerprints: dict[str, tuple[object, ...]] = {}

    def register(self, identity: AgentIdentity) -> None:
        if not identity.agent_id.strip() or not identity.tenant_id.strip() or not identity.owner_id.strip():
            raise ValueError("agent_id, tenant_id, and owner_id are required")
        self._agents[identity.agent_id] = identity

    def revoke(self, agent_id: str) -> None:
        self._revoked.add(agent_id)

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def cancel_run(self, run_id: str) -> None:
        if not run_id.strip():
            raise ValueError("run_id is required")
        self._cancelled_runs.add(run_id)

    def evaluate(self, request: ActionRequest) -> PolicyDecision:
        identity = self._agents.get(request.agent_id)
        if identity is None:
            return PolicyDecision(False, DispatchState.BLOCKED_PRE_DISPATCH, "unknown_agent")
        if self._paused:
            return PolicyDecision(False, DispatchState.BLOCKED_PRE_DISPATCH, "global_pause")
        if request.run_id in self._cancelled_runs:
            return PolicyDecision(False, DispatchState.BLOCKED_PRE_DISPATCH, "run_cancelled")
        if request.agent_id in self._revoked:
            return PolicyDecision(False, DispatchState.BLOCKED_PRE_DISPATCH, "agent_revoked")
        if identity.tenant_id != request.tenant_id:
            return PolicyDecision(False, DispatchState.BLOCKED_PRE_DISPATCH, "cross_tenant_access")
        if request.permission not in identity.permissions:
            return PolicyDecision(False, DispatchState.BLOCKED_PRE_DISPATCH, "permission_denied")
        if request.estimated_cost_minor < 0:
            return PolicyDecision(False, DispatchState.BLOCKED_PRE_DISPATCH, "invalid_cost")
        if self.data_policy.forbidden_tags & request.data_tags:
            return PolicyDecision(False, DispatchState.BLOCKED_PRE_DISPATCH, "forbidden_data")
        unknown_tags = request.data_tags - self.data_policy.permitted_tags - self.data_policy.forbidden_tags
        if unknown_tags:
            return PolicyDecision(False, DispatchState.BLOCKED_PRE_DISPATCH, "unclassified_data")
        spent = self._spent_minor_by_run.get(request.run_id, 0)
        if spent + request.estimated_cost_minor > self.spend_policy.budget_minor:
            return PolicyDecision(False, DispatchState.BLOCKED_PRE_DISPATCH, "budget_exhausted")
        autonomy = self.approval_registry.evaluate_action(ActionContext(action_category=request.action_category, reversible=request.reversible, remote=request.remote, within_authorized_scope=True, external_irreversible_effect=request.external_irreversible_effect, material_spend=request.material_spend))
        if autonomy.human_approval_required:
            return PolicyDecision(False, DispatchState.BLOCKED_PRE_DISPATCH, autonomy.reason or "approval_required")
        return PolicyDecision(True, DispatchState.DISPATCHED, "allowed")

    @staticmethod
    def _fingerprint(request: ActionRequest) -> tuple[object, ...]:
        return (request.agent_id, request.tenant_id, request.run_id, request.permission, request.action_category, request.reversible, request.remote, request.estimated_cost_minor, tuple(sorted(request.data_tags)), request.material_spend, request.external_irreversible_effect)

    def begin_dispatch(self, request: ActionRequest) -> PolicyDecision:
        fingerprint = self._fingerprint(request)
        prior = self._states.get(request.action_id)
        if prior is not None:
            if self._request_fingerprints[request.action_id] != fingerprint:
                return PolicyDecision(False, DispatchState.BLOCKED_PRE_DISPATCH, "action_id_reused_with_different_request")
            return PolicyDecision(prior is not DispatchState.BLOCKED_PRE_DISPATCH, prior, "idempotent_replay")
        decision = self.evaluate(request)
        self._request_fingerprints[request.action_id] = fingerprint
        self._states[request.action_id] = decision.state
        if decision.allowed:
            self._spent_minor_by_run[request.run_id] = self._spent_minor_by_run.get(request.run_id, 0) + request.estimated_cost_minor
        return decision

    def mark_external_accepted(self, action_id: str) -> None:
        if self._states.get(action_id) is not DispatchState.DISPATCHED:
            raise ValueError("action was not dispatched")
        self._states[action_id] = DispatchState.EXTERNAL_ACCEPTED

    def mark_ambiguous(self, action_id: str) -> None:
        if self._states.get(action_id) not in {DispatchState.DISPATCHED, DispatchState.EXTERNAL_ACCEPTED}:
            raise ValueError("action is not in-flight")
        self._states[action_id] = DispatchState.RECONCILIATION_REQUIRED

    def mark_compensation_required(self, action_id: str) -> None:
        if self._states.get(action_id) not in {DispatchState.EXTERNAL_ACCEPTED, DispatchState.RECONCILIATION_REQUIRED}:
            raise ValueError("action has no accepted/ambiguous external side effect")
        self._states[action_id] = DispatchState.COMPENSATION_REQUIRED

    def state(self, action_id: str) -> DispatchState | None:
        return self._states.get(action_id)
