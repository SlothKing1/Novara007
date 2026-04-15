"""NovelBin source adapter (novelbin.com).

novelbin.com uses the same HTML structure as novelfull.com with minor
selector differences. Both inherit from NovelFullTemplate.
"""

from novara.ingestion.adapters._novelfull_template import NovelFullTemplate
from novara.ingestion.registry import register


@register
class NovelBinAdapter(NovelFullTemplate):
    SITE_KEY = "novelbin"
    SITE_NAME = "NovelBin"
    BASE_URL = "https://novelbin.com"

    # novelbin uses slightly different selectors
    SEL_TITLE = "h3.title"
    SEL_COVER = ".book img"
    SEL_AUTHOR = "div.info a[href*='author']"
    SEL_STATUS = "div.info a[href*='status']"
    SEL_GENRES = "div.info a[href*='genre']"
    SEL_SYNOPSIS = "div.desc-text"
    SEL_CHAPTER_LIST = "#list-chapter li a"
    SEL_CONTENT = "div#chr-content, div#chapter-content"
