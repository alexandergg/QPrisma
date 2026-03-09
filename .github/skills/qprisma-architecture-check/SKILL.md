---
name: qprisma-architecture-check
description: Validate that changes follow QPrisma architecture boundaries across backend services, frontend components, agent flows, and infrastructure.
---

# QPrisma Architecture Check Skill

Use this skill when reviewing design consistency or structural impact.

## Validation checklist

- API handlers remain orchestration-only and business logic stays in services.
- Dependency creation follows lazy initialization/singleton accessors.
- Agent graph/tool changes respect existing state, memory, and observability patterns.
- Frontend changes align with Next.js App Router conventions.
- Infra changes preserve current multi-stage CI/CD and deployment safety controls.

## Output format

Return:

1. Architecture-aligned items
2. Violations with impacted files
3. Minimal remediation plan
