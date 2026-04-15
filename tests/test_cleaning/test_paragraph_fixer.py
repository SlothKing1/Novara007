"""Tests for ParagraphFixer."""

import pytest

from novara.cleaning.cleaners.paragraph_fixer import ParagraphFixer


@pytest.fixture
def fixer() -> ParagraphFixer:
    return ParagraphFixer()


def test_drops_short_paragraphs(fixer: ParagraphFixer) -> None:
    paras = ["OK paragraph here.", "Eh", "Another valid one here."]
    result = fixer.fix(paras)
    assert "Eh" not in result
    assert "OK paragraph here." in result


def test_preserves_normal_paragraphs(fixer: ParagraphFixer) -> None:
    paras = [
        "The sky was dark and the stars were out.",
        "He had been waiting for hours.",
        "Nothing was going to change that.",
    ]
    result = fixer.fix(paras)
    assert result == paras


def test_splits_blob_paragraph() -> None:
    fixer = ParagraphFixer(blob_word_threshold=10)
    # Create a 20+ word paragraph (above our test threshold of 10)
    blob = (
        "First sentence here. Second sentence there. "
        "Third one follows. And a fourth one too. Fifth sentence. Sixth one."
    )
    result = fixer.fix([blob])
    # Should have been split into multiple paragraphs
    assert len(result) > 1


def test_no_split_below_threshold(fixer: ParagraphFixer) -> None:
    # A normal-length paragraph should not be split
    para = "He walked into the room. She was there. They looked at each other."
    result = fixer.fix([para])
    assert len(result) == 1


def test_empty_input(fixer: ParagraphFixer) -> None:
    assert fixer.fix([]) == []
