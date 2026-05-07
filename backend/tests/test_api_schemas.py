"""
Tests for models/api_schemas.py.

Covers request/response model validation, field constraints, and enum values.
"""

import pytest
from pydantic import ValidationError

from models.api_schemas import (
    JobStatus,
    SearchRequest,
)

# =============================================================================
# SearchRequest
# =============================================================================


@pytest.mark.unit
class TestSearchRequest:
    def test_defaults(self):
        req = SearchRequest(query="test")
        assert req.limit == 20
        assert req.media_id is None

    def test_limit_bounds(self):
        req = SearchRequest(query="test", limit=1)
        assert req.limit == 1
        req = SearchRequest(query="test", limit=100)
        assert req.limit == 100

    def test_limit_too_high(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="test", limit=101)

    def test_limit_too_low(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="test", limit=0)


# =============================================================================
# JobStatus
# =============================================================================


@pytest.mark.unit
class TestJobStatus:
    def test_enum_values(self):
        assert JobStatus.PENDING == "pending"
        assert JobStatus.PROCESSING == "processing"
        assert JobStatus.COMPLETED == "completed"
        assert JobStatus.FAILED == "failed"
        assert JobStatus.CANCELLED == "cancelled"

    def test_from_string(self):
        assert JobStatus("pending") == JobStatus.PENDING
        assert JobStatus("completed") == JobStatus.COMPLETED
