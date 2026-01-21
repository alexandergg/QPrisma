#!/usr/bin/env python3
"""
Export OpenAPI schema from FastAPI application.

Usage:
    python scripts/export_openapi.py

This will generate:
    - docs/openapi.json - Full OpenAPI 3.0 schema
    - docs/openapi.yaml - YAML version (if pyyaml is installed)
"""

import json
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.main import app


def export_openapi():
    """Export the OpenAPI schema to JSON and optionally YAML."""

    # Create docs directory
    docs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs")
    os.makedirs(docs_dir, exist_ok=True)

    # Get OpenAPI schema
    openapi_schema = app.openapi()

    # Export to JSON
    json_path = os.path.join(docs_dir, "openapi.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2, ensure_ascii=False)
    print(f"Exported OpenAPI schema to: {json_path}")

    # Try to export to YAML if pyyaml is installed
    try:
        import yaml
        yaml_path = os.path.join(docs_dir, "openapi.yaml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(openapi_schema, f, default_flow_style=False, allow_unicode=True)
        print(f"Exported OpenAPI schema to: {yaml_path}")
    except ImportError:
        print("Note: Install 'pyyaml' to also export YAML format")

    # Print summary
    paths = openapi_schema.get("paths", {})
    endpoint_count = sum(len(methods) for methods in paths.values())
    print("\nAPI Summary:")
    print(f"  Title: {openapi_schema.get('info', {}).get('title', 'Unknown')}")
    print(f"  Version: {openapi_schema.get('info', {}).get('version', 'Unknown')}")
    print(f"  Endpoints: {endpoint_count}")
    print(f"  Paths: {len(paths)}")


if __name__ == "__main__":
    export_openapi()
