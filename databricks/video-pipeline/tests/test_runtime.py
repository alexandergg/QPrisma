from __future__ import annotations

# ruff: noqa: S101
import pytest
from qprisma_video_pipeline import runtime


def test_quote_identifier_wraps_valid_unity_catalog_identifiers() -> None:
    assert runtime.quote_identifier("video_schema_01") == "`video_schema_01`"


@pytest.mark.parametrize("identifier", ["bad-name", "1starts_with_digit", "schema.name"])
def test_quote_identifier_rejects_unsafe_identifiers(identifier: str) -> None:
    with pytest.raises(ValueError, match="Invalid Unity Catalog identifier"):
        runtime.quote_identifier(identifier)


def test_qualified_table_names_include_core_operational_contracts() -> None:
    names = runtime.qualified_table_names("catalog", "schema")

    assert names["qualified_manifest_table"] == "`catalog`.`schema`.`video_media_manifest`"
    assert names["qualified_outbox_table"] == "`catalog`.`schema`.`video_pipeline_outbox`"
    assert names["qualified_gold_processing_results_table"] == "`catalog`.`schema`.`video_processing_results`"


def test_public_namespace_exposes_runtime_helpers_and_contracts() -> None:
    namespace = runtime.public_namespace()

    assert namespace["quote_identifier"] is runtime.quote_identifier
    assert namespace["PIPELINE_STAGES"][0] == "register_manifest"
