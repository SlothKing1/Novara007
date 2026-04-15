"""NovelBuddy source adapter (novelbuddy.com / novelbuddy.io).

NovelBuddy is a clean Madara-based aggregator with a large CN TL catalogue
and a good reading experience.  Standard Madara layout with no overrides needed.
"""

from __future__ import annotations

import re

from novara.ingestion.adapters._madara_template import MadaraTemplate
from novara.ingestion.registry import register

_SLUG_RE = re.compile(r"novelbuddy\.(?:com|io)/novel/([^/?#]+)")


@register
class NovelBuddyAdapter(MadaraTemplate):
    SITE_KEY = "novelbuddy"
    SITE_NAME = "NovelBuddy"
    BASE_URL = "https://novelbuddy.com"
    REQUESTS_PER_SECOND = 1.0

    def extract_source_id(self, source_url: str) -> str:
        m = _SLUG_RE.search(source_url)
        return m.group(1) if m else source_url.rstrip("/").split("/")[-1]
