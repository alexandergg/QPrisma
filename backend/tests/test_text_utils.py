"""Tests for agent.utils.text — shared text cleaning and content validation."""

import pytest

from agent.utils.text import (
    INVALID_CONTENT_PHRASES,
    SCENE_DESCRIPTION_PREFIXES,
    VIDEO_SUMMARY_PREFIXES,
    clean_generated_text,
    is_valid_content,
)


class TestCleanGeneratedText:
    """Tests for clean_generated_text()."""

    def test_returns_unchanged_when_no_cleaning_needed(self):
        assert clean_generated_text("Hello world", ()) == "Hello world"

    def test_strips_leading_list_marker(self):
        assert clean_generated_text("1. Item text", ()) == "Item text"
        assert clean_generated_text("42. Another item", ()) == "Another item"

    def test_strips_bold_list_marker(self):
        assert clean_generated_text("1. **Bold item**", ()) == "Bold item"

    def test_removes_markdown_bold(self):
        assert clean_generated_text("This is **bold** text", ()) == "This is bold text"

    def test_replaces_newlines_with_space(self):
        assert clean_generated_text("line one\nline two", ()) == "line one line two"

    def test_collapses_multiple_whitespace(self):
        assert clean_generated_text("too   many   spaces", ()) == "too many spaces"

    def test_strips_outer_whitespace(self):
        assert clean_generated_text("  padded  ", ()) == "padded"

    def test_strips_matching_prefix(self):
        result = clean_generated_text(
            "General scene description: A park", SCENE_DESCRIPTION_PREFIXES
        )
        assert result == "A park"

    def test_strips_only_first_matching_prefix(self):
        text = "Scene description: General description: nested"
        result = clean_generated_text(text, SCENE_DESCRIPTION_PREFIXES)
        assert result == "General description: nested"

    def test_prefix_case_sensitive(self):
        result = clean_generated_text(
            "general scene description: lowercase", SCENE_DESCRIPTION_PREFIXES
        )
        assert result == "general scene description: lowercase"

    def test_video_summary_prefixes_superset_of_scene(self):
        for p in SCENE_DESCRIPTION_PREFIXES:
            assert p in VIDEO_SUMMARY_PREFIXES

    def test_video_summary_extra_prefixes(self):
        result = clean_generated_text("The image shows a cat", VIDEO_SUMMARY_PREFIXES)
        assert result == "a cat"

    def test_empty_string(self):
        assert clean_generated_text("", ()) == ""

    def test_combined_cleaning(self):
        text = "1. **General scene description: A\nbeautiful   park**"
        result = clean_generated_text(text, SCENE_DESCRIPTION_PREFIXES)
        assert result == "A beautiful park"

    def test_unicode_preserved(self):
        result = clean_generated_text(
            "Descripción general: café résumé", SCENE_DESCRIPTION_PREFIXES
        )
        assert result == "café résumé"

    def test_spanish_prefix_stripped(self):
        result = clean_generated_text(
            "Descripción general de la escena: Una playa", SCENE_DESCRIPTION_PREFIXES
        )
        assert result == "Una playa"


class TestIsValidContent:
    """Tests for is_valid_content()."""

    def test_valid_description(self):
        assert is_valid_content("A person walking in the park") is True

    def test_empty_string_invalid(self):
        assert is_valid_content("") is False

    def test_none_equivalent_empty(self):
        # Empty string is falsy
        assert is_valid_content("") is False

    @pytest.mark.parametrize("phrase", INVALID_CONTENT_PHRASES)
    def test_each_invalid_phrase_detected(self, phrase):
        assert is_valid_content(f"The frame shows {phrase} content") is False

    def test_case_insensitive_detection(self):
        assert is_valid_content("BLACK SCREEN detected") is False
        assert is_valid_content("Completely Black frame") is False

    def test_partial_match_within_word(self):
        # "no visible" should match as substring
        assert is_valid_content("There is no visible detail") is False

    def test_valid_content_with_similar_but_different_phrase(self):
        assert is_valid_content("The screen shows colorful content") is True

    def test_spanish_invalid_phrases(self):
        assert is_valid_content("Esta es una imagen negra") is False
        assert is_valid_content("La pantalla completamente negra") is False
