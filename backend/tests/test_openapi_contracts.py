"""OpenAPI contract tests for documented API behavior."""

import pytest


@pytest.mark.unit
def test_core_status_endpoints_have_response_schemas(client):
    schema = client.get("/openapi.json").json()

    assert (
        schema["paths"]["/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/RootStatusResponse"
    )
    assert (
        schema["paths"]["/health"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/HealthCheckResponse"
    )
    assert (
        schema["paths"]["/config"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/ConfigStatusResponse"
    )


@pytest.mark.unit
def test_a2a_streaming_endpoints_document_sse(client):
    schema = client.get("/openapi.json").json()

    message_stream = schema["paths"]["/a2a/message:stream"]["post"]["responses"]["200"]
    assert "text/event-stream" in message_stream["content"]
    assert "StreamResponse" in message_stream["description"]

    task_stream = schema["paths"]["/a2a/tasks/{task_id}:subscribe"]["post"]["responses"]["200"]
    assert "text/event-stream" in task_stream["content"]
    assert "StreamResponse" in task_stream["description"]


@pytest.mark.unit
def test_hierarchy_endpoints_document_security_and_conflict_responses(client):
    schema = client.get("/openapi.json").json()

    process_responses = schema["paths"]["/graph/hierarchy/process"]["post"]["responses"]
    for status_code in ("401", "403", "404", "409"):
        assert status_code in process_responses

    drill_down_responses = schema["paths"]["/graph/hierarchy/search/drill-down"]["post"][
        "responses"
    ]
    for status_code in ("401", "403", "404"):
        assert status_code in drill_down_responses


@pytest.mark.unit
def test_upload_endpoints_have_typed_contracts_and_media_errors(client):
    schema = client.get("/openapi.json").json()

    for path in ("/upload", "/upload/optimized"):
        responses = schema["paths"][path]["post"]["responses"]
        assert (
            responses["200"]["content"]["application/json"]["schema"]["$ref"]
            == "#/components/schemas/MediaUploadResponse"
        )
        for status_code in ("401", "413", "415", "429", "500", "503"):
            assert status_code in responses

    chunked_status = schema["paths"]["/upload/chunked/status/{media_id}"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    assert chunked_status["$ref"] == "#/components/schemas/ChunkedUploadStatusResponse"

    chunked_cancel = schema["paths"]["/upload/chunked/cancel/{media_id}"]["delete"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    assert chunked_cancel["$ref"] == "#/components/schemas/CancelUploadResponse"


@pytest.mark.unit
def test_public_config_schema_omits_environment_detail(client):
    payload = client.get("/config").json()

    assert "environment" not in payload
