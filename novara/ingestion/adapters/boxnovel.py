"""BoxNovel source adapter (boxnovel.com).

BoxNovel is a large CN/KR translation aggregator built on the Madara WordPress
theme.  The site has one of the largest chapter catalogues among aggregators.

Selectors: inherited from MadaraTemplate (standard Madara layout).
"""

from __future__ import annotations

from novara.ingestion.adapters._madara_template import MadaraTemplate
from novara.ingestion.registry import register


@register
class BoxNovelAdapter(MadaraTemplate):
    SITE_KEY = "boxnovel"
    SITE_NAME = "BoxNovel"
    BASE_URL = "https://boxnovel.com"
    REQUESTS_PER_SECOND = 1.0
