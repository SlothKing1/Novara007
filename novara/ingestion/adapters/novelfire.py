"""NovelFire source adapter (novelfire.net).

NovelFire is a CN/KR translation aggregator running the WordPress Madara
theme.  Standard Madara layout; no selector overrides needed.
"""

from __future__ import annotations

import re

from novara.ingestion.adapters._madara_template import MadaraTemplate
from novara.ingestion.registry import register

_SLUG_RE = re.compile(r"novelfire\.net/novel/([^/?#]+)")


@register
class NovelFireAdapter(MadaraTemplate):
    SITE_KEY = "novelfire"
    SITE_NAME = "NovelFire"
    BASE_URL = "https://novelfire.net"
    REQUESTS_PER_SECOND = 1.0

    def extract_source_id(self, source_url: str) -> str:
        m = _SLUG_RE.search(source_url)
        return m.group(1) if m else source_url.rstrip("/").split("/")[-1]
