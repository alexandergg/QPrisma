from __future__ import annotations

# ruff: noqa: S101
import pytest
from qprisma_video_pipeline import config


def test_parse_json_object_accepts_object() -> None:
    assert config.parse_json_object('{"mode": "managed_identity"}', "source_media") == {
        "mode": "managed_identity"
    }


@pytest.mark.parametrize("raw_value", ["[]", '"value"', "not json"])
def test_parse_json_object_rejects_non_objects(raw_value: str) -> None:
    with pytest.raises(ValueError, match="source_media"):
        config.parse_json_object(raw_value, "source_media")


def test_validate_no_raw_secrets_rejects_nested_sensitive_keys() -> None:
    payload = {"azure_openai": {"api_key": "literal-value"}}

    with pytest.raises(ValueError, match="raw secret"):
        config.validate_no_raw_secrets(payload)


def test_validate_no_raw_secrets_allows_secret_references() -> None:
    config.validate_no_raw_secrets(
        {
            "azure_openai": {
                "api_key_env": "AZURE_OPENAI_API_KEY",
                "api_key_secret_scope": "qprisma",
                "api_key_secret_key": "openai-key",
            }
        }
    )


def test_filtered_dict_preserves_allowed_scalar_lists_and_nested_keys() -> None:
    filtered = config.filtered_dict(
        {
            "frames": {"max_frames": 5, "unsafe": {"nested": "value"}},
            "tags": ["smoke", "dev"],
            "ignored": "value",
        },
        {"frames", "tags"},
        {"frames": {"max_frames"}},
    )

    assert filtered == {"frames": {"max_frames": 5}, "tags": ["smoke", "dev"]}
