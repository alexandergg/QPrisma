---
applyTo: "backend/**/*.py,backend/pyproject.toml"
---

# Backend path-specific instructions

- Keep request/response wiring in `backend/api/routes/`; move logic to `backend/services/`.
- Reuse dependency providers from `backend/api/dependencies.py` instead of constructing services inline.
- Use type hints, Pydantic models, and async I/O patterns consistently.
- For runtime configuration, use `core.config.settings` and typed config models.
- For agent tool functions, return explicit success/error dictionaries and avoid raising broad exceptions.
- For behavior changes, update or add targeted pytest coverage in `backend/tests/`.
