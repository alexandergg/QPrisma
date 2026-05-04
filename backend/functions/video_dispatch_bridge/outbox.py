from __future__ import annotations

import json
import logging
import re
from typing import Any

from .contracts import DatabricksStatusEvent, PayloadValidationError
from .databricks_client import DatabricksJobsClient
from .settings import BridgeSettings
from .state_store import PostgresDispatchStateStore

logger = logging.getLogger(__name__)

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DatabricksOutboxConsumer:
    def __init__(
        self,
        *,
        settings: BridgeSettings,
        databricks_client: DatabricksJobsClient,
        state_store: PostgresDispatchStateStore,
    ) -> None:
        self._settings = settings
        self._databricks_client = databricks_client
        self._state_store = state_store

    async def process_once(self) -> int:
        if not self._settings.databricks_sql_warehouse_id:
            logger.warning(
                "Skipping Databricks outbox polling because DATABRICKS_SQL_WAREHOUSE_ID is not set"
            )
            return 0

        rows = await self._fetch_unconsumed_rows()
        processed_count = 0
        for row in rows:
            event = self._status_event_from_row(row)
            self._state_store.apply_status_event(event)
            await self._mark_consumed(self._required_string(row, "outbox_id"))
            processed_count += 1

        logger.info(
            "Databricks outbox polling completed", extra={"processed_count": processed_count}
        )
        return processed_count

    async def _fetch_unconsumed_rows(self) -> list[dict[str, Any]]:
        statement = f"""
        SELECT
          outbox_id,
          schema_version,
          media_id,
          dispatch_id,
          status,
          progress,
          message,
          processing_result,
          video_metadata,
          error
        FROM {self._qualified_table()}
        WHERE consumed_at IS NULL
        ORDER BY emitted_at ASC
        LIMIT {self._settings.databricks_outbox_poll_batch_size}
        """
        result = await self._databricks_client.execute_sql_statement(statement)
        return result.rows

    async def _mark_consumed(self, outbox_id: str) -> None:
        statement = f"""
        UPDATE {self._qualified_table()}
        SET consumed_at = current_timestamp()
        WHERE outbox_id = {self._sql_literal(outbox_id)}
          AND consumed_at IS NULL
        """  # noqa: S608 - identifiers are validated and outbox_id is SQL-escaped.
        await self._databricks_client.execute_sql_statement(statement)

    def _status_event_from_row(self, row: dict[str, Any]) -> DatabricksStatusEvent:
        payload = {
            "schema_version": self._required_string(row, "schema_version"),
            "media_id": self._required_string(row, "media_id"),
            "dispatch_id": self._required_string(row, "dispatch_id"),
            "status": self._required_string(row, "status"),
            "progress": self._progress(row.get("progress")),
            "message": self._required_string(row, "message"),
            "processing_result": row.get("processing_result") or "{}",
            "video_metadata": row.get("video_metadata") or "{}",
            "error": row.get("error") or "{}",
        }
        return DatabricksStatusEvent.from_json(json.dumps(payload))

    def _qualified_table(self) -> str:
        return ".".join(
            [
                self._quote_identifier(self._settings.databricks_outbox_catalog),
                self._quote_identifier(self._settings.databricks_outbox_schema),
                self._quote_identifier(self._settings.databricks_outbox_table),
            ]
        )

    @staticmethod
    def _quote_identifier(value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise PayloadValidationError(f"Invalid Databricks SQL identifier: {value}")
        return f"`{value}`"

    @staticmethod
    def _sql_literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    @staticmethod
    def _required_string(row: dict[str, Any], field_name: str) -> str:
        value = row.get(field_name)
        if not isinstance(value, str) or not value:
            raise PayloadValidationError(f"Databricks outbox row requires non-empty {field_name}")
        return value

    @staticmethod
    def _progress(value: Any) -> float:
        if isinstance(value, bool):
            raise PayloadValidationError("Databricks outbox row progress must be numeric")
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError as exc:
                raise PayloadValidationError(
                    "Databricks outbox row progress must be numeric"
                ) from exc
        raise PayloadValidationError("Databricks outbox row progress must be numeric")
