"""HtmlCleaner — strips unsafe/noisy HTML and returns clean plain paragraphs."""

from __future__ import annotations

import re

import bleach
from bs4 import BeautifulSoup, NavigableString, Tag

# Tags we keep; everything else is stripped (content preserved)
ALLOWED_TAGS: list[str] = [
    "p",
    "br",
    "em",
    "strong",
    "i",
    "b",
    "u",
    "span",
    "div",
    "blockquote",
    "hr",
]

# Attributes allowed on kept tags
ALLOWED_ATTRIBUTES: dict[str, list[str]] = {}

# Inline elements that should be treated as text runs (not block separators)
INLINE_TAGS = frozenset({"em", "strong", "i", "b", "u", "span"})

# Block elements that act as paragraph separators
BLOCK_TAGS = frozenset({"p", "div", "blockquote", "section", "article", "li"})


class HtmlCleaner:
    """Converts raw scraped HTML into a list of clean paragraph strings.

    Steps:
    1. Sanitise with bleach (remove scripts, iframes, etc.)
    2. Parse with BeautifulSoup
    3. Walk the tree, emitting paragraph strings
    4. Collapse whitespace within paragraphs
    5. Discard empty paragraphs
    """

    def clean(self, raw_html: str) -> list[str]:
        """Return a list of cleaned paragraph strings from raw HTML.

        Args:
            raw_html: Raw HTML string from the scraper.

        Returns:
            List of non-empty paragraph strings with internal whitespace normalised.
        """
        if not raw_html or not raw_html.strip():
            return []

        sanitised = bleach.clean(
            raw_html,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
            strip=True,
        )

        soup = BeautifulSoup(sanitised, "lxml")
        paragraphs = self._extract_paragraphs(soup)
        return [p for p in paragraphs if p.strip()]

    # ── private ───────────────────────────────────────────────────────────────

    def _extract_paragraphs(self, soup: BeautifulSoup) -> list[str]:
        """Walk the soup tree and collect paragraph text blocks."""
        paragraphs: list[str] = []
        current_parts: list[str] = []

        def flush() -> None:
            text = _normalise_whitespace(" ".join(current_parts))
            if text:
                paragraphs.append(text)
            current_parts.clear()

        def visit(node: Tag | NavigableString) -> None:
            if isinstance(node, NavigableString):
                text = str(node)
                if text.strip():
                    current_parts.append(text.strip())
                return

            if not isinstance(node, Tag):
                return

            tag = node.name.lower() if node.name else ""

            if tag == "br":
                # Line break: flush current accumulation as a paragraph
                flush()
                return

            if tag == "hr":
                flush()
                return

            if tag in BLOCK_TAGS:
                flush()
                for child in node.children:
                    visit(child)  # type: ignore[arg-type]
                flush()
            else:
                # Inline or unknown tag — recurse into children
                for child in node.children:
                    visit(child)  # type: ignore[arg-type]

        for child in soup.body.children if soup.body else soup.children:
            visit(child)  # type: ignore[arg-type]

        flush()
        return paragraphs


def _normalise_whitespace(text: str) -> str:
    """Collapse multiple spaces/tabs/newlines into a single space."""
    return re.sub(r"\s+", " ", text).strip()
