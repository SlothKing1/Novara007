"""NovelFull source adapter (novelfull.com)."""

from novara.ingestion.adapters._novelfull_template import NovelFullTemplate
from novara.ingestion.registry import register


@register
class NovelFullAdapter(NovelFullTemplate):
    SITE_KEY = "novelfull"
    SITE_NAME = "NovelFull"
    BASE_URL = "https://novelfull.com"
