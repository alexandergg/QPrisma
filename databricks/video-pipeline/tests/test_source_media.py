from __future__ import annotations

# ruff: noqa: S101
import pytest
from qprisma_video_pipeline import source_media


def test_validate_volume_path_accepts_uc_paths_without_query_strings() -> None:
    assert (
        source_media.validate_volume_path("/Volumes/catalog/schema/video/source.mp4", "volume_path")
        == "/Volumes/catalog/schema/video/source.mp4"
    )


@pytest.mark.parametrize(
    "path",
    [
        "/Volumes/catalog/schema/video/source.mp4?sig=redacted",
        "https://storage.blob.core.windows.net/video/source.mp4",
    ],
)
def test_validate_volume_path_rejects_non_uc_or_signed_paths(path: str) -> None:
    with pytest.raises(ValueError, match="source_media.volume_path"):
        source_media.validate_volume_path(path, "volume_path")


def test_validate_cloud_uri_rejects_embedded_credentials() -> None:
    with pytest.raises(ValueError, match="embedded credentials"):
        source_media.validate_cloud_uri("https://user@example.blob.core.windows.net/container/blob.mp4", "uri")


def test_source_media_uri_prefers_staged_volume_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        source_media,
        "source_media",
        {
            "volume_path": "/Volumes/catalog/schema/video_artifacts/media-1/source.mp4",
            "uri": "abfss://raw@account.dfs.core.windows.net/ignored.mp4",
        },
        raising=False,
    )
    monkeypatch.setattr(source_media, "blob_name", "ignored.mp4", raising=False)

    assert source_media.source_media_uri() == "/Volumes/catalog/schema/video_artifacts/media-1/source.mp4"


def test_source_media_uri_builds_abfss_uri_from_dfs_storage_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        source_media,
        "source_media",
        {
            "container_name": "raw",
            "blob_name": "/videos/source.mp4",
            "storage_account_url": "https://qprisma.dfs.core.windows.net",
        },
        raising=False,
    )
    monkeypatch.setattr(source_media, "blob_name", "", raising=False)

    assert source_media.source_media_uri() == "abfss://raw@qprisma.dfs.core.windows.net/videos/source.mp4"


def test_validate_source_contract_requires_managed_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        source_media,
        "source_media",
        {"auth": {"mode": "account_key"}, "volume_path": "/Volumes/catalog/schema/video/source.mp4"},
        raising=False,
    )

    with pytest.raises(ValueError, match="managed_identity"):
        source_media.validate_source_contract()
