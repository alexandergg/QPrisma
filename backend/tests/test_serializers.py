"""
Tests for core/serializers.py

Covers numpy type conversion with standard tests and Hypothesis property-based testing.
"""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.serializers import sanitize_for_json

# =============================================================================
# Standard Tests
# =============================================================================


@pytest.mark.unit
class TestSanitizeForJson:
    def test_numpy_int(self):
        result = sanitize_for_json(np.int64(42))
        assert result == 42
        assert isinstance(result, int)

    def test_numpy_float(self):
        result = sanitize_for_json(np.float64(3.14))
        assert result == pytest.approx(3.14)
        assert isinstance(result, float)

    def test_numpy_array(self):
        result = sanitize_for_json(np.array([1, 2, 3]))
        assert result == [1, 2, 3]
        assert isinstance(result, list)

    def test_nested_dict(self):
        data = {"count": np.int32(5), "scores": np.array([0.1, 0.2])}
        result = sanitize_for_json(data)
        assert result["count"] == 5
        assert isinstance(result["count"], int)
        assert result["scores"] == [pytest.approx(0.1), pytest.approx(0.2)]

    def test_nested_list(self):
        data = [np.float32(1.0), {"val": np.int16(2)}]
        result = sanitize_for_json(data)
        assert isinstance(result[0], float)
        assert isinstance(result[1]["val"], int)

    def test_plain_types_unchanged(self):
        assert sanitize_for_json(42) == 42
        assert sanitize_for_json("hello") == "hello"
        assert sanitize_for_json(3.14) == 3.14
        assert sanitize_for_json(True) is True
        assert sanitize_for_json(None) is None

    def test_empty_dict(self):
        assert sanitize_for_json({}) == {}

    def test_empty_list(self):
        assert sanitize_for_json([]) == []

    def test_deeply_nested(self):
        data = {"a": {"b": {"c": np.int64(99)}}}
        result = sanitize_for_json(data)
        assert result["a"]["b"]["c"] == 99
        assert isinstance(result["a"]["b"]["c"], int)

    def test_2d_numpy_array(self):
        arr = np.array([[1, 2], [3, 4]])
        result = sanitize_for_json(arr)
        assert result == [[1, 2], [3, 4]]


# =============================================================================
# Property-Based Tests with Hypothesis
# =============================================================================


@pytest.mark.unit
class TestSanitizePropertyBased:
    @given(st.integers(min_value=-1000, max_value=1000))
    @settings(max_examples=50)
    def test_numpy_int_roundtrip(self, n):
        result = sanitize_for_json(np.int64(n))
        assert result == n
        assert isinstance(result, int)

    @given(st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6))
    @settings(max_examples=50)
    def test_numpy_float_roundtrip(self, f):
        result = sanitize_for_json(np.float64(f))
        assert result == pytest.approx(f)
        assert isinstance(result, float)

    @given(st.lists(st.integers(min_value=-100, max_value=100), max_size=20))
    @settings(max_examples=30)
    def test_numpy_array_roundtrip(self, lst):
        arr = np.array(lst)
        result = sanitize_for_json(arr)
        assert result == lst
        assert isinstance(result, list)
