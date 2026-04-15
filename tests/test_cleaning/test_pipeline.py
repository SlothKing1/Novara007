"""Integration tests for CleaningPipeline."""

import pytest

from novara.cleaning.pipeline import CleaningPipeline, PIPELINE_VERSION


@pytest.fixture
def pipeline() -> CleaningPipeline:
    return CleaningPipeline()


def test_basic_pipeline_run(pipeline: CleaningPipeline) -> None:
    html = """
    <div class="chapter-content">
        <p>Han Xiao opened his eyes.</p>
        <p>He was reborn.</p>
        <p>The room was cold and dim.</p>
    </div>
    """
    result = pipeline.run(html, content_format="html")
    assert result.paragraph_count == 3
    assert result.word_count > 0
    assert result.pipeline_version == PIPELINE_VERSION
    assert "Han Xiao opened his eyes." in result.paragraphs


def test_pipeline_removes_boilerplate(pipeline: CleaningPipeline) -> None:
    html = """
    <div>
        <p>Chapter 1</p>
        <p>Story begins here.</p>
        <p>TL Note: Special thanks to editor.</p>
        <p>More story here.</p>
    </div>
    """
    result = pipeline.run(html, chapter_title="Chapter 1 — Beginning")
    # TL note and bare chapter heading should be stripped
    assert all("TL Note" not in p for p in result.paragraphs)
    assert "Story begins here." in result.paragraphs


def test_pipeline_heading_dedup(pipeline: CleaningPipeline) -> None:
    html = """
    <div>
        <p>Chapter 1: The Beginning</p>
        <p>Chapter 1: The Beginning</p>
        <p>The story starts here.</p>
    </div>
    """
    result = pipeline.run(html, chapter_title="Chapter 1: The Beginning")
    # Neither duplicate heading should appear
    heading_occurrences = sum(
        1 for p in result.paragraphs if "Chapter 1" in p
    )
    assert heading_occurrences == 0


def test_pipeline_plain_text(pipeline: CleaningPipeline) -> None:
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    result = pipeline.run(text, content_format="text")
    assert result.paragraph_count == 3


def test_pipeline_empty_content(pipeline: CleaningPipeline) -> None:
    result = pipeline.run("")
    assert result.paragraphs == []
    assert result.word_count == 0
    assert result.paragraph_count == 0


def test_pipeline_content_property(pipeline: CleaningPipeline) -> None:
    html = "<p>First.</p><p>Second.</p>"
    result = pipeline.run(html)
    assert result.content == "First.\n\nSecond."


def test_pipeline_unicode_repair(pipeline: CleaningPipeline) -> None:
    # Simulate mojibake / bad encoding
    html = "<p>He said \u201chello\u201d.</p>"
    result = pipeline.run(html)
    assert len(result.paragraphs) == 1
    assert "hello" in result.paragraphs[0]
