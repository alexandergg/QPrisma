from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation_foundry.benchmarks import BenchmarkManifest, BenchmarkVideo
from evaluation_foundry.benchmarks.video_mme.emit_foundry_data import main


def _assert_metadata_values_are_strings(row: dict) -> None:
    metadata = row["metadata"]
    assert metadata, "expected row metadata"
    assert all(isinstance(value, str) for value in metadata.values())
    assert not any(isinstance(value, bool) for value in metadata.values())


def _write_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    manifest = BenchmarkManifest(
        name="video_mme",
        version="test-v0",
        license="academic-only-no-redistribution",
        user_id="bench-user",
        eval_mode="mcq",
        format="letter_only",
        judge_model="",
        videos=[
            BenchmarkVideo(
                benchmark_video_id="vid-1",
                media_id="media-abc",
                duration_bucket="short",
            )
        ],
    )
    manifest_path = tmp_path / "manifest.json"
    manifest.write(manifest_path)

    questions = [
        {
            "video_id": "vid-1",
            "question_id": "q-1",
            "question": "What color?",
            "options": ["Red", "Green", "Blue", "Yellow"],
            "answer": "C",
            "domain": "Perception",
            "sub_category": "color",
        }
    ]
    questions_path = tmp_path / "questions.json"
    questions_path.write_text(json.dumps(questions), encoding="utf-8")
    return manifest_path, questions_path


def _base_args(out: Path, manifest_path: Path, questions_path: Path) -> list[str]:
    return [
        "--manifest",
        str(manifest_path),
        "--questions",
        str(questions_path),
        "--subtitle-modes",
        "without",
        "--out",
        str(out),
    ]


def test_emit_foundry_data_writes_wrapped_json(tmp_path: Path) -> None:
    manifest_path, questions_path = _write_fixtures(tmp_path)
    out = tmp_path / "video-mme-eval.json"

    rc = main(_base_args(out, manifest_path, questions_path))

    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["name"] == "video-mme"
    assert payload["evaluators"] == ["qprisma.video_mme_mcq"]
    assert isinstance(payload["data"], list) and payload["data"], "expected at least one row"
    row = payload["data"][0]
    assert set(row) >= {"query", "ground_truth", "metadata"}
    assert row["ground_truth"] == "C"
    assert row["query"].startswith(
        '[QPRISMA_CONTEXT:{"user_id":"bench-user","media_id":"media-abc",'
        '"media_ids":["media-abc"]}]'
        '[QPRISMA_BENCH:{"eval_mode":"mcq","format":"letter_only",'
    )
    assert row["metadata"]["media_id"] == "media-abc"
    assert row["metadata"]["with_subtitles"] == "false"
    _assert_metadata_values_are_strings(row)


def test_emit_foundry_data_honors_evaluators_and_name_flags(tmp_path: Path) -> None:
    manifest_path, questions_path = _write_fixtures(tmp_path)
    out = tmp_path / "custom.json"

    args = _base_args(out, manifest_path, questions_path) + [
        "--name",
        "custom-eval",
        "--evaluators",
        "qprisma.video_mme_mcq",
        "another.eval",
    ]
    assert main(args) == 0

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["name"] == "custom-eval"
    assert payload["evaluators"] == ["qprisma.video_mme_mcq", "another.eval"]


def test_emit_foundry_data_jsonl_backwards_compat(tmp_path: Path) -> None:
    manifest_path, questions_path = _write_fixtures(tmp_path)
    out = tmp_path / "video-mme-eval.jsonl"

    rc = main(_base_args(out, manifest_path, questions_path))

    assert rc == 0
    lines = [
        json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert lines, "expected at least one JSONL row"
    for row in lines:
        assert set(row) >= {"query", "ground_truth", "metadata"}
        assert row["metadata"]["with_subtitles"] == "false"
        _assert_metadata_values_are_strings(row)


def test_emit_foundry_data_rejects_unknown_suffix(tmp_path: Path) -> None:
    manifest_path, questions_path = _write_fixtures(tmp_path)
    out = tmp_path / "video-mme-eval.txt"

    with pytest.raises(SystemExit, match="must end in .json or .jsonl"):
        main(_base_args(out, manifest_path, questions_path))
