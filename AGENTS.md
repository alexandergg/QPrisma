# QPrisma Agent Instructions

Use this file together with `.github/copilot-instructions.md` and path-specific files in `.github/instructions/`.

## Global operating rules

- Make the smallest safe change that solves the requested problem.
- Keep backend route handlers thin; put business logic in `backend/services/`.
- Use centralized settings from `core.config.settings`; do not use `os.getenv()` directly.
- For LangGraph tools, return structured error payloads instead of raising exceptions.
- Prefer `datetime.now(UTC)` over `datetime.utcnow()`.
- Preserve authentication requirements on API endpoints.
- Run only relevant existing tests/checks for changed areas before finishing.

## Instruction precedence

When file-specific guidance exists in `.github/instructions/*.instructions.md`, follow that guidance first for matching files.
