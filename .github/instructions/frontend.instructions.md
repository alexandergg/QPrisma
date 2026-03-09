---
applyTo: "frontend/**/*.ts,frontend/**/*.tsx,frontend/package.json"
---

# Frontend path-specific instructions

- Follow Next.js App Router patterns and React 19 functional component conventions.
- Use explicit TypeScript types; avoid `any` unless there is a documented and justified boundary.
- Use `'use client';` only for components that need client-side hooks/browser APIs.
- Prefer existing data-fetching patterns (SWR and shared utilities) over ad-hoc fetch logic.
- Keep UI changes accessible and consistent with existing Tailwind utility patterns.
- Validate frontend changes with relevant existing scripts (`lint`, `typecheck`, and tests) before completion.
