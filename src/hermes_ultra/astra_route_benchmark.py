from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable, Sequence

SHORT_CONTEXT_LIMIT = 272_000
DIRECT_ROUTE = "direct-astra"
BEDROCK_ROUTE = "bedrock-astra-us"


@dataclass(frozen=True)
class PriceBand:
    input_per_million: float
    cache_write_per_million: float
    cache_read_per_million: float
    output_per_million: float


@dataclass(frozen=True)
class RoutePricing:
    short: PriceBand
    long: PriceBand

    def cost(self, observation: "RunObservation") -> float:
        band = self.long if observation.input_tokens > SHORT_CONTEXT_LIMIT else self.short
        token_cost = (
            observation.input_tokens * band.input_per_million
            + observation.cache_write_tokens * band.cache_write_per_million
            + observation.cache_read_tokens * band.cache_read_per_million
            + observation.output_tokens * band.output_per_million
        ) / 1_000_000
        return token_cost + observation.extra_cost_usd


@dataclass(frozen=True)
class RouteSpec:
    key: str
    provider: str
    model_id: str
    base_url: str
    auth_env: str
    pricing: RoutePricing
    benchmark_only: bool = True
    primary_eligible: bool = False
    audit_controls: tuple[str, ...] = ()


@dataclass(frozen=True)
class BenchmarkManifest:
    base_sha: str
    task: str
    repo_path: str = "."
    primary_route_change_allowed: bool = False

    @property
    def fingerprint(self) -> str:
        return task_fingerprint(self.base_sha, self.task)


@dataclass(frozen=True)
class RunObservation:
    route: str
    run_id: str
    task_fingerprint: str
    completion_quality: float
    context_retention: float
    browser_reliability: float
    tool_reliability: float
    latency_seconds: float
    input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int
    extra_cost_usd: float
    audit_score: float
    audit_evidence_complete: bool
    success: bool
    tests_passed: bool
    regression: bool


@dataclass(frozen=True)
class RouteMetrics:
    runs: int
    completion_quality: float
    context_retention: float
    browser_reliability: float
    tool_reliability: float
    latency_seconds: float
    effective_cost_usd: float
    audit_score: float
    audit_evidence_complete: bool
    success_rate: float
    tests_pass_rate: float
    regression_rate: float


@dataclass(frozen=True)
class BenchmarkDecision:
    candidate: bool
    reason: str
    auto_promote: bool = False
    primary_route_changed: bool = False
    human_approval_required: bool = True


@dataclass(frozen=True)
class BenchmarkReport:
    manifest: BenchmarkManifest
    direct: RouteMetrics
    bedrock: RouteMetrics
    decision: BenchmarkDecision

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest": asdict(self.manifest),
            "direct": asdict(self.direct),
            "bedrock": asdict(self.bedrock),
            "decision": asdict(self.decision),
        }


@dataclass(frozen=True)
class BenchmarkPolicy:
    min_runs: int = 3
    min_success_rate: float = 1.0
    min_tests_pass_rate: float = 1.0
    max_regression_rate: float = 0.0
    max_quality_regression: float = 0.02
    max_context_regression: float = 0.02
    max_browser_regression: float = 0.02
    max_tool_regression: float = 0.02
    max_latency_ratio: float = 1.25
    max_cost_ratio: float = 1.15
    min_bedrock_audit_score: float = 0.90
    min_material_advantage: float = 0.05


def task_fingerprint(base_sha: str, task: str) -> str:
    material = f"{base_sha.strip()}\n{task.strip()}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def default_routes() -> dict[str, RouteSpec]:
    direct = RouteSpec(
        key=DIRECT_ROUTE,
        provider="openai",
        model_id="gpt-6-astra",
        base_url="https://api.openai.com/v1",
        auth_env="OPENAI_API_KEY",
        pricing=RoutePricing(
            short=PriceBand(10.00, 12.50, 1.00, 50.00),
            long=PriceBand(20.00, 25.00, 2.00, 75.00),
        ),
        audit_controls=("provider_request_id", "usage_metadata"),
    )
    bedrock = RouteSpec(
        key=BEDROCK_ROUTE,
        provider="amazon-bedrock",
        model_id="us.openai.gpt-6-astra",
        base_url="https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1",
        auth_env="AWS_BEARER_TOKEN_BEDROCK",
        pricing=RoutePricing(
            short=PriceBand(11.00, 13.75, 1.10, 55.00),
            long=PriceBand(22.00, 27.50, 2.20, 82.50),
        ),
        audit_controls=(
            "provider_request_id",
            "usage_metadata",
            "bedrock_invocation_log",
            "cloudtrail_auth_event",
        ),
    )
    return {route.key: route for route in (direct, bedrock)}


