"""Notebook entrypoint for the QPrisma Databricks video pipeline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from . import runtime, stages, tables


def run_from_notebook(*, spark: Any, dbutils: Any) -> None:
    namespace = runtime.initialize_runtime(spark, dbutils)
    tables.ensure_ops_table()
    stages.run_stage()
    print(
        json.dumps(
            {
                "event": "qprisma_video_pipeline_stage_completed",
                "catalog": namespace["catalog"],
                "schema": namespace["schema"],
                "ops_table": namespace["qualified_ops_table"],
                "stage": namespace["stage"],
                "media_id": namespace["media_id"],
                "dispatch_id": namespace["dispatch_id"],
                "timestamp": datetime.now(UTC).isoformat(),
            },
            sort_keys=True,
        )
    )
