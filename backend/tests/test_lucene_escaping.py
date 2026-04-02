"""
Unit tests for Lucene query sanitisation and fulltext search hardening.

Covers:
1. Special character escaping for all Lucene operators
2. Empty / whitespace-only query rejection
3. Max-length truncation
4. Integration with _fulltext_search via mocked Neo4j session
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.graph_search_queries import sanitize_fulltext_query

# ---------------------------------------------------------------------------
# sanitize_fulltext_query — pure function tests
# ---------------------------------------------------------------------------


class TestSanitizeFulltextQuery:
    """Verify Lucene special character escaping and input validation."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            # Each Lucene special character individually
            ("hello+world", r"hello\+world"),
            ("hello-world", r"hello\-world"),
            ("foo&&bar", r"foo\&\&bar"),
            ("foo||bar", r"foo\|\|bar"),
            ("!important", r"\!important"),
            ("(group)", r"\(group\)"),
            ("{set}", r"\{set\}"),
            ("[range]", r"\[range\]"),
            ("score^2", r"score\^2"),
            ('"quoted"', r"\"quoted\""),
            ("wild~", r"wild\~"),
            ("star*", r"star\*"),
            ("question?", r"question\?"),
            ("field:value", r"field\:value"),
            ("back\\slash", r"back\\slash"),
            ("path/to", r"path\/to"),
            # Compound: the exact pattern that was crashing evaluation
            (
                "Answer with just the letter (A/B/C/D).",
                r"Answer with just the letter \(A\/B\/C\/D\).",
            ),
            # Multiple specials in sequence
            ("a+b-c*d?e:f", r"a\+b\-c\*d\?e\:f"),
        ],
    )
    def test_escapes_special_characters(self, raw: str, expected: str):
        assert sanitize_fulltext_query(raw) == expected

    def test_plain_text_unchanged(self):
        assert sanitize_fulltext_query("hello world") == "hello world"

    def test_none_input(self):
        assert sanitize_fulltext_query("") is None

    def test_whitespace_only(self):
        assert sanitize_fulltext_query("   ") is None
        assert sanitize_fulltext_query("\t\n") is None

    def test_strips_leading_trailing_whitespace(self):
        result = sanitize_fulltext_query("  hello  ")
        assert result == "hello"

    def test_max_length_truncation(self):
        long_query = "a" * 2000
        result = sanitize_fulltext_query(long_query, max_length=100)
        assert result is not None
        assert len(result) == 100

    def test_custom_max_length(self):
        result = sanitize_fulltext_query("hello world", max_length=5)
        assert result == "hello"


# ---------------------------------------------------------------------------
# _fulltext_search — integration with sanitisation
# ---------------------------------------------------------------------------


class TestFulltextSearchIntegration:
    """Verify _fulltext_search uses sanitised queries and handles edge cases."""

    def _make_service(self):
        from services.graph_search_service import GraphSearchService

        mock_graph = MagicMock()
        mock_embedding = MagicMock()
        svc = GraphSearchService(
            graph_service=mock_graph,
            embedding_service=mock_embedding,
        )
        return svc, mock_graph

    def test_empty_query_returns_empty(self):
        from models.graph_models import NodeType

        svc, _ = self._make_service()
        result = svc._fulltext_search("", NodeType.FRAME, 10, video_id="v1")
        assert result == []

    def test_unsupported_node_type_returns_empty(self):
        from models.graph_models import NodeType

        svc, _ = self._make_service()
        # VIDEO is not in _INDEX_BY_TYPE
        result = svc._fulltext_search("test", NodeType.VIDEO, 10, video_id="v1")
        assert result == []

    def test_escaped_query_passed_to_neo4j(self):
        from models.graph_models import NodeType

        svc, mock_graph = self._make_service()
        mock_session = MagicMock()
        mock_graph.get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_graph.get_session.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = []

        svc._fulltext_search("(A/B/C/D)", NodeType.FRAME, 10, video_id="v1")

        call_args = mock_session.run.call_args
        params = call_args.kwargs if call_args.kwargs else {}
        # If passed as **params, check positional
        if not params and len(call_args.args) > 1:
            # session.run(query, **params) — params in kwargs
            pass
        # The query_text param should be escaped
        actual_query_text = call_args.kwargs.get("query_text") or call_args[1].get("query_text", "")
        assert r"\(" in actual_query_text or r"\/" in actual_query_text
