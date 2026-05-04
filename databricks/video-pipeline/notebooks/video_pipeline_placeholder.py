# Databricks notebook source
"""QPrisma video pipeline placeholder.

This notebook defines the initial job contract for the Databricks pilot. The
heavy video stages will replace these placeholders incrementally while keeping
the same job parameters and outbox/status contract.
"""

# COMMAND ----------

from datetime import UTC, datetime

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
queue_name = dbutils.widgets.get("queue_name")
stage = dbutils.widgets.get("stage")

print(
    {
        "event": "qprisma_video_pipeline_stage_placeholder",
        "catalog": catalog,
        "schema": schema,
        "queue_name": queue_name,
        "stage": stage,
        "timestamp": datetime.now(UTC).isoformat(),
    }
)
