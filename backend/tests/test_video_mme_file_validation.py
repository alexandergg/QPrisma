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


@pytest.mark.parametrize("loader", [_load_metadata, _load_questions])
def test_parquet_loaders_wrap_corrupt_parquet_errors(tmp_path, loader) -> None:
    pytest.importorskip("pyarrow")

    path = tmp_path / "questions.parquet"
    path.write_bytes(b"PAR1not-a-real-parquet-filePAR1")

    with pytest.raises(RuntimeError, match="raw parquet bytes"):
        loader(path)
