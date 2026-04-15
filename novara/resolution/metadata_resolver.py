"""MetadataResolver — selects the winning claim per field and promotes to Work.

Resolution strategy:
- For each field on a Work, look at all MetadataClaims across all SourceTitles
  that belong to the Work (via Version → SourceTitle).
- Pick the claim with the highest confidence score.
- On tie: prefer the claim from the most recently scraped source.
- Write the winning value to Work.<field> and mark the claim as is_resolved=True.

Resolution is designed to be re-runnable without re-scraping.  Changing a
source's quality_score and re-running the resolver is sufficient to update
the outcome.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from novara.models import MetadataClaim, SourceTitle, Version, Work

log = structlog.get_logger(__name__)

# Map from MetadataClaim.field_name to Work attribute name
FIELD_TO_WORK_ATTR: dict[str, str] = {
    "title": "title",
    "synopsis": "synopsis",
    "status": "status",
    "original_language": "original_language",
}

# Fields that should be written to Version instead of Work
FIELD_TO_VERSION_ATTR: dict[str, str] = {
    "translator_group": "translator_group",
    "language": "language",
}


@dataclass
class ResolutionReport:
    """Result of one resolver run."""

    work_id: str
    fields_resolved: dict[str, str]  # field_name → winning raw_value
    fields_skipped: list[str]  # fields with no claims


class MetadataResolver:
    """Resolves metadata claims for a Work into canonical field values."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(self, work: Work) -> ResolutionReport:
        """Run resolution for all metadata fields of a Work.

        Args:
            work: The Work row to resolve.

        Returns:
            ResolutionReport summarising what changed.
        """
        # Load all SourceTitles for this work (via its Versions)
        stmt = (
            select(SourceTitle)
            .join(Version, SourceTitle.version_id == Version.id)
            .where(Version.work_id == work.id)
            .options(selectinload(SourceTitle.metadata_claims))
        )
        result = await self.session.scalars(stmt)
        source_titles = list(result.all())

        if not source_titles:
            return ResolutionReport(
                work_id=str(work.id), fields_resolved={}, fields_skipped=[]
            )

        # Gather all claims grouped by field_name
        claims_by_field: dict[str, list[MetadataClaim]] = {}
        for st in source_titles:
            for claim in st.metadata_claims:
                claims_by_field.setdefault(claim.field_name, []).append(claim)

        resolved: dict[str, str] = {}
        skipped: list[str] = []

        # Reset previous is_resolved flags for this Work's claims
        claim_ids = [
            c.id
            for claims in claims_by_field.values()
            for c in claims
        ]
        if claim_ids:
            await self.session.execute(
                update(MetadataClaim)
                .where(MetadataClaim.id.in_(claim_ids))
                .values(is_resolved=False)
            )

        for field_name, claims in claims_by_field.items():
            winner = self._pick_winner(claims)
            if winner is None:
                skipped.append(field_name)
                continue

            winner.is_resolved = True
            value = winner.normalised_value or winner.raw_value
            resolved[field_name] = value

            if field_name in FIELD_TO_WORK_ATTR:
                setattr(work, FIELD_TO_WORK_ATTR[field_name], value)

        log.info(
            "metadata_resolved",
            work_id=str(work.id),
            resolved=list(resolved),
            skipped=skipped,
        )

        return ResolutionReport(
            work_id=str(work.id),
            fields_resolved=resolved,
            fields_skipped=skipped,
        )

    def _pick_winner(self, claims: list[MetadataClaim]) -> MetadataClaim | None:
        """Return the best claim by confidence, then recency."""
        if not claims:
            return None
        return max(
            claims,
            key=lambda c: (c.confidence, c.created_at),
        )
