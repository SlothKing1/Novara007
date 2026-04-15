"""Tests for QualityScorer."""

import pytest

from novara.cleaning.quality_scorer import QualityScorer


@pytest.fixture
def scorer() -> QualityScorer:
    return QualityScorer()


def test_empty_chapter_scores_zero(scorer: QualityScorer) -> None:
    signals = scorer.score_chapter([], 0)
    assert signals.final_score == 0.0
    assert "empty content" in signals.notes


def test_short_chapter_penalised(scorer: QualityScorer) -> None:
    paras = ["Short text."]
    signals = scorer.score_chapter(paras, 2)
    assert signals.final_score < 0.5
    assert any("short" in note for note in signals.notes)


def test_single_blob_paragraph_penalised(scorer: QualityScorer) -> None:
    # One massive paragraph
    blob = " ".join(["word"] * 1000)
    signals = scorer.score_chapter([blob], 1000)
    assert signals.structure_score < 0.5
    assert any("blob" in note for note in signals.notes)


def test_good_chapter_scores_well(scorer: QualityScorer) -> None:
    paras = [
        "The sky was clear. Stars dotted the night.",
        "Han Xiao moved carefully through the grass.",
        "He had come prepared for this mission.",
        "The enemy camp was two hundred meters ahead.",
        "He signalled to his team and they advanced.",
    ] * 6  # 30 paragraphs
    word_count = sum(len(p.split()) for p in paras)
    signals = scorer.score_chapter(paras, word_count)
    assert signals.final_score > 0.6


def test_boilerplate_lowers_score(scorer: QualityScorer) -> None:
    paras = [
        "Good chapter text here. " * 10,
        "Please read on our website for more.",
        "Support us on Patreon to get more chapters.",
        "Stolen content! This chapter was stolen!",
    ]
    word_count = sum(len(p.split()) for p in paras)
    signals = scorer.score_chapter(paras, word_count)
    assert signals.boilerplate_hits > 0
    assert signals.cleanliness_score < 1.0


def test_metadata_completeness_full(scorer: QualityScorer) -> None:
    metadata = {
        "title": "The Novel",
        "synopsis": "A long synopsis.",
        "author": "Author Name",
        "status": "ongoing",
        "cover_url": "https://example.com/cover.jpg",
        "genres": ["Fantasy", "Action"],
        "original_title": "原著",
        "original_language": "zh",
        "translator_group": "WuxiaWorld",
        "total_chapters": 1000,
        "release_year": 2020,
        "tags": ["op-mc", "leveling"],
    }
    score = scorer.score_metadata_completeness(metadata)
    assert score > 0.9


def test_metadata_completeness_minimal(scorer: QualityScorer) -> None:
    metadata = {"title": "A Title"}
    score = scorer.score_metadata_completeness(metadata)
    assert score < 0.5


def test_metadata_completeness_empty(scorer: QualityScorer) -> None:
    score = scorer.score_metadata_completeness({})
    assert score == 0.0
