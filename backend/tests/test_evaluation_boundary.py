"""Architecture boundary tests for evaluation tooling."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRS = ("api", "agent", "services")
ALLOWED_RUNTIME_IMPORTS = {
    Path("services/benchmark_ingest_service.py"),
}


def _imports_evaluation_foundry(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "evaluation_foundry" or alias.name.startswith("evaluation_foundry.") for alias in node.names):
                return True
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (node.module == "evaluation_foundry" or node.module.startswith("evaluation_foundry."))
        ):
            return True
    return False


@pytest.mark.unit
def test_evaluation_foundry_is_not_imported_by_runtime_hot_path():
    offenders: list[str] = []

    for runtime_dir in RUNTIME_DIRS:
        for path in (BACKEND_ROOT / runtime_dir).rglob("*.py"):
            relative = path.relative_to(BACKEND_ROOT)
            if relative in ALLOWED_RUNTIME_IMPORTS:
                continue
            if _imports_evaluation_foundry(path):
                offenders.append(str(relative))

    assert offenders == []
