from __future__ import annotations

import pytest

from evaluation_foundry import register_evaluators


def test_validate_code_text_compatibility_rejects_compile_keyword() -> None:
    with pytest.raises(ValueError, match="compile\\("):
        register_evaluators._validate_code_text_compatibility(
            "example.evaluator",
            "import re\nmatcher = re.compile(r'abc')\n",
        )


def test_validate_code_text_compatibility_allows_search_only() -> None:
    register_evaluators._validate_code_text_compatibility(
        "example.evaluator",
        "import re\nre.search(r'abc', 'abcdef')\n",
    )
