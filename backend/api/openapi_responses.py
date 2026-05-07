"""Shared OpenAPI response documentation for API routes."""

from typing import Any

JsonObject = dict[str, Any]
ResponseDocs = dict[int | str, JsonObject]

ERROR_DETAIL_SCHEMA: JsonObject = {
    "type": "object",
    "properties": {
        "detail": {
            "description": "Human-readable error details or a structured error payload.",
        }
    },
}

AUTH_RESPONSES: ResponseDocs = {
    401: {
        "description": "Authentication is required or the bearer token is invalid.",
        "content": {"application/json": {"schema": ERROR_DETAIL_SCHEMA}},
    }
}

OWNER_SCOPED_RESPONSES: ResponseDocs = {
    **AUTH_RESPONSES,
    403: {
        "description": "The authenticated user is not authorized to access the requested resource.",
        "content": {"application/json": {"schema": ERROR_DETAIL_SCHEMA}},
    },
    404: {
        "description": "The requested owner-scoped resource was not found.",
        "content": {"application/json": {"schema": ERROR_DETAIL_SCHEMA}},
    },
}

CONFLICT_RESPONSES: ResponseDocs = {
    409: {
        "description": "The request is valid but cannot be completed in the resource's current state.",
        "content": {"application/json": {"schema": ERROR_DETAIL_SCHEMA}},
    }
}

PAYLOAD_TOO_LARGE_RESPONSES: ResponseDocs = {
    413: {
        "description": "The uploaded payload exceeds the configured size limit.",
        "content": {"application/json": {"schema": ERROR_DETAIL_SCHEMA}},
    }
}

UNSUPPORTED_MEDIA_RESPONSES: ResponseDocs = {
    415: {
        "description": "The uploaded media type is not supported.",
        "content": {"application/json": {"schema": ERROR_DETAIL_SCHEMA}},
    }
}

SERVICE_RESPONSES: ResponseDocs = {
    500: {
        "description": "The server could not complete the request.",
        "content": {"application/json": {"schema": ERROR_DETAIL_SCHEMA}},
    },
    503: {
        "description": "A required downstream service is unavailable.",
        "content": {"application/json": {"schema": ERROR_DETAIL_SCHEMA}},
    },
}

RATE_LIMIT_RESPONSES: ResponseDocs = {
    429: {
        "description": "The caller exceeded the configured request rate limit.",
        "content": {"application/json": {"schema": ERROR_DETAIL_SCHEMA}},
    }
}

SSE_STREAM_RESPONSE: ResponseDocs = {
    200: {
        "description": (
            "Server-Sent Events stream. Each `data:` line contains a JSON-encoded "
            "`StreamResponse` object."
        ),
        "content": {
            "text/event-stream": {
                "schema": {
                    "type": "string",
                    "description": "SSE stream carrying A2A StreamResponse JSON payloads.",
                },
                "examples": {
                    "task_update": {
                        "summary": "Task status update event",
                        "value": 'data: {"statusUpdate":{"taskId":"task-id","contextId":"context-id","status":{"state":"working"}}}\\n\\n',
                    }
                },
            }
        },
    }
}


def merge_responses(*response_sets: ResponseDocs) -> ResponseDocs:
    """Merge FastAPI ``responses=`` dictionaries without mutating callers."""
    merged: ResponseDocs = {}
    for response_set in response_sets:
        merged.update(response_set)
    return merged
