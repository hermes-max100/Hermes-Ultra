from __future__ import annotations

import re

from .types import (
    EvidenceBundle,
    EvidenceSource,
    LegalContext,
    MatterIsolationViolation,
    ProvenanceViolation,
    SourceKind,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProvenanceGuard:
    """Matter-isolated evidence registry and verification gate."""

    def __init__(self) -> None:
        self._sources: dict[str, EvidenceSource] = {}

    def add_source(
        self,
        context: LegalContext,
        *,
        source_id: str,
        kind: SourceKind,
        locator: str,
        sha256: str,
    ) -> EvidenceSource:
        source_id = source_id.strip() if isinstance(source_id, str) else ""
        locator = locator.strip() if isinstance(locator, str) else ""
        digest = sha256.strip().lower() if isinstance(sha256, str) else ""
        if not source_id or not locator:
            raise ProvenanceViolation("invalid_source")
        if not _SHA256_RE.fullmatch(digest):
            raise ProvenanceViolation("invalid_source_sha256")
        existing = self._sources.get(source_id)
        if existing is not None:
            if existing.matter_id != context.matter_id:
                raise MatterIsolationViolation("source_id_owned_by_other_matter")
            if existing != EvidenceSource(source_id, context.matter_id, kind, locator, digest):
                raise ProvenanceViolation("source_id_redefinition_forbidden")
            return existing
        source = EvidenceSource(source_id, context.matter_id, kind, locator, digest)
        self._sources[source_id] = source
        return source

    def _resolve(self, context: LegalContext, source_id: str) -> EvidenceSource:
        source = self._sources.get(source_id)
        if source is None:
            raise ProvenanceViolation("unknown_source_id")
        if source.matter_id != context.matter_id:
            raise MatterIsolationViolation("cross_matter_source_access")
        return source

    def verify_fact(self, context: LegalContext, *, source_ids: list[str] | tuple[str, ...]) -> tuple[EvidenceSource, ...]:
        if not source_ids:
            raise ProvenanceViolation("verified_fact_requires_source")
        return tuple(self._resolve(context, source_id) for source_id in source_ids)

    def verify_citation(
        self,
        context: LegalContext,
        *,
        authority_source_ids: list[str] | tuple[str, ...],
    ) -> tuple[EvidenceSource, ...]:
        if not authority_source_ids:
            raise ProvenanceViolation("verified_citation_requires_authority")
        sources = tuple(self._resolve(context, source_id) for source_id in authority_source_ids)
        if any(source.kind is not SourceKind.AUTHORITY for source in sources):
            raise ProvenanceViolation("citation_source_is_not_authority")
        return sources

    def claim_success(
        self,
        context: LegalContext,
        *,
        operation: str,
        source_ids: list[str] | tuple[str, ...],
        authority_ids: list[str] | tuple[str, ...] = (),
        external_disclosure: bool = False,
        model_route: str | None = None,
    ) -> EvidenceBundle:
        operation = operation.strip() if isinstance(operation, str) else ""
        if not operation:
            raise ProvenanceViolation("operation_required")
        if not source_ids:
            raise ProvenanceViolation("success_requires_evidence_bundle")
        self.verify_fact(context, source_ids=source_ids)
        if authority_ids:
            self.verify_citation(context, authority_source_ids=authority_ids)
        return EvidenceBundle(
            matter_id=context.matter_id,
            operation=operation,
            source_ids=tuple(source_ids),
            authority_ids=tuple(authority_ids),
            external_disclosure=bool(external_disclosure),
            model_route=model_route,
            verified=True,
        )
