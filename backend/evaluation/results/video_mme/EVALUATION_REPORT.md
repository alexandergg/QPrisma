# QPrisma Video-MME Evaluation Report

**Date:** 2026-03-26 05:11 UTC
**API:** `https://ca-qprisma-api-dev.lemoncoast-87c1f692.westeurope.azurecontainerapps.io/`
**Subset:** short | **Max videos:** 12
**Total questions evaluated:** 36

## qprisma-remote

| Metric | Value |
|--------|-------|
| Overall Accuracy | **0.0%** |
| Questions | 33/33 successful |
| Avg Latency | 5743ms |
| Avg Tool Calls | 0.0 |

## direct-search-remote

| Metric | Value |
|--------|-------|
| Overall Accuracy | **22.2%** |
| Questions | 18/33 successful |
| Avg Latency | 11541ms |
| Avg Tool Calls | 0.0 |

### Accuracy by Category

| Category | Accuracy |
|----------|----------|
| Action Reasoning | 0.0% |
| Action Recognition | 100.0% |
| Attribute Perception | 20.0% |
| Counting Problem | 33.3% |
| Information Synopsis | 33.3% |
| Object Recognition | 0.0% |
| Temporal Reasoning | 0.0% |

### Accuracy by Duration Tier

| Tier | Accuracy |
|------|----------|
| short | 22.2% |

### Accuracy by Domain

| Domain | Accuracy |
|--------|----------|
| Knowledge | 22.2% |

## Method Comparison

| Method | Accuracy | Avg Latency | Avg Tools |
|--------|----------|-------------|-----------|
| qprisma-remote | 0.0% | 5743ms | 0.0 |
| direct-search-remote | 22.2% | 11541ms | 0.0 |
