# Databricks notebook source
"""Thin Databricks notebook entrypoint for the QPrisma video pipeline.

The implementation lives in ``databricks/video-pipeline/src/qprisma_video_pipeline``
so operational code can be reviewed, tested, and maintained as normal Python modules.
"""

# COMMAND ----------

import os
import sys

_context = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
_notebook_path = _context.notebookPath().get()
_src_path = os.path.normpath(
    os.path.join("/Workspace", os.path.dirname(_notebook_path).lstrip("/"), "..", "src")
)
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from qprisma_video_pipeline.runner import run_from_notebook

run_from_notebook(spark=spark, dbutils=dbutils)
