"""CoverResolver — downloads and scores cover candidates, selects the best.

Resolution strategy:
1. For each CoverCandidate without a local_path: download and score.
2. Pick the candidate with the highest quality_score.
3. Mark it as is_selected=True; clear is_selected on all others.
4. Write its id to Work.selected_cover_id.

Cover quality heuristics (configurable):
- Resolution: prefer larger images
- Aspect ratio: prefer portrait (2:3) over square or landscape
- File size: penalise both tiny and suspiciously huge files
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from novara.config import get_settings
from novara.models import CoverCandidate, SourceTitle, Version, Work

log = structlog.get_logger(__name__)
settings = get_settings()

# Ideal cover dimensions
IDEAL_WIDTH = 300
IDEAL_HEIGHT = 450

# Minimum acceptable dimensions
MIN_WIDTH = 100
MIN_HEIGHT = 100


class CoverResolver:
    """Downloads cover images and selects the best candidate for a Work."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._storage_path = Path(settings.cover_storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)

    async def resolve(self, work: Work) -> CoverCandidate | None:
        """Download all unscored covers for a Work, select the best one.

        Args:
            work: The Work to resolve a cover for.

        Returns:
            The selected CoverCandidate, or None if none available.
        """
        candidates = await self._load_candidates(work)
        if not candidates:
            return None

        for candidate in candidates:
            if candidate.quality_score is None:
                await self._download_and_score(candidate)

        # Reset selection
        candidate_ids = [c.id for c in candidates]
        await self.session.execute(
            update(CoverCandidate)
            .where(CoverCandidate.id.in_(candidate_ids))
            .values(is_selected=False)
        )

        # Pick best
        scored = [c for c in candidates if c.quality_score is not None]
        if not scored:
            return None

        winner = max(scored, key=lambda c: c.quality_score or 0.0)
        winner.is_selected = True
        work.selected_cover_id = winner.id

        log.info(
            "cover_selected",
            work_id=str(work.id),
            cover_id=str(winner.id),
            score=winner.quality_score,
        )

        return winner

    async def _load_candidates(self, work: Work) -> list[CoverCandidate]:
        stmt = (
            select(CoverCandidate)
            .join(SourceTitle, CoverCandidate.source_title_id == SourceTitle.id)
            .join(Version, SourceTitle.version_id == Version.id)
            .where(Version.work_id == work.id)
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def _download_and_score(self, candidate: CoverCandidate) -> None:
        """Download the cover image and compute its quality score."""
        try:
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=True
            ) as client:
                resp = await client.get(candidate.source_url)
                resp.raise_for_status()

            content = resp.content
            candidate.file_size = len(content)

            # Detect format and dimensions
            fmt, width, height = _inspect_image(content)
            candidate.image_format = fmt
            candidate.width = width
            candidate.height = height

            # Save locally
            if fmt:
                filename = f"{candidate.id}.{fmt}"
                local_path = self._storage_path / filename
                local_path.write_bytes(content)
                candidate.local_path = str(local_path)

            candidate.quality_score = self._compute_score(
                width=width, height=height, file_size=len(content)
            )

        except Exception:
            log.warning(
                "cover_download_failed",
                url=candidate.source_url,
                cover_id=str(candidate.id),
                exc_info=True,
            )
            candidate.quality_score = 0.0

    def _compute_score(
        self,
        width: int | None,
        height: int | None,
        file_size: int | None,
    ) -> float:
        if not width or not height:
            return 0.0

        # Too small: discard
        if width < MIN_WIDTH or height < MIN_HEIGHT:
            return 0.05

        # Resolution score: sigmoid-like approach towards ideal size
        res_score = min(width / IDEAL_WIDTH, 1.0) * 0.5 + min(height / IDEAL_HEIGHT, 1.0) * 0.5

        # Aspect ratio score: ideal is 2:3 (portrait)
        ratio = width / height
        ideal_ratio = IDEAL_WIDTH / IDEAL_HEIGHT  # 0.667
        aspect_score = max(0.0, 1.0 - abs(ratio - ideal_ratio) * 2)

        # File size sanity (50 KB–5 MB is healthy)
        size_score = 1.0
        if file_size:
            if file_size < 10_000:
                size_score = 0.3
            elif file_size > 10_000_000:
                size_score = 0.5

        return round(0.5 * res_score + 0.3 * aspect_score + 0.2 * size_score, 4)


def _inspect_image(data: bytes) -> tuple[str | None, int | None, int | None]:
    """Return (format, width, height) by reading image headers.

    Uses Pillow if available; falls back to magic-byte detection.
    """
    try:
        from PIL import Image
        import io

        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").lower()
            if fmt == "jpeg":
                fmt = "jpeg"
            return fmt or None, img.width, img.height
    except Exception:
        pass

    # Fallback: detect format from magic bytes only, no dimension info
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg", None, None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", None, None
    if data[:4] in (b"RIFF", b"WEBP"):
        return "webp", None, None
    return None, None, None
