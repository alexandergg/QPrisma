from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any

import httpx

from .settings import BridgeSettings


class DatabricksAuthError(RuntimeError):
    """Raised when the bridge cannot obtain Databricks API credentials."""


class DatabricksApiError(RuntimeError):
    """Raised when Databricks Jobs API rejects the run request."""


@dataclass(frozen=True)
class DatabricksRunResult:
    run_id: int
    number_in_job: int | None = None


@dataclass(frozen=True)
class DatabricksSqlStatementResult:
    statement_id: str | None
    rows: list[dict[str, Any]]


class DatabricksJobsClient:
    def __init__(
        self, settings: BridgeSettings, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self._settings = settings
        self._workspace_url = settings.databricks_workspace_url.rstrip("/")
        self._http_client = http_client

    async def run_now(self, run_request: dict[str, Any]) -> DatabricksRunResult:
        token = await self._get_access_token()
        request_body = {
            "job_id": run_request["job_id"],
            "idempotency_token": run_request["idempotency_token"],
            "job_parameters": run_request["job_parameters"],
        }

        if self._http_client is None:
            async with httpx.AsyncClient(timeout=self._settings.http_timeout_seconds) as client:
                return await self._post_run_now(client, token, request_body)

        return await self._post_run_now(self._http_client, token, request_body)

    async def execute_sql_statement(self, statement: str) -> DatabricksSqlStatementResult:
        if not self._settings.databricks_sql_warehouse_id:
            raise DatabricksApiError("DATABRICKS_SQL_WAREHOUSE_ID is required for Databricks SQL")

        token = await self._get_access_token()
        request_body = {
            "warehouse_id": self._settings.databricks_sql_warehouse_id,
            "statement": statement,
            "wait_timeout": f"{int(self._settings.http_timeout_seconds)}s",
            "on_wait_timeout": "CONTINUE",
        }

        if self._http_client is None:
            async with httpx.AsyncClient(timeout=self._settings.http_timeout_seconds) as client:
                return await self._post_sql_statement(client, token, request_body)

        return await self._post_sql_statement(self._http_client, token, request_body)

    async def _post_run_now(
        self,
        client: httpx.AsyncClient,
        token: str,
        request_body: dict[str, Any],
    ) -> DatabricksRunResult:
        response = await client.post(
            f"{self._workspace_url}/api/2.1/jobs/run-now",
            headers={"Authorization": f"Bearer {token}"},
            json=request_body,
        )
        if response.status_code >= 400:
            raise DatabricksApiError(
                f"Databricks run-now failed with status {response.status_code}: {response.text}"
            )

        body = response.json()
        run_id = body.get("run_id")
        if not isinstance(run_id, int):
            raise DatabricksApiError("Databricks run-now response did not include integer run_id")

        number_in_job = body.get("number_in_job")
        return DatabricksRunResult(
            run_id=run_id,
            number_in_job=number_in_job if isinstance(number_in_job, int) else None,
        )

    async def _post_sql_statement(
        self,
        client: httpx.AsyncClient,
        token: str,
        request_body: dict[str, Any],
    ) -> DatabricksSqlStatementResult:
        response = await client.post(
            f"{self._workspace_url}/api/2.0/sql/statements",
            headers={"Authorization": f"Bearer {token}"},
            json=request_body,
        )
        if response.status_code >= 400:
            raise DatabricksApiError(
                f"Databricks SQL statement failed with status {response.status_code}: {response.text}"
            )

        return await self._wait_for_sql_result(client, token, response.json())

    async def _wait_for_sql_result(
        self,
        client: httpx.AsyncClient,
        token: str,
        body: dict[str, Any],
    ) -> DatabricksSqlStatementResult:
        deadline = monotonic() + self._settings.http_timeout_seconds

        while True:
            state = str(body.get("status", {}).get("state", "")).upper()
            if state == "SUCCEEDED":
                return self._parse_sql_result(body)
            if state in {"FAILED", "CANCELED", "CLOSED"}:
                error = body.get("status", {}).get("error") or body
                raise DatabricksApiError(f"Databricks SQL statement ended in {state}: {error}")

            statement_id = body.get("statement_id")
            if not isinstance(statement_id, str) or not statement_id:
                raise DatabricksApiError("Databricks SQL response did not include statement_id")
            if monotonic() >= deadline:
                raise DatabricksApiError(f"Databricks SQL statement timed out: {statement_id}")

            await asyncio.sleep(1)
            response = await client.get(
                f"{self._workspace_url}/api/2.0/sql/statements/{statement_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code >= 400:
                raise DatabricksApiError(
                    f"Databricks SQL status check failed with status {response.status_code}: {response.text}"
                )
            body = response.json()

    def _parse_sql_result(self, body: dict[str, Any]) -> DatabricksSqlStatementResult:
        columns = body.get("manifest", {}).get("schema", {}).get("columns", [])
        column_names = [column.get("name") for column in columns if isinstance(column, dict)]
        if not all(isinstance(name, str) and name for name in column_names):
            column_names = []

        data_array = body.get("result", {}).get("data_array") or []
        rows: list[dict[str, Any]] = []
        if column_names:
            for row in data_array:
                if isinstance(row, list):
                    rows.append(dict(zip(column_names, row, strict=False)))

        statement_id = body.get("statement_id")
        return DatabricksSqlStatementResult(
            statement_id=statement_id if isinstance(statement_id, str) else None,
            rows=rows,
        )

    async def _get_access_token(self) -> str:
        auth_type = self._settings.databricks_auth_type.lower()
        if auth_type == "pat":
            if not self._settings.databricks_token:
                raise DatabricksAuthError(
                    "DATABRICKS_TOKEN is required when DATABRICKS_AUTH_TYPE=pat"
                )
            return self._settings.databricks_token

        if auth_type == "oauth_m2m":
            return await self._get_oauth_m2m_token()

        if auth_type == "azure_managed_identity":
            return await self._get_azure_managed_identity_token()

        raise DatabricksAuthError(
            f"Unsupported Databricks auth type: {self._settings.databricks_auth_type}"
        )

    async def _get_oauth_m2m_token(self) -> str:
        if not self._settings.databricks_client_id or not self._settings.databricks_client_secret:
            raise DatabricksAuthError(
                "DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET are required for OAuth M2M"
            )

        data = {
            "grant_type": "client_credentials",
            "scope": "all-apis",
            "client_id": self._settings.databricks_client_id,
            "client_secret": self._settings.databricks_client_secret,
        }

        async with httpx.AsyncClient(timeout=self._settings.http_timeout_seconds) as client:
            response = await client.post(f"{self._workspace_url}/oidc/v1/token", data=data)

        if response.status_code >= 400:
            raise DatabricksAuthError(
                f"Databricks OAuth token request failed with status {response.status_code}: {response.text}"
            )

        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise DatabricksAuthError(
                "Databricks OAuth token response did not include access_token"
            )
        return token

    async def _get_azure_managed_identity_token(self) -> str:
        from azure.identity.aio import DefaultAzureCredential

        credential_kwargs: dict[str, str] = {}
        if self._settings.databricks_client_id:
            credential_kwargs["managed_identity_client_id"] = self._settings.databricks_client_id

        async with DefaultAzureCredential(**credential_kwargs) as credential:
            token = await credential.get_token("2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default")
        return token.token
