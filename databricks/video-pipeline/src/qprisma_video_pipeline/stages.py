"""Stage dispatcher for the Databricks video pipeline."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from .contracts import *

STAGE_HANDLERS = tuple(PIPELINE_STAGES)


def run_stage() -> None:
    try:
        if stage == "register_manifest":
            stage_message = STAGE_MESSAGES[stage]
            upsert_processing_run(
                status="running",
                progress=progress_for_stage(stage),
                current_stage=stage,
            )
            write_stage_run(stage_name=stage, status="running", message=stage_message)
            write_progress_outbox(stage, stage_message)
            validate_source_contract()
            register_manifest()
            write_event(
                status="running",
                message="Manifest registered",
                details={
                    "pipeline_config": safe_pipeline_config_for_persistence(),
                    "source_media": safe_source_media_for_persistence(),
                    "config_hash": config_hash,
                    "processing_version": processing_version,
                },
            )
            write_stage_run(
                stage_name=stage,
                status="completed",
                message="Manifest registered",
                completed=True,
            )
        elif stage == "validate_and_probe_media":
            stage_message = STAGE_MESSAGES[stage]
            upsert_processing_run(
                status="running",
                progress=progress_for_stage(stage),
                current_stage=stage,
            )
            write_stage_run(stage_name=stage, status="running", message=stage_message)
            write_progress_outbox(stage, stage_message)
            validate_source_contract()
            uri = source_media_uri()
            probe = probe_source_media(uri)
            register_manifest(source_uri=uri)
            try:
                quality = evaluate_source_quality(uri, probe)
            except QualityGateError as exc:
                register_source_file(uri, probe, exc.quality)
                raise
            register_source_file(uri, probe, quality)
            write_event(
                status="source_validated",
                message="Source media is readable by Databricks",
                source_uri=uri,
                details={"probe": probe, "quality": quality},
            )
            write_stage_run(
                stage_name=stage,
                status="completed",
                message="Source media is readable by Databricks",
                metrics={
                    "bytes": probe["length"],
                    "path": probe["path"],
                    "duration_seconds": quality["metadata"].get("duration_seconds"),
                    "video_codec": quality["metadata"].get("video_codec"),
                    "audio_codec": quality["metadata"].get("audio_codec"),
                    "width": quality["metadata"].get("width"),
                    "height": quality["metadata"].get("height"),
                    "fps": quality["metadata"].get("fps"),
                    "quality_status": quality["status"],
                },
                completed=True,
            )
        elif stage == "extract_audio_assets":
            stage_message = "Extracting 16kHz mono audio asset with FFmpeg"
            upsert_processing_run(
                status="running",
                progress=progress_for_stage(stage),
                current_stage=stage,
            )
            write_stage_run(stage_name=stage, status="running", message=stage_message)
            write_progress_outbox(stage, stage_message)
            validate_source_contract()
            uri = source_media_uri()
            if not source_has_audio():
                skip_metrics = {"skipped": True, "reason": "source_has_no_audio"}
                write_event(
                    status="audio_extraction_skipped",
                    message="Source media has no audio stream; skipping audio extraction",
                    source_uri=uri,
                    details=skip_metrics,
                )
                write_stage_run(
                    stage_name=stage,
                    status="completed",
                    message="Audio extraction skipped because source has no audio stream",
                    metrics=skip_metrics,
                    completed=True,
                )
            else:
                audio_started = time.perf_counter()
                audio_asset = extract_audio_asset(uri)
                audio_chunks = build_audio_chunk_rows(audio_asset)
                register_audio_asset(audio_asset, audio_chunks)
                audio_elapsed = time.perf_counter() - audio_started
                audio_metrics = {
                    "audio_asset_id": audio_asset["audio_asset_id"],
                    "audio_uri": audio_asset["audio_uri"],
                    "duration_seconds": audio_asset["duration_seconds"],
                    "size_bytes": audio_asset["size_bytes"],
                    "sample_rate_hz": audio_asset["sample_rate_hz"],
                    "channels": audio_asset["channels"],
                    "chunk_count": len(audio_chunks),
                    "elapsed_seconds": rounded_metric(audio_elapsed),
                    "audio_seconds_per_second": rate_metric(audio_asset["duration_seconds"], audio_elapsed),
                    "bytes_per_second": rate_metric(audio_asset["size_bytes"], audio_elapsed),
                    "chunks_per_second": rate_metric(len(audio_chunks), audio_elapsed),
                }
                write_event(
                    status="audio_extracted",
                    message="Audio asset extracted for faster-whisper",
                    source_uri=uri,
                    details=audio_metrics,
                )
                write_stage_run(
                    stage_name=stage,
                    status="completed",
                    message="Audio asset extracted for faster-whisper",
                    metrics=audio_metrics,
                    completed=True,
                )
        elif stage == "extract_frame_assets":
            stage_message = "Extracting representative frames with FFmpeg"
            upsert_processing_run(
                status="running",
                progress=progress_for_stage(stage),
                current_stage=stage,
            )
            write_stage_run(stage_name=stage, status="running", message=stage_message)
            write_progress_outbox(stage, stage_message)
            validate_source_contract()
            uri = source_media_uri()
            frame_config = frame_extraction_config()
            frame_started = time.perf_counter()
            frame_assets = extract_frame_assets(uri)
            register_frame_assets(frame_assets)
            frame_elapsed = time.perf_counter() - frame_started
            frame_total_size_bytes = sum(frame["size_bytes"] for frame in frame_assets)
            frame_metrics = {
                "frame_count": len(frame_assets),
                "first_timestamp_ms": frame_assets[0]["timestamp_ms"] if frame_assets else None,
                "last_timestamp_ms": frame_assets[-1]["timestamp_ms"] if frame_assets else None,
                "frame_table": FRAME_ASSETS_TABLE,
                "total_size_bytes": frame_total_size_bytes,
                "avg_frame_size_bytes": rounded_metric(
                    frame_total_size_bytes / len(frame_assets) if frame_assets else 0
                ),
                "elapsed_seconds": rounded_metric(frame_elapsed),
                "frames_per_second": rate_metric(len(frame_assets), frame_elapsed),
                "bytes_per_second": rate_metric(frame_total_size_bytes, frame_elapsed),
                "extraction_method": frame_config["method"],
                "max_frames": frame_config["max_frames"],
                "min_spacing_seconds": frame_config["min_spacing_seconds"],
                "dedupe_hashes": frame_config["dedupe_hashes"],
                "format": frame_config["format"],
                "quality": frame_config["quality"],
            }
            write_event(
                status="frames_extracted",
                message="Frame assets extracted for multimodal inference",
                source_uri=uri,
                details=frame_metrics,
            )
            write_stage_run(
                stage_name=stage,
                status="completed",
                message="Frame assets extracted for multimodal inference",
                metrics=frame_metrics,
                completed=True,
            )
        elif stage == "run_florence_frame_analysis":
            stage_message = STAGE_MESSAGES[stage]
            upsert_processing_run(
                status="running",
                progress=progress_for_stage(stage),
                current_stage=stage,
            )
            write_stage_run(stage_name=stage, status="running", message=stage_message)
            write_progress_outbox(stage, stage_message)
            florence_metrics = run_florence_frame_analysis()
            skipped = bool(florence_metrics.get("skipped"))
            write_event(
                status="florence_frame_analysis_skipped" if skipped else "florence_frame_analysis_completed",
                message="Florence-2 frame analysis skipped" if skipped else "Florence-2 frame analysis completed",
                details=florence_metrics,
            )
            write_stage_run(
                stage_name=stage,
                status="completed",
                message="Florence-2 frame analysis skipped" if skipped else "Florence-2 frame analysis completed",
                metrics=florence_metrics,
                completed=True,
            )
        elif stage == "run_faster_whisper_asr":
            stage_message = "Transcribing audio chunks with faster-whisper"
            upsert_processing_run(
                status="running",
                progress=progress_for_stage(stage),
                current_stage=stage,
            )
            write_stage_run(stage_name=stage, status="running", message=stage_message)
            write_progress_outbox(stage, stage_message)
            model_config = faster_whisper_config()
            asr_run_id = f"{media_id}:asr:{model_config['model_name']}:{config_hash[:12]}"
            if not source_has_audio():
                skip_metrics = {"skipped": True, "reason": "source_has_no_audio"}
                write_event(
                    status="asr_skipped",
                    message="Source media has no audio stream; skipping ASR",
                    details={"asr_run_id": asr_run_id, **skip_metrics},
                )
                write_stage_run(
                    stage_name=stage,
                    status="completed",
                    message="ASR skipped because source has no audio stream",
                    metrics={"asr_run_id": asr_run_id, **skip_metrics},
                    completed=True,
                )
                continue_stage = False
            else:
                continue_stage = True
    
            if continue_stage:
                chunks = load_audio_chunks()
                audio_asset_id = chunks[0]["audio_asset_id"]
                asr_started_at = datetime.now(UTC)
                write_asr_run(
                    asr_run_id=asr_run_id,
                    audio_asset_id=audio_asset_id,
                    model_config=model_config,
                    status="running",
                    started_at=asr_started_at,
                    metrics={"chunk_count": len(chunks), "preset": model_config["preset"]},
                )
                transcript = transcribe_audio_chunks(chunks, model_config)
                write_transcript_segments(asr_run_id, transcript["segments"])
                write_asr_run(
                    asr_run_id=asr_run_id,
                    audio_asset_id=audio_asset_id,
                    model_config=model_config,
                    status="completed",
                    transcript_text=transcript["text"],
                    language=transcript["language"],
                    language_probability=transcript["language_probability"],
                    duration_seconds=transcript["duration_seconds"],
                    segment_count=len(transcript["segments"]),
                    started_at=asr_started_at,
                    completed=True,
                    metrics={
                        "chunk_count": len(chunks),
                        "elapsed_seconds": rounded_metric(transcript["elapsed_seconds"]),
                        "audio_duration_seconds": rounded_metric(transcript["duration_seconds"]),
                        "real_time_factor": rounded_metric(transcript["real_time_factor"]),
                        "audio_seconds_per_second": transcript["audio_seconds_per_second"],
                        "seconds_per_chunk": rounded_metric(transcript["seconds_per_chunk"]),
                        "device": model_config["device"],
                        "compute_type": model_config["compute_type"],
                        "batch_size": model_config["batch_size"],
                        "preset": model_config["preset"],
                        "azure_openai_whisper": "disabled_for_primary_path",
                        "chunk_metrics": transcript["chunk_metrics"],
                    },
                )
                write_event(
                    status="asr_completed",
                    message="faster-whisper ASR completed",
                    details={
                        "asr_run_id": asr_run_id,
                        "audio_asset_id": audio_asset_id,
                        "model_name": model_config["model_name"],
                        "preset": model_config["preset"],
                        "segment_count": len(transcript["segments"]),
                        "language": transcript["language"],
                        "duration_seconds": transcript["duration_seconds"],
                        "elapsed_seconds": rounded_metric(transcript["elapsed_seconds"]),
                        "real_time_factor": rounded_metric(transcript["real_time_factor"]),
                        "audio_seconds_per_second": transcript["audio_seconds_per_second"],
                    },
                )
                write_stage_run(
                    stage_name=stage,
                    status="completed",
                    message="faster-whisper ASR completed",
                    metrics={
                        "asr_run_id": asr_run_id,
                        "audio_asset_id": audio_asset_id,
                        "model_name": model_config["model_name"],
                        "preset": model_config["preset"],
                        "device": model_config["device"],
                        "compute_type": model_config["compute_type"],
                        "batch_size": model_config["batch_size"],
                        "chunk_count": len(chunks),
                        "audio_duration_seconds": rounded_metric(transcript["duration_seconds"]),
                        "segment_count": len(transcript["segments"]),
                        "elapsed_seconds": rounded_metric(transcript["elapsed_seconds"]),
                        "real_time_factor": rounded_metric(transcript["real_time_factor"]),
                        "audio_seconds_per_second": transcript["audio_seconds_per_second"],
                        "seconds_per_chunk": rounded_metric(transcript["seconds_per_chunk"]),
                    },
                    completed=True,
                )
        elif stage == "detect_scenes_and_windows":
            stage_message = STAGE_MESSAGES[stage]
            upsert_processing_run(
                status="running",
                progress=progress_for_stage(stage),
                current_stage=stage,
            )
            write_stage_run(stage_name=stage, status="running", message=stage_message)
            write_progress_outbox(stage, stage_message)
            detection_metrics = detect_scenes_and_windows()
            write_event(
                status="scene_windows_detected",
                message="Temporal windows and scene candidates registered",
                details=detection_metrics,
            )
            write_stage_run(
                stage_name=stage,
                status="completed",
                message="Temporal windows and scene candidates registered",
                metrics=detection_metrics,
                completed=True,
            )
        elif stage == "run_databricks_scene_reasoning":
            stage_message = STAGE_MESSAGES[stage]
            upsert_processing_run(
                status="running",
                progress=progress_for_stage(stage),
                current_stage=stage,
            )
            write_stage_run(stage_name=stage, status="running", message=stage_message)
            write_progress_outbox(stage, stage_message)
            scene_metrics = run_databricks_scene_reasoning()
            skipped = bool(scene_metrics.get("skipped"))
            write_event(
                status="databricks_scene_reasoning_skipped" if skipped else "databricks_scene_reasoning_completed",
                message="Databricks Gemma 3 scene reasoning skipped"
                if skipped
                else "Databricks Gemma 3 scene reasoning completed",
                details=scene_metrics,
            )
            write_stage_run(
                stage_name=stage,
                status="completed",
                message="Databricks Gemma 3 scene reasoning skipped"
                if skipped
                else "Databricks Gemma 3 scene reasoning completed",
                metrics=scene_metrics,
                completed=True,
            )
        elif stage == "build_gold_processing_result":
            stage_message = "Building frontend-compatible Gold processing result"
            upsert_processing_run(
                status="running",
                progress=progress_for_stage(stage),
                current_stage=stage,
            )
            write_stage_run(stage_name=stage, status="running", message=stage_message)
            write_progress_outbox(stage, stage_message)
            gold_result = build_gold_processing_result()
            metrics = parse_json_dict(gold_result["metrics_json"])
            write_event(
                status="gold_processing_result_built",
                message="Gold processing result registered",
                details={
                    "result_id": gold_result["result_id"],
                    "status": gold_result["status"],
                    "processing_results_table": GOLD_PROCESSING_RESULTS_TABLE,
                    "metrics": metrics,
                },
            )
            write_stage_run(
                stage_name=stage,
                status="completed",
                message="Gold processing result registered",
                metrics={
                    "result_id": gold_result["result_id"],
                    "status": gold_result["status"],
                    "processing_results_table": GOLD_PROCESSING_RESULTS_TABLE,
                    **metrics,
                },
                completed=True,
            )
        elif stage == "build_graph_upserts":
            stage_message = "Building Neo4j graph upsert intents from Delta records"
            upsert_processing_run(
                status="running",
                progress=progress_for_stage(stage),
                current_stage=stage,
            )
            write_stage_run(stage_name=stage, status="running", message=stage_message)
            write_progress_outbox(stage, stage_message)
            graph_build_started = time.perf_counter()
            graph_upserts = build_graph_upsert_rows()
            register_graph_upserts(graph_upserts)
            graph_build_elapsed = time.perf_counter() - graph_build_started
            operation_counts: dict[str, int] = {}
            label_counts: dict[str, int] = {}
            for upsert in graph_upserts:
                operation_counts[upsert["operation_type"]] = (
                    operation_counts.get(upsert["operation_type"], 0) + 1
                )
                label_counts[upsert["label_or_type"]] = label_counts.get(upsert["label_or_type"], 0) + 1
            write_event(
                status="graph_upserts_built",
                message="Neo4j graph upsert intents registered",
                details={
                    "upsert_count": len(graph_upserts),
                    "operation_counts": operation_counts,
                    "label_counts": label_counts,
                    "graph_upserts_table": GRAPH_UPSERTS_TABLE,
                    "elapsed_seconds": rounded_metric(graph_build_elapsed),
                    "upserts_per_second": rate_metric(len(graph_upserts), graph_build_elapsed),
                },
            )
            write_stage_run(
                stage_name=stage,
                status="completed",
                message="Neo4j graph upsert intents registered",
                metrics={
                    "upsert_count": len(graph_upserts),
                    "operation_counts": operation_counts,
                    "label_counts": label_counts,
                    "graph_upserts_table": GRAPH_UPSERTS_TABLE,
                    "elapsed_seconds": rounded_metric(graph_build_elapsed),
                    "upserts_per_second": rate_metric(len(graph_upserts), graph_build_elapsed),
                },
                completed=True,
            )
        elif stage == "project_neo4j_graph":
            stage_message = STAGE_MESSAGES[stage]
            upsert_processing_run(
                status="running",
                progress=progress_for_stage(stage),
                current_stage=stage,
            )
            write_stage_run(stage_name=stage, status="running", message=stage_message)
            write_progress_outbox(stage, stage_message)
            projection_metrics = project_neo4j_graph()
            projection_skipped = bool(projection_metrics.get("skipped"))
            projection_message = (
                "Neo4j graph projection skipped"
                if projection_skipped
                else "Neo4j graph upserts applied"
            )
            write_event(
                status="neo4j_graph_skipped" if projection_skipped else "neo4j_graph_projected",
                message=projection_message,
                details={
                    "applied_count": projection_metrics["applied_count"],
                    "failed_count": projection_metrics["failed_count"],
                    "graph_upserts_table": projection_metrics["graph_upserts_table"],
                    "neo4j_database": projection_metrics.get("neo4j_database"),
                    "skipped": projection_skipped,
                    "skipped_reason": projection_metrics.get("skipped_reason"),
                    "elapsed_seconds": projection_metrics.get("elapsed_seconds"),
                    "upserts_per_second": projection_metrics.get("upserts_per_second"),
                },
            )
            write_stage_run(
                stage_name=stage,
                status="completed",
                message=projection_message,
                metrics=projection_metrics,
                completed=True,
            )
        elif stage == "publish_outbox":
            stage_message = STAGE_MESSAGES[stage]
            upsert_processing_run(
                status="running",
                progress=progress_for_stage(stage),
                current_stage=stage,
            )
            write_stage_run(stage_name=stage, status="running", message=stage_message)
            gold_result = load_latest_gold_processing_result()
            if not gold_result:
                raise ValueError("Gold processing result is missing. Run build_gold_processing_result first.")
            processing_result = parse_json_dict(gold_result["processing_result_json"])
            video_metadata = parse_json_dict(gold_result["video_metadata_json"])
            write_event(
                status="completed",
                message="Databricks lakehouse video processing completed",
                details={
                    "gold_result_id": gold_result["result_id"],
                    "status": processing_result.get("status"),
                    "frames_analyzed": processing_result.get("frames_analyzed"),
                    "processing_results_table": GOLD_PROCESSING_RESULTS_TABLE,
                },
            )
            write_stage_run(
                stage_name=stage,
                status="completed",
                message="Databricks lakehouse video processing completed",
                completed=True,
            )
            upsert_processing_run(
                status="completed",
                progress=1.0,
                current_stage=stage,
                completed=True,
            )
            write_outbox_event(
                status="completed",
                progress=1.0,
                message="Databricks lakehouse video processing completed",
                processing_result=processing_result,
                video_metadata=video_metadata,
            )
        else:
            raise ValueError(f"Unsupported pipeline stage: {stage}")
    except Exception as exc:
        write_quarantine(stage_name=stage, reason="stage_failed", exc=exc)
        write_stage_run(
            stage_name=stage,
            status="failed",
            message=str(exc),
            error={"error_type": type(exc).__name__, "message": str(exc)},
            completed=True,
        )
        upsert_processing_run(
            status="failed",
            progress=progress_for_stage(stage),
            current_stage=stage,
            error={"error_type": type(exc).__name__, "message": str(exc)},
            completed=True,
        )
        write_event(
            status="failed",
            message=str(exc),
            details={"error_type": type(exc).__name__},
        )
        write_outbox_event(
            status="failed",
            progress=progress_for_stage(stage),
            message="Databricks video pipeline failed",
            error={"error_type": type(exc).__name__, "message": str(exc)},
        )
        raise

