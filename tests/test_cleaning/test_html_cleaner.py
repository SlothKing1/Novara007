"""Tests for HtmlCleaner."""

import pytest

from novara.cleaning.cleaners.html_cleaner import HtmlCleaner


@pytest.fixture
def cleaner() -> HtmlCleaner:
    return HtmlCleaner()


def test_basic_paragraphs(cleaner: HtmlCleaner) -> None:
    html = "<p>First paragraph.</p><p>Second paragraph.</p>"
    result = cleaner.clean(html)
    assert result == ["First paragraph.", "Second paragraph."]


def test_strips_script_tags(cleaner: HtmlCleaner) -> None:
    html = "<p>Text</p><script>alert('xss')</script><p>More text</p>"
    result = cleaner.clean(html)
    assert all("script" not in p for p in result)
    assert any("Text" in p for p in result)
    assert any("More text" in p for p in result)


def test_handles_br_tags(cleaner: HtmlCleaner) -> None:
    html = "Line one<br>Line two<br>Line three"
    result = cleaner.clean(html)
    assert len(result) >= 1
    assert any("Line one" in p for p in result)


def test_nested_divs(cleaner: HtmlCleaner) -> None:
    html = "<div><div><p>Inner paragraph.</p></div></div>"
    result = cleaner.clean(html)
    assert "Inner paragraph." in result


def test_empty_input(cleaner: HtmlCleaner) -> None:
    assert cleaner.clean("") == []
    assert cleaner.clean("   ") == []


def test_collapses_whitespace(cleaner: HtmlCleaner) -> None:
    html = "<p>  Too   many    spaces  </p>"
    result = cleaner.clean(html)
    assert result == ["Too many spaces"]


def test_inline_tags_preserved_as_text(cleaner: HtmlCleaner) -> None:
    html = "<p>She was <em>very</em> angry.</p>"
    result = cleaner.clean(html)
    assert result == ["She was very angry."]


def test_strips_images_and_links(cleaner: HtmlCleaner) -> None:
    html = "<p>Text <a href='#'>link</a> and <img src='x.jpg'> image.</p>"
    result = cleaner.clean(html)
    # Link text preserved, img stripped
    assert any("Text" in p for p in result)
    assert all("<img" not in p for p in result)


def test_real_chapter_html(cleaner: HtmlCleaner) -> None:
    html = """
    <div class="chapter-content">
        <p>Han Xiao woke up in a small dormitory.</p>
        <p>The dim light flickered above him.</p>
        <p>He did not know what year it was.</p>
    </div>
    """
    result = cleaner.clean(html)
    assert len(result) == 3
    assert result[0] == "Han Xiao woke up in a small dormitory."
