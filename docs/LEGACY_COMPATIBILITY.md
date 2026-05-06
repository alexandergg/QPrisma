# Legacy Compatibility

QPrisma keeps a small number of compatibility paths so existing media and
evaluation data continue to work while the backend architecture is simplified.
These paths are not new product surfaces and should only be removed after the
affected data or clients have been migrated.

## Structure fallback

`backend/services/structure_service.py` first reads video structure from Neo4j.
If graph data is missing, it can fall back to structure stored on the PostgreSQL
media record (`structure` or `processing_result.structure`). This protects media
processed before graph ingestion became the canonical structure source.

Fallback responses include `_legacy_path: true` and emit a
`structure_legacy_fallback` warning log with sanitized media metadata so
operators can measure remaining usage. Removal is safe only after affected media
has been identified and backfilled into the graph.

## Context envelope fallback

Hosted-agent requests should use the base64 envelope produced by
`format_qprisma_context()`:

```text
[QPRISMA_CONTEXT_B64:<base64url-json>]
```

`extract_qprisma_context()` also accepts the older raw JSON envelope:

```text
[QPRISMA_CONTEXT:{"media_id":"..."}]
```

This keeps older evaluation records and offline benchmark reruns compatible.
New code should not emit the raw JSON format.

## Removal checklist

Before deleting either compatibility path:

1. Confirm production logs show no recent `structure_legacy_fallback` events.
2. Backfill legacy PostgreSQL structures into Neo4j or accept a documented data
   loss/404 behavior for old media.
3. Regenerate benchmark/evaluation data with `QPRISMA_CONTEXT_B64`.
4. Keep tests for the migration boundary until the legacy path is removed.
