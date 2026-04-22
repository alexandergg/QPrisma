from __future__ import annotations

import json

import pytest

from evaluation_foundry.benchmarks.video_mme.emit_foundry_data import _load_questions
from evaluation_foundry.benchmarks.video_mme.file_validation import validate_staged_dataset_file
from evaluation_foundry.benchmarks.video_mme.ingest import _load_metadata


def test_validate_staged_dataset_file_rejects_html_saved_as_parquet(tmp_path) -> None:
    path = tmp_path / "questions.parquet"
    path.write_text("<!DOCTYPE html><html><body>AccessDenied</body></html>", encoding="utf-8")

    with pytest.raises(RuntimeError, match="does not look like parquet"):
        validate_staged_dataset_file(path, label="Video-MME questions file")


def test_load_metadata_surfaces_actionable_error_for_invalid_parquet(tmp_path) -> None:
    path = tmp_path / "questions.parquet"
    path.write_text("<html><body>BlobNotFound</body></html>", encoding="utf-8")

    with pytest.raises(RuntimeError, match="expired SAS URL|Hugging Face page URL"):
        _load_metadata(path)


def test_load_questions_surfaces_actionable_error_for_invalid_parquet(tmp_path) -> None:
    path = tmp_path / "questions.parquet"
    path.write_text("<?xml version='1.0'?><Error>AuthenticationFailed</Error>", encoding="utf-8")

    with pytest.raises(RuntimeError, match="does not look like parquet"):
        _load_questions(path)


def test_load_questions_accepts_json_payload(tmp_path) -> None:
    path = tmp_path / "questions.json"
    path.write_text(json.dumps([{"video_id": "vid-1", "question": "What?"}]), encoding="utf-8")

    rows = _load_questions(path)

    assert rows == [{"video_id": "vid-1", "question": "What?"}]


def test_load_questions_preserves_empty_questions_list_in_json_payload(tmp_path) -> None:
    path = tmp_path / "questions.json"
    path.write_text(
        json.dumps({"questions": [], "videos": [{"video_id": "vid-1"}]}), encoding="utf-8"
    )

    rows = _load_questions(path)

    assert rows == []


@pytest.mark.parametrize("loader", [_load_metadata, _load_questions])
def test_parquet_loaders_wrap_corrupt_parquet_errors(tmp_path, loader) -> None:
    pytest.importorskip("pyarrow")

    path = tmp_path / "questions.parquet"
    path.write_bytes(b"PAR1not-a-real-parquet-filePAR1")

    with pytest.raises(RuntimeError, match="raw parquet bytes"):
        loader(path)


def _write_metadata_json(tmp_path, rows):
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_load_metadata_uses_youtube_id_for_filename(tmp_path) -> None:
    path = _write_metadata_json(
        tmp_path,
        [
            {
                "video_id": "838",
                "videoID": "fFjv93ACGo8",
                "duration": "short",
            }
        ],
    )

    records = _load_metadata(path)

    assert len(records) == 1
    assert records[0].video_id == "838"
    assert records[0].filename == "fFjv93ACGo8.mp4"


def test_load_metadata_explicit_filename_wins_over_youtube_id(tmp_path) -> None:
    path = _write_metadata_json(
        tmp_path,
        [
            {
                "video_id": "001",
                "videoID": "fFjv93ACGo8",
                "filename": "custom-name.mp4",
                "duration": "short",
            }
        ],
    )

    records = _load_metadata(path)

    assert records[0].filename == "custom-name.mp4"


def test_load_metadata_falls_back_to_video_id_when_no_youtube_id(tmp_path) -> None:
    path = _write_metadata_json(
        tmp_path,
        [
            {
                "video_id": "042",
                "duration": "medium",
            }
        ],
    )

    records = _load_metadata(path)

    assert records[0].filename == "042.mp4"
