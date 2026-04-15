"""Foxaholic source adapter (foxaholic.com).

Foxaholic is a CN/KR/JP translation aggregator running on the WordPress
Madara theme.  Standard Madara layout — no overrides needed.
"""

from __future__ import annotations

from novara.ingestion.adapters._madara_template import MadaraTemplate
from novara.ingestion.registry import register


@register
class FoxaholicAdapter(MadaraTemplate):
    SITE_KEY = "foxaholic"
    SITE_NAME = "Foxaholic"
    BASE_URL = "https://foxaholic.com"
    REQUESTS_PER_SECOND = 1.0
