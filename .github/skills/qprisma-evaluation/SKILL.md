---
name: qprisma-evaluation
description: Run QPrisma Video-MME benchmark evaluation against a remote API deployment.
---

# QPrisma Evaluation Skill

Use this skill to run Video-MME (CVPR 2025) evaluation against a QPrisma API deployment.

## Prerequisites

- `yt-dlp` installed (`pip install yt-dlp`) for video downloading
- `httpx` installed (included in backend dependencies)
- QPrisma API credentials (email/password)
- Environment variables or CLI flags for API URL and credentials

## Common runs

### Quick test (12 short videos)

```bash
cd backend
python -m evaluation.run_video_mme_eval \
  --api-url $QPRISMA_API_URL \
  --subset short --max-videos 12
```

### Re-run with indexed videos (skip upload)

```bash
cd backend
python -m evaluation.run_video_mme_eval --skip-upload --subset short
```

### Full Video-MME benchmark

```bash
cd backend
python -m evaluation.run_video_mme_eval --subset all --max-videos 900
```

## Environment variables

| Variable | Description | Default/Example |
|----------|-------------|-----------------|
| `QPRISMA_API_URL` | QPrisma API base URL | https://ca-qprisma-api-dev.lemoncoast-87c1f692.westeurope.azurecontainerapps.io |
| `QPRISMA_EVAL_EMAIL` | Auth email | user@example.com |
| `QPRISMA_EVAL_PASSWORD` | Auth password | stringst |

## Pipeline phases

1. **Setup** — authenticate, health check, load benchmark data
2. **Video Preparation** — discover indexed videos, download missing via yt-dlp, upload, wait for processing
3. **Evaluation** — run QPrisma agent + direct-search baseline on each question
4. **Reporting** — compute accuracy (by category/tier/domain), efficiency metrics, generate markdown report

## Reporting

- Results saved to `evaluation/results/video_mme/`
- `EVALUATION_REPORT.md` — human-readable report with accuracy tables
- `metrics.json` — machine-readable metrics
- Per-question JSON results with resume support
