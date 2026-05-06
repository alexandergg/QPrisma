"""Source-media URI validation and Databricks file probing."""

from __future__ import annotations

from urllib.parse import urlparse

from .contracts import *


def validate_volume_path(path: str, field_name: str) -> str:
    normalized = path.strip()
    if "?" in normalized or "#" in normalized:
        raise ValueError(f"source_media.{field_name} must not include query strings or fragments")
    if normalized.startswith(("dbfs:/Volumes/", "/Volumes/")):
        return normalized
    raise ValueError(f"source_media.{field_name} must be a Unity Catalog volume path")


def validate_no_uri_credentials(uri: str, field_name: str) -> str:
    normalized = uri.strip()
    parsed = urlparse(normalized)
    if parsed.query or parsed.fragment:
        raise ValueError(f"source_media.{field_name} must not include query strings or fragments")
    if parsed.password or (parsed.scheme in {"http", "https"} and parsed.username):
        raise ValueError(f"source_media.{field_name} must not include embedded credentials")
    return normalized


def validate_cloud_uri(uri: str, field_name: str) -> str:
    normalized = validate_no_uri_credentials(uri, field_name)
    if normalized.startswith(("abfss://", "wasbs://")):
        return normalized
    if normalized.startswith(("dbfs:/Volumes/", "/Volumes/")):
        return normalized
    raise ValueError(
        f"source_media.{field_name} must be an abfss:// URI, wasbs:// URI, or Unity Catalog volume path"
    )


def source_media_uri() -> str:
    volume_path = source_media.get("volume_path")
    if volume_path:
        return validate_volume_path(str(volume_path), "volume_path")

    explicit_uri = source_media.get("uri")
    if explicit_uri:
        return validate_cloud_uri(str(explicit_uri), "uri")

    for field_name in ("abfss_uri", "wasbs_uri"):
        explicit_storage_uri = source_media.get(field_name)
        if explicit_storage_uri:
            return validate_cloud_uri(str(explicit_storage_uri), field_name)

    container = str(source_media.get("container_name") or source_media.get("container") or "")
    blob = str(source_media.get("blob_name") or blob_name)
    storage_account_url = str(source_media.get("storage_account_url") or "")
    if not container or not blob or not storage_account_url:
        raise ValueError(
            "source_media must include volume_path, uri, or container_name, blob_name and storage_account_url"
        )

    storage_account_url = validate_no_uri_credentials(storage_account_url, "storage_account_url")
    host = urlparse(storage_account_url).hostname or ""
    account_name = host.split(".")[0]
    if not account_name:
        raise ValueError("source_media.storage_account_url must include a storage account host")

    normalized_blob = blob.lstrip("/")
    if ".dfs." in host:
        return f"abfss://{container}@{account_name}.dfs.core.windows.net/{normalized_blob}"
    return f"wasbs://{container}@{account_name}.blob.core.windows.net/{normalized_blob}"


def validate_source_contract() -> None:
    auth = source_media.get("auth")
    if not isinstance(auth, dict) or auth.get("mode") != "managed_identity":
        raise ValueError("source_media.auth.mode must be 'managed_identity'")
    source_media_uri()


def probe_source_media(uri: str) -> dict:
    rows = (
        spark.read.format("binaryFile")
        .load(uri)
        .select("path", "length", "modificationTime")
        .limit(1)
        .collect()
    )
    if not rows:
        raise FileNotFoundError(f"No readable source media found at {uri}")
    row = rows[0].asDict()
    return {
        "path": row["path"],
        "length": int(row["length"]),
        "modification_time": row["modificationTime"].isoformat(),
    }
