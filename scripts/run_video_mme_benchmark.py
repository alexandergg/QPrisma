"""Local helper to run the Video-MME smoke path and dispatch the benchmark workflow."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _run(command: list[str], *, cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(  # noqa: S603 - this helper intentionally shells out to trusted local CLIs
        command,
        cwd=str(cwd) if cwd else None,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout.strip() if capture else ""


def _upload_and_sign(
    *,
    storage_account: str,
    container: str,
    file_path: Path,
    blob_name: str,
    expiry: str,
) -> str:
    _run(
        [
            "az",
            "storage",
            "blob",
            "upload",
            "--auth-mode",
            "login",
            "--overwrite",
            "true",
            "--account-name",
            storage_account,
            "--container-name",
            container,
            "--file",
            str(file_path),
            "--name",
            blob_name,
        ]
    )
    return _run(
        [
            "az",
            "storage",
            "blob",
            "generate-sas",
            "--as-user",
            "--auth-mode",
            "login",
            "--account-name",
            storage_account,
            "--container-name",
            container,
            "--name",
            blob_name,
            "--permissions",
            "r",
            "--https-only",
            "--expiry",
            expiry,
            "--full-uri",
            "-o",
            "tsv",
        ],
        capture=True,
    )


def _trigger_workflow(
    *,
    workflow_file: str,
    manifest_url: str,
    questions_url: str,
    limit: int,
    subtitle_modes: str,
) -> None:
    _run(
        [
            "gh",
            "workflow",
            "run",
            workflow_file,
            "-f",
            "mode=eval-only",
            "-f",
            f"manifest-url={manifest_url}",
            "-f",
            f"questions-url={questions_url}",
            "-f",
            f"limit={limit}",
            "-f",
            f"subtitle-modes={subtitle_modes}",
        ]
    )


def _wait_for_latest_run(workflow_file: str) -> None:
    time.sleep(10)
    while True:
        payload = _run(
            [
                "gh",
                "run",
                "list",
                "--workflow",
                workflow_file,
                "--limit",
                "1",
                "--json",
                "databaseId,status,conclusion,url",
            ],
            capture=True,
        )
        runs = json.loads(payload)
        if not runs:
            raise RuntimeError("Could not find the dispatched workflow run")
        run = runs[0]
        print(f"Workflow status: {run['status']} ({run.get('conclusion')})")
        print(run["url"])
        if run["status"] == "completed":
            if run.get("conclusion") != "success":
                raise RuntimeError(f"Workflow failed with conclusion={run.get('conclusion')}")
            return
        time.sleep(30)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run local Video-MME ingest, upload manifest/questions, and dispatch the benchmark workflow.",
    )
    parser.add_argument("--videos-dir", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--storage-account", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--workflow-file", default="benchmark-video-mme.yml")
    parser.add_argument(
        "--manifest-path", type=Path, default=Path("data/datasets/_private/video_mme/manifest.json")
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--subtitle-modes", default="without")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--wait", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    backend_dir = repo_root / "backend"

    if not args.skip_ingest:
        _run(
            [
                sys.executable,
                "-m",
                "evaluation_foundry.benchmarks.video_mme.ingest",
                "--videos-dir",
                str(args.videos_dir),
                "--metadata",
                str(args.metadata),
                "--preset",
                "benchmark",
                "--limit",
                str(args.limit),
                "--stratify-by",
                "duration_bucket",
                "--seed",
                "42",
                "--manifest-out",
                str(args.manifest_path),
            ],
            cwd=backend_dir,
        )

    if not args.manifest_path.is_file():
        raise FileNotFoundError(f"Manifest not found: {args.manifest_path}")

    expiry = (datetime.now(UTC) + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%MZ")
    run_prefix = datetime.now(UTC).strftime("video-mme/smoke/%Y%m%dT%H%M%SZ")
    manifest_blob = f"{run_prefix}/manifest.json"
    questions_blob = f"{run_prefix}/{args.metadata.name}"

    manifest_url = _upload_and_sign(
        storage_account=args.storage_account,
        container=args.container,
        file_path=args.manifest_path,
        blob_name=manifest_blob,
        expiry=expiry,
    )
    questions_url = _upload_and_sign(
        storage_account=args.storage_account,
        container=args.container,
        file_path=args.metadata,
        blob_name=questions_blob,
        expiry=expiry,
    )

    _trigger_workflow(
        workflow_file=args.workflow_file,
        manifest_url=manifest_url,
        questions_url=questions_url,
        limit=args.limit,
        subtitle_modes=args.subtitle_modes,
    )

    if args.wait:
        _wait_for_latest_run(args.workflow_file)

    return 0


if __name__ == "__main__":
    sys.exit(main())
