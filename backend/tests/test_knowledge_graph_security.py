"""
Security tests for Knowledge Graph Service.

Validates that Cypher injection vectors in search_multimodal are mitigated.
"""

import re
from unittest.mock import MagicMock, patch


class TestSearchMultimodalInjectionPrevention:
    """Verify search_multimodal parameterizes keywords and sanitizes input."""

    def _make_service(self):
        """Create a KnowledgeGraphService with mocked Neo4j driver."""
        with patch("services.knowledge_graph.settings") as mock_settings:
            mock_settings.neo4j.uri = "bolt://localhost:7687"
            mock_settings.neo4j.username = "neo4j"
            mock_settings.neo4j.password = "test"
            mock_settings.neo4j.database = "neo4j"
            mock_settings.neo4j.enabled = True

            from services.knowledge_graph import KnowledgeGraphService

            svc = KnowledgeGraphService.__new__(KnowledgeGraphService)
            svc.uri = "bolt://localhost:7687"
            svc.database = "neo4j"
            svc._driver = MagicMock()
            svc._connected = True
            svc._schema_initialized = True
            svc.nodes = MagicMock()
            svc.expander = MagicMock()
            return svc

    def _capture_queries(self, svc):
        """Set up mock session to capture all Cypher queries executed."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        svc._driver.session.return_value = mock_session
        return mock_session

    def test_keywords_are_parameterized_not_interpolated(self):
        """Keywords must be passed via $keywords parameter, not string interpolation."""
        svc = self._make_service()
        mock_session = self._capture_queries(svc)

        svc.search_multimodal("hello world test")

        # Verify session.run was called with keywords as parameter
        for call in mock_session.run.call_args_list:
            query = call[0][0]
            kwargs = call[1]

            # The query must NOT contain literal keyword strings
            assert "hello" not in query, "Keyword 'hello' interpolated into Cypher query"
            assert "world" not in query, "Keyword 'world' interpolated into Cypher query"

            # Must use parameterized $keywords
            assert "$keywords" in query, "Query does not use parameterized $keywords"
            assert "keywords" in kwargs, "keywords not passed as parameter"

    def test_injection_attempt_single_quote(self):
        """Single-quote injection attempts must be sanitized out of keywords."""
        svc = self._make_service()
        mock_session = self._capture_queries(svc)

        # Attempt: close the string literal and inject DETACH DELETE
        malicious = "test' OR 1=1}) DETACH DELETE (n) //"
        svc.search_multimodal(malicious)

        for call in mock_session.run.call_args_list:
            query = call[0][0]
            kwargs = call[1]

            # Query must not contain injected Cypher
            assert "DETACH DELETE" not in query
            assert "OR 1=1" not in query

            # Keywords parameter must have sanitized values (no quotes/special chars)
            for kw in kwargs.get("keywords", []):
                assert "'" not in kw, f"Single quote found in keyword: {kw}"
                assert "}" not in kw, f"Closing brace found in keyword: {kw}"

    def test_injection_attempt_double_quote(self):
        """Double-quote injection must be sanitized."""
        svc = self._make_service()
        mock_session = self._capture_queries(svc)

        malicious = 'test" RETURN apoc.export.csv.all("file:///etc/passwd")'
        svc.search_multimodal(malicious)

        for call in mock_session.run.call_args_list:
            query = call[0][0]
            assert "apoc.export" not in query
            assert "file:///" not in query

    def test_injection_attempt_backtick(self):
        """Backtick injection must be sanitized."""
        svc = self._make_service()
        mock_session = self._capture_queries(svc)

        malicious = "test` CALL db.labels() YIELD label //"
        svc.search_multimodal(malicious)

        for call in mock_session.run.call_args_list:
            query = call[0][0]
            assert "CALL db.labels" not in query

    def test_keyword_count_limited_to_five(self):
        """Only the first 5 valid keywords should be used."""
        svc = self._make_service()
        mock_session = self._capture_queries(svc)

        # 10 keywords, all > 2 chars
        svc.search_multimodal("alpha bravo charlie delta echo foxtrot golf hotel india juliet")

        for call in mock_session.run.call_args_list:
            kwargs = call[1]
            keywords = kwargs.get("keywords", [])
            assert len(keywords) <= 5, f"Expected <=5 keywords, got {len(keywords)}"

    def test_short_keywords_are_filtered(self):
        """Keywords with <= 2 characters should be excluded."""
        svc = self._make_service()
        mock_session = self._capture_queries(svc)

        svc.search_multimodal("a an the test data")

        for call in mock_session.run.call_args_list:
            kwargs = call[1]
            keywords = kwargs.get("keywords", [])
            for kw in keywords:
                assert len(kw) > 2, f"Short keyword passed through: '{kw}'"

    def test_special_characters_stripped_from_keywords(self):
        """Non-word characters must be stripped from keywords."""
        svc = self._make_service()
        mock_session = self._capture_queries(svc)

        svc.search_multimodal("hello! world@ test#$%")

        for call in mock_session.run.call_args_list:
            kwargs = call[1]
            keywords = kwargs.get("keywords", [])
            for kw in keywords:
                assert re.match(r"^[\w\s]+$", kw), f"Special chars in keyword: '{kw}'"

    def test_empty_query_uses_query_text_param(self):
        """When no keywords extracted, fallback to $query_text parameter."""
        svc = self._make_service()
        mock_session = self._capture_queries(svc)

        svc.search_multimodal("a b c")  # All <= 2 chars

        for call in mock_session.run.call_args_list:
            query = call[0][0]
            assert "$query_text" in query, "Empty keywords should fallback to $query_text"