def _validate_score(name: str, value: float) -> None:
    if value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be between 0 and 1")


def _validate_observation(observation: RunObservation, expected_fingerprint: str) -> None:
    if observation.route not in {DIRECT_ROUTE, BEDROCK_ROUTE}:
        raise ValueError(f"unknown benchmark route: {observation.route}")
    if observation.task_fingerprint != expected_fingerprint:
        raise ValueError("benchmark observations do not share the manifest task fingerprint")
    if not observation.run_id:
        raise ValueError("run_id is required")
    for name in (
        "completion_quality",
        "context_retention",
        "browser_reliability",
        "tool_reliability",
        "audit_score",
    ):
        _validate_score(name, float(getattr(observation, name)))
    if observation.latency_seconds < 0:
        raise ValueError("latency_seconds must be non-negative")
    for name in ("input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens"):
        if int(getattr(observation, name)) < 0:
            raise ValueError(f"{name} must be non-negative")
    if observation.extra_cost_usd < 0:
        raise ValueError("extra_cost_usd must be non-negative")


def _aggregate(route: RouteSpec, observations: Sequence[RunObservation]) -> RouteMetrics:
    if not observations:
        raise ValueError(f"no observations for route {route.key}")
    costs = [route.pricing.cost(item) for item in observations]
    n = len(observations)
    return RouteMetrics(
        runs=n,
        completion_quality=mean(item.completion_quality for item in observations),
        context_retention=mean(item.context_retention for item in observations),
        browser_reliability=mean(item.browser_reliability for item in observations),
        tool_reliability=mean(item.tool_reliability for item in observations),
        latency_seconds=mean(item.latency_seconds for item in observations),
        effective_cost_usd=mean(costs),
        audit_score=mean(item.audit_score for item in observations),
        audit_evidence_complete=all(item.audit_evidence_complete for item in observations),
        success_rate=sum(item.success for item in observations) / n,
        tests_pass_rate=sum(item.tests_passed for item in observations) / n,
        regression_rate=sum(item.regression for item in observations) / n,
    )


def _decision(direct: RouteMetrics, bedrock: RouteMetrics, policy: BenchmarkPolicy) -> BenchmarkDecision:
    blockers: list[str] = []
    if direct.runs < policy.min_runs or bedrock.runs < policy.min_runs:
        blockers.append(f"minimum {policy.min_runs} runs per route not met")
    if bedrock.success_rate < policy.min_success_rate:
        blockers.append("Bedrock success rate below threshold")
    if bedrock.tests_pass_rate < policy.min_tests_pass_rate:
        blockers.append("Bedrock tests pass rate below threshold")
    if bedrock.regression_rate > policy.max_regression_rate:
        blockers.append("Bedrock regression rate above threshold")
    if not bedrock.audit_evidence_complete:
        blockers.append("Bedrock audit evidence is incomplete")
    if bedrock.audit_score < policy.min_bedrock_audit_score:
        blockers.append("Bedrock auditability score below threshold")
    if bedrock.completion_quality < direct.completion_quality - policy.max_quality_regression:
        blockers.append("Bedrock completion quality regresses versus direct Astra")
    if bedrock.context_retention < direct.context_retention - policy.max_context_regression:
        blockers.append("Bedrock context retention regresses versus direct Astra")
    if bedrock.browser_reliability < direct.browser_reliability - policy.max_browser_regression:
        blockers.append("Bedrock browser reliability regresses versus direct Astra")
    if bedrock.tool_reliability < direct.tool_reliability - policy.max_tool_regression:
        blockers.append("Bedrock tool reliability regresses versus direct Astra")
    if direct.latency_seconds > 0 and bedrock.latency_seconds > direct.latency_seconds * policy.max_latency_ratio:
        blockers.append("Bedrock latency exceeds allowed ratio")
    if direct.effective_cost_usd > 0 and bedrock.effective_cost_usd > direct.effective_cost_usd * policy.max_cost_ratio:
        blockers.append("Bedrock effective cost exceeds allowed ratio")
    if blockers:
        return BenchmarkDecision(False, "; ".join(blockers))

    advantages = []
    if bedrock.audit_score >= direct.audit_score + policy.min_material_advantage:
        advantages.append("auditability")
    if direct.effective_cost_usd > 0 and bedrock.effective_cost_usd <= direct.effective_cost_usd * (1 - policy.min_material_advantage):
        advantages.append("effective cost")
    if direct.latency_seconds > 0 and bedrock.latency_seconds <= direct.latency_seconds * (1 - policy.min_material_advantage):
        advantages.append("latency")
    if bedrock.completion_quality >= direct.completion_quality + policy.min_material_advantage:
        advantages.append("completion quality")
    if bedrock.context_retention >= direct.context_retention + policy.min_material_advantage:
        advantages.append("context retention")
    if bedrock.browser_reliability >= direct.browser_reliability + policy.min_material_advantage:
        advantages.append("browser reliability")
    if bedrock.tool_reliability >= direct.tool_reliability + policy.min_material_advantage:
        advantages.append("tool reliability")

    if not advantages:
        return BenchmarkDecision(False, "Bedrock passed guardrails but has no measured material advantage")
    return BenchmarkDecision(
        True,
        "Bedrock candidate justified by measured " + ", ".join(advantages),
        auto_promote=False,
        primary_route_changed=False,
        human_approval_required=True,
    )


