"""Tests for services.graph.cypher_filters — keyword sanitization and filter builders."""

from services.graph.cypher_filters import (
    MAX_KEYWORDS,
    MIN_KEYWORD_LENGTH,
    build_keyword_filter,
    sanitize_keywords,
)


class TestSanitizeKeywords:
    """Tests for sanitize_keywords()."""

    def test_basic_split(self):
        result = sanitize_keywords("the quick brown fox jumps")
        assert result == ["the", "quick", "brown", "fox", "jumps"]

    def test_strips_special_characters(self):
        result = sanitize_keywords("hello' OR 1=1 --world")
        # "OR" and "1=1" stripped; "hello" and "world" kept
        assert "hello" in result
        assert "world" in result
        # None contain injection chars
        for kw in result:
            assert "'" not in kw
            assert "=" not in kw
            assert "-" not in kw

    def test_filters_short_keywords(self):
        result = sanitize_keywords("I am a big cat")
        # "I", "am", "a" are < 3 chars, filtered out
        assert result == ["big", "cat"]

    def test_custom_min_length(self):
        result = sanitize_keywords("go run it now", min_length=2)
        assert "go" in result
        assert "run" in result

    def test_max_keywords_cap(self):
        text = " ".join(f"word{i}" for i in range(20))
        result = sanitize_keywords(text)
        assert len(result) == MAX_KEYWORDS

    def test_custom_max_keywords(self):
        text = "alpha beta gamma delta epsilon"
        result = sanitize_keywords(text, max_keywords=2)
        assert len(result) == 2

    def test_empty_input(self):
        assert sanitize_keywords("") == []

    def test_only_short_words(self):
        assert sanitize_keywords("a I me") == []

    def test_unicode_preserved(self):
        result = sanitize_keywords("café résumé naïve")
        assert len(result) == 3
        assert "café" in result

    def test_min_length_default(self):
        assert MIN_KEYWORD_LENGTH == 3


class TestBuildKeywordFilter:
    """Tests for build_keyword_filter()."""

    def test_with_keywords_returns_any_predicate(self):
        result = build_keyword_filter("f.description", ["hello", "world"])
        assert "ANY(kw IN $keywords" in result
        assert "f.description" in result
        assert "CONTAINS" in result

    def test_without_keywords_returns_fallback(self):
        result = build_keyword_filter("f.description", [])
        assert "$query_text" in result
        assert "f.description" in result
        assert "ANY" not in result

    def test_custom_fallback_param(self):
        result = build_keyword_filter("a.text", [], fallback_param="$search_term")
        assert "$search_term" in result

    def test_property_expr_in_output(self):
        result = build_keyword_filter("node.prop", ["test"])
        assert "node.prop" in result

    def test_keywords_produce_tolower(self):
        result = build_keyword_filter("x.y", ["foo"])
        assert "toLower(kw)" in result
        assert "toLower(x.y)" in result
