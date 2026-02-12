"""Tests for services/tool_artifact_service.py."""

from datetime import UTC, datetime
from typing import Any

import pytest

from services.tool_artifact_service import ToolArtifactService


class FakeDownloadStream:
    def __init__(self, payload: bytes):
        self.payload = payload

    def readall(self) -> bytes:
        return self.payload


class FakeBlobClient:
    def __init__(self, storage: dict[str, bytes], key: str):
        self.storage = storage
        self.key = key

    def upload_blob(self, data: bytes, overwrite: bool = False, content_settings: Any = None):
        if not overwrite and self.key in self.storage:
            raise ValueError("Blob already exists")
        self.storage[self.key] = data

    def download_blob(self):
        return FakeDownloadStream(self.storage[self.key])


class FakeBlobServiceClient:
    def __init__(self):
        self.storage: dict[str, bytes] = {}

    def get_blob_client(self, container: str, blob: str):
        return FakeBlobClient(self.storage, f"{container}/{blob}")


class FakeCacheService:
    def __init__(self):
        self.storage: dict[str, bytes] = {}

    async def _get_raw(self, key: str) -> bytes | None:
        return self.storage.get(key)

    async def _set_raw(self, key: str, value: bytes, ttl: int) -> bool:
        self.storage[key] = value
        return True


class FakeArtifactRecord:
    def __init__(self, payload: dict[str, Any]):
        self.__dict__.update(payload)

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        for key in ("created_at", "updated_at", "last_accessed_at"):
            value = data.get(key)
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data


class FakeDatabaseService:
    def __init__(self):
        self.records: dict[str, FakeArtifactRecord] = {}

    def create_tool_artifact(self, artifact_data: dict[str, Any]) -> FakeArtifactRecord:
        now = datetime.now(UTC)
        record = FakeArtifactRecord(
            {
                **artifact_data,
                "created_at": now,
                "updated_at": now,
                "last_accessed_at": now,
            }
        )
        self.records[record.id] = record
        return record

    def get_tool_artifact(self, artifact_id: str) -> FakeArtifactRecord | None:
        return self.records.get(artifact_id)

    def update_tool_artifact_accessed_at(self, artifact_id: str) -> FakeArtifactRecord | None:
        record = self.records.get(artifact_id)
        if record is not None:
            now = datetime.now(UTC)
            record.last_accessed_at = now
            record.updated_at = now
        return record


@pytest.fixture
def artifact_service_fixture():
    db = FakeDatabaseService()
    cache = FakeCacheService()
    blob = FakeBlobServiceClient()
    service = ToolArtifactService(
        database_service=db,
        cache_service=cache,
        blob_service=blob,
        container_name="media-test",
        cache_ttl_seconds=300,
        blob_prefix="tool-artifacts",
        cache_key_prefix="test_tool_artifact",
    )
    return service, db, cache, blob


@pytest.mark.unit
class TestToolArtifactService:
    @pytest.mark.asyncio
    async def test_save_artifact_persists_blob_metadata_and_cache(self, artifact_service_fixture):
        service, db, cache, blob = artifact_service_fixture

        result = await service.save_artifact(
            tool_call_id="call_1",
            tool_name="search_video",
            session_id="session_1",
            payload={"result": "ok", "items": [1, 2, 3]},
            metadata={"query": "what happened"},
        )

        assert result["id"] in db.records
        assert len(blob.storage) == 1
        assert f"test_tool_artifact:{result['id']}" in cache.storage

    @pytest.mark.asyncio
    async def test_get_artifact_reads_from_cache_when_available(self, artifact_service_fixture):
        service, _, cache, blob = artifact_service_fixture

        saved = await service.save_artifact(
            tool_call_id="call_2",
            tool_name="find_entities",
            session_id="session_2",
            payload={"entities": ["alice", "bob"]},
        )

        blob.storage.clear()
        artifact = await service.get_artifact(saved["id"])

        assert artifact is not None
        assert artifact["source"] == "cache"
        assert artifact["payload"] == {"entities": ["alice", "bob"]}
        assert f"test_tool_artifact:{saved['id']}" in cache.storage

    @pytest.mark.asyncio
    async def test_get_artifact_falls_back_to_blob_and_backfills_cache(self, artifact_service_fixture):
        service, _, cache, _ = artifact_service_fixture

        saved = await service.save_artifact(
            tool_call_id="call_3",
            tool_name="tool_x",
            session_id="session_3",
            payload={"nested": {"value": 42}},
        )

        cache.storage.clear()
        artifact = await service.get_artifact(saved["id"])

        assert artifact is not None
        assert artifact["source"] == "blob"
        assert artifact["payload"] == {"nested": {"value": 42}}
        assert f"test_tool_artifact:{saved['id']}" in cache.storage
