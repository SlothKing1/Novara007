"""Tests for BoilerplateCleaner."""

import pytest

from novara.cleaning.cleaners.boilerplate_cleaner import BoilerplateCleaner


@pytest.fixture
def cleaner() -> BoilerplateCleaner:
    return BoilerplateCleaner()


def test_removes_translator_note(cleaner: BoilerplateCleaner) -> None:
    paras = ["Chapter text here.", "TL Note: This is a note.", "More text."]
    result = cleaner.clean(paras)
    assert "TL Note: This is a note." not in result
    assert "Chapter text here." in result


def test_removes_editor_note(cleaner: BoilerplateCleaner) -> None:
    paras = ["Story.", "Editor's Note: Fixed typos.", "Continued."]
    result = cleaner.clean(paras)
    assert "Editor's Note: Fixed typos." not in result


def test_removes_chapter_end_marker(cleaner: BoilerplateCleaner) -> None:
    paras = ["The end was near.", "--- End of Chapter ---", "Next: something"]
    result = cleaner.clean(paras)
    assert all("End of Chapter" not in p for p in result)


def test_removes_read_on_site(cleaner: BoilerplateCleaner) -> None:
    paras = [
        "He walked forward.",
        "Read the latest novel updates on novelbin.com",
        "She followed.",
    ]
    result = cleaner.clean(paras)
    assert len(result) == 2


def test_removes_bare_chapter_heading(cleaner: BoilerplateCleaner) -> None:
    paras = ["Chapter 42", "The story continues here.", "Chapter 43"]
    result = cleaner.clean(paras)
    # Only bare headings should be removed, not inline ones
    assert "The story continues here." in result
    assert "Chapter 42" not in result


def test_preserves_valid_paragraphs(cleaner: BoilerplateCleaner) -> None:
    paras = [
        "The wind swept across the plains.",
        "It carried the scent of war.",
        "He had survived this before.",
    ]
    result = cleaner.clean(paras)
    assert result == paras


def test_removes_patreon_line(cleaner: BoilerplateCleaner) -> None:
    paras = ["Action scene.", "Support us on Patreon!", "More action."]
    result = cleaner.clean(paras)
    assert "Support us on Patreon!" not in result


def test_removes_very_short_paragraphs(cleaner: BoilerplateCleaner) -> None:
    paras = ["Valid long paragraph here.", ".", "Another valid paragraph."]
    result = cleaner.clean(paras)
    assert "." not in result