def evaluate_benchmark(
    manifest: BenchmarkManifest,
    observations: Iterable[RunObservation],
    *,
    policy: BenchmarkPolicy | None = None,
) -> BenchmarkReport:
    policy = policy or BenchmarkPolicy()
    routes = default_routes()
    grouped = {DIRECT_ROUTE: [], BEDROCK_ROUTE: []}
    seen_ids: set[tuple[str, str]] = set()
    for observation in observations:
        _validate_observation(observation, manifest.fingerprint)
        key = (observation.route, observation.run_id)
        if key in seen_ids:
            raise ValueError(f"duplicate run_id for route: {observation.route}/{observation.run_id}")
        seen_ids.add(key)
        grouped[observation.route].append(observation)

    direct = _aggregate(routes[DIRECT_ROUTE], grouped[DIRECT_ROUTE])
    bedrock = _aggregate(routes[BEDROCK_ROUTE], grouped[BEDROCK_ROUTE])
    decision = _decision(direct, bedrock, policy)
    return BenchmarkReport(manifest=manifest, direct=direct, bedrock=bedrock, decision=decision)


def _manifest_payload(manifest: BenchmarkManifest) -> dict[str, object]:
    routes = default_routes()
    return {
        "manifest": {
            **asdict(manifest),
            "task_fingerprint": manifest.fingerprint,
            "required_routes": [DIRECT_ROUTE, BEDROCK_ROUTE],
        },
        "routes": {
            key: {
                "key": route.key,
                "provider": route.provider,
                "model_id": route.model_id,
                "base_url": route.base_url,
                "auth_env": route.auth_env,
                "benchmark_only": route.benchmark_only,
                "primary_eligible": route.primary_eligible,
                "audit_controls": list(route.audit_controls),
            }
            for key, route in routes.items()
        },
        "required_metrics": [
            "completion_quality",
            "context_retention",
            "browser_reliability",
            "tool_reliability",
            "latency_seconds",
            "input_tokens",
            "cache_write_tokens",
            "cache_read_tokens",
            "output_tokens",
            "extra_cost_usd",
            "audit_score",
            "audit_evidence_complete",
            "success",
            "tests_passed",
            "regression",
        ],
        "promotion": {
            "automatic": False,
            "primary_route_change_allowed": False,
            "human_approval_required": True,
        },
    }


def _load_observations(path: Path) -> list[RunObservation]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("runs", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("observation file must be a list or {'runs': [...]} object")
    return [RunObservation(**row) for row in rows]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded direct-vs-Bedrock GPT-6 Astra benchmark")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="emit a benchmark-only route manifest")
    plan.add_argument("--repo-path", default=".")
    plan.add_argument("--base-sha", required=True)
    plan.add_argument("--task", required=True)

    evaluate = sub.add_parser("evaluate", help="evaluate collected benchmark observations")
    evaluate.add_argument("--repo-path", default=".")
    evaluate.add_argument("--base-sha", required=True)
    evaluate.add_argument("--task", required=True)
    evaluate.add_argument("--observations", required=True)

    args = parser.parse_args(argv)
    manifest = BenchmarkManifest(base_sha=args.base_sha, task=args.task, repo_path=args.repo_path)
    if args.command == "plan":
        print(json.dumps(_manifest_payload(manifest), indent=2, sort_keys=True))
        return 0

    report = evaluate_benchmark(manifest, _load_observations(Path(args.observations)))
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.decision.candidate else 3


if __name__ == "__main__":
    raise SystemExit(main())
