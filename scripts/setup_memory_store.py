#!/usr/bin/env python3
"""
Setup Memory Store
==================

One-time script to provision the Foundry Memory Store for QPrisma.
Idempotent — safe to run multiple times.

Usage::

    python scripts/setup_memory_store.py

Environment variables (from .env or shell):
    FOUNDRY_PROJECT_ENDPOINT
    FOUNDRY_MEMORY_STORE_NAME
    FOUNDRY_MEMORY_CHAT_MODEL
    FOUNDRY_MEMORY_EMBEDDING_MODEL
"""

import asyncio
import json
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from core.config import settings  # noqa: E402
from services.foundry_memory_service import FoundryMemoryService  # noqa: E402


async def main() -> None:
    service = FoundryMemoryService()

    if not service.enabled:
        print("ERROR: Memory store not configured. Set these environment variables:")
        print("  FOUNDRY_PROJECT_ENDPOINT")
        print("  FOUNDRY_MEMORY_STORE_NAME")
        print("  FOUNDRY_MEMORY_CHAT_MODEL")
        print("  FOUNDRY_MEMORY_EMBEDDING_MODEL")
        print()
        print(f"Current values:")
        print(f"  project_endpoint: {settings.foundry.project_endpoint or '(not set)'}")
        print(f"  memory_store_name: {settings.foundry.memory_store_name or '(not set)'}")
        print(f"  memory_chat_model: {settings.foundry.memory_chat_model or '(not set)'}")
        print(f"  memory_embedding_model: {settings.foundry.memory_embedding_model or '(not set)'}")
        sys.exit(1)

    print(f"Setting up memory store: {settings.foundry.memory_store_name}")
    print(f"  Endpoint: {settings.foundry.project_endpoint}")
    print(f"  Chat model: {settings.foundry.memory_chat_model}")
    print(f"  Embedding model: {settings.foundry.memory_embedding_model}")
    print()

    result = await service.ensure_memory_store()
    print(json.dumps(result, indent=2))

    if "error" in result:
        sys.exit(1)

    print("\nMemory store ready!")


if __name__ == "__main__":
    asyncio.run(main())
