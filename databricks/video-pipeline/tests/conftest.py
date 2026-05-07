"""Local pytest bootstrap for the Databricks video-pipeline package."""

from __future__ import annotations

import sys
import types
from pathlib import Path


class _SparkType:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class _StructField(_SparkType):
    def __init__(self, name: str, data_type: object, nullable: bool = True):
        super().__init__(name, data_type, nullable)
        self.name = name
        self.dataType = data_type
        self.nullable = nullable


class _StructType(_SparkType):
    def __init__(self, fields: list[_StructField] | None = None):
        super().__init__(fields or [])
        self.fields = fields or []


def _install_pyspark_type_stub() -> None:
    if "pyspark.sql.types" in sys.modules:
        return

    pyspark_module = types.ModuleType("pyspark")
    sql_module = types.ModuleType("pyspark.sql")
    types_module = types.ModuleType("pyspark.sql.types")

    for type_name in ("DoubleType", "LongType", "StringType", "TimestampType"):
        setattr(types_module, type_name, type(type_name, (_SparkType,), {}))
    types_module.StructField = _StructField
    types_module.StructType = _StructType
    sql_module.types = types_module
    pyspark_module.sql = sql_module

    sys.modules["pyspark"] = pyspark_module
    sys.modules["pyspark.sql"] = sql_module
    sys.modules["pyspark.sql.types"] = types_module


_install_pyspark_type_stub()

PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from qprisma_video_pipeline import runtime  # noqa: E402

runtime.bind_namespace(runtime.public_namespace())
