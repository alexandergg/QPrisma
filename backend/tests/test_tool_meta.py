"""Tests for agent.utils.tool_meta — tool response metadata helpers."""

from agent.utils.tool_meta import tool_error, tool_meta, truncate_with_notice


class TestToolMeta:
    """Tests for tool_meta()."""

    def test_defaults(self):
        meta = tool_meta()
        assert meta == {"source": "graph", "is_complete": True}

    def test_custom_source(self):
        meta = tool_meta(source="embedding")
        assert meta["source"] == "embedding"

    def test_incomplete(self):
        meta = tool_meta(is_complete=False)
        assert meta["is_complete"] is False

    def test_truncated_fields(self):
        meta = tool_meta(truncated_fields=["description", "summary"])
        assert meta["truncated_fields"] == ["description", "summary"]

    def test_truncated_fields_omitted_when_none(self):
        meta = tool_meta(truncated_fields=None)
        assert "truncated_fields" not in meta

    def test_truncated_fields_omitted_when_empty(self):
        meta = tool_meta(truncated_fields=[])
        assert "truncated_fields" not in meta

    def test_result_count(self):
        meta = tool_meta(result_count=5)
        assert meta["result_count"] == 5

    def test_result_count_zero(self):
        meta = tool_meta(result_count=0)
        assert meta["result_count"] == 0

    def test_total_available_shown_when_different(self):
        meta = tool_meta(result_count=5, total_available=20)
        assert meta["total_available"] == 20

    def test_total_available_hidden_when_equal(self):
        meta = tool_meta(result_count=5, total_available=5)
        assert "total_available" not in meta

    def test_total_available_hidden_when_none(self):
        meta = tool_meta(result_count=5, total_available=None)
        assert "total_available" not in meta

    def test_all_fields_together(self):
        meta = tool_meta(
            source="search",
            is_complete=False,
            truncated_fields=["body"],
            result_count=3,
            total_available=100,
        )
        assert meta == {
            "source": "search",
            "is_complete": False,
            "truncated_fields": ["body"],
            "result_count": 3,
            "total_available": 100,
        }


class TestTruncateWithNotice:
    """Tests for truncate_with_notice()."""

    def test_short_text_unchanged(self):
        text, was_truncated = truncate_with_notice("hello", 10)
        assert text == "hello"
        assert was_truncated is False

    def test_exact_limit_not_truncated(self):
        text, was_truncated = truncate_with_notice("12345", 5)
        assert text == "12345"
        assert was_truncated is False

    def test_over_limit_truncated(self):
        text, was_truncated = truncate_with_notice("1234567890", 5)
        assert was_truncated is True
        assert text.startswith("12345")
        assert "5 chars omitted" in text

    def test_truncation_notice_format(self):
        text, _ = truncate_with_notice("abcdefghij", 3)
        assert text == "abc […7 chars omitted]"

    def test_empty_string(self):
        text, was_truncated = truncate_with_notice("", 10)
        assert text == ""
        assert was_truncated is False

    def test_none_input(self):
        text, was_truncated = truncate_with_notice(None, 10)
        assert text is None
        assert was_truncated is False

    def test_limit_of_one(self):
        text, was_truncated = truncate_with_notice("ab", 1)
        assert was_truncated is True
        assert text.startswith("a")


class TestToolError:
    """Tests for tool_error()."""

    def test_basic_error(self):
        result = tool_error("not_found", "Video not found")
        assert result["error"]["type"] == "not_found"
        assert result["error"]["message"] == "Video not found"
        assert result["_meta"]["is_complete"] is False
        assert result["_meta"]["result_count"] == 0

    def test_default_source(self):
        result = tool_error("timeout", "Request timed out")
        assert result["_meta"]["source"] == "error"

    def test_custom_source(self):
        result = tool_error("timeout", "Request timed out", source="neo4j")
        assert result["_meta"]["source"] == "neo4j"

    def test_recovery_hint(self):
        result = tool_error("not_found", "No data", recovery="Try a broader search")
        assert result["error"]["recovery"] == "Try a broader search"

    def test_recovery_omitted_when_none(self):
        result = tool_error("not_found", "No data")
        assert "recovery" not in result["error"]

    def test_partial_data(self):
        partial = {"scenes": [{"id": 1}]}
        result = tool_error("timeout", "Partial results", partial_data=partial)
        assert result["partial_data"] == partial

    def test_partial_data_omitted_when_none(self):
        result = tool_error("timeout", "No results")
        assert "partial_data" not in result

    def test_full_error_response(self):
        result = tool_error(
            "partial_failure",
            "Some results missing",
            recovery="Retry with smaller scope",
            partial_data={"count": 3},
            source="graph",
        )
        assert result == {
            "error": {
                "type": "partial_failure",
                "message": "Some results missing",
                "recovery": "Retry with smaller scope",
            },
            "partial_data": {"count": 3},
            "_meta": {"source": "graph", "is_complete": False, "result_count": 0},
        }
