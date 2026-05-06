#!/usr/bin/env python3
"""
QPrisma Data Reset Script
=========================
Wipes all data from Blob Storage, Neo4j, and PostgreSQL
so you can start fresh with a new knowledge graph technique.

Usage:
    # Dry-run (default) — shows what would be deleted
    python scripts/reset_all_data.py

    # Execute the reset with confirmation prompt
    python scripts/reset_all_data.py --execute

    # Skip specific stores
    python scripts/reset_all_data.py --execute --skip-blob

    # Non-interactive (CI) — skip confirmation prompt
    python scripts/reset_all_data.py --execute --yes
"""

from __future__ import annotations

import argparse
import sys
import os
import time

# Ensure backend is importable when running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


# ---------------------------------------------------------------------------
# Colour helpers (degrade gracefully on Windows without colorama)
# ---------------------------------------------------------------------------

def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_USE_COLOR = _supports_color()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def red(t: str) -> str:
    return _c("91", t)


def green(t: str) -> str:
    return _c("92", t)


def yellow(t: str) -> str:
    return _c("93", t)


def cyan(t: str) -> str:
    return _c("96", t)


def bold(t: str) -> str:
    return _c("1", t)


# ---------------------------------------------------------------------------
# Store reset functions
# ---------------------------------------------------------------------------

def reset_postgresql(dry_run: bool) -> bool:
    """Truncate all QPrisma tables (CASCADE), preserving the schema."""
    from core.config import settings

    header = "PostgreSQL"
    print(f"\n{'─' * 60}")
    print(bold(f"  {header}"))
    print(f"{'─' * 60}")

    try:
        from sqlalchemy import create_engine, text, inspect

        engine = create_engine(settings.postgres.database_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        if not tables:
            print(green("  No tables found — nothing to reset."))
            return True

        print(f"  Database URL : {cyan(_mask_url(settings.postgres.database_url))}")
        print(f"  Tables found : {', '.join(tables)}")

        if dry_run:
            print(yellow("  [DRY-RUN] Would TRUNCATE all tables with CASCADE."))
            return True

        with engine.begin() as conn:
            for table in tables:
                conn.execute(text(f'TRUNCATE TABLE "{table}" CASCADE'))
                print(f"  ✓ Truncated {cyan(table)}")

        print(green("  PostgreSQL reset complete."))
        return True

    except Exception as e:
        print(red(f"  ✗ PostgreSQL reset failed: {e}"))
        return False


def reset_neo4j(dry_run: bool) -> bool:
    """Delete all nodes and relationships from the Neo4j knowledge graph."""
    from core.config import settings

    header = "Neo4j Knowledge Graph"
    print(f"\n{'─' * 60}")
    print(bold(f"  {header}"))
    print(f"{'─' * 60}")

    try:
        from neo4j import GraphDatabase

        uri = settings.neo4j.uri
        user = settings.neo4j.user
        password = settings.neo4j.password
        database = settings.neo4j.database

        print(f"  URI      : {cyan(uri)}")
        print(f"  Database : {cyan(database)}")

        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()

        # Count nodes and relationships
        with driver.session(database=database) as session:
            node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

        print(f"  Nodes    : {node_count:,}")
        print(f"  Rels     : {rel_count:,}")

        if node_count == 0 and rel_count == 0:
            print(green("  Graph is already empty — nothing to reset."))
            driver.close()
            return True

        if dry_run:
            print(yellow("  [DRY-RUN] Would DELETE all nodes and relationships."))
            driver.close()
            return True

        # Delete in batches to avoid memory issues on large graphs
        with driver.session(database=database) as session:
            deleted = 0
            while True:
                result = session.run(
                    "MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(*) AS c"
                )
                batch = result.single()["c"]
                if batch == 0:
                    break
                deleted += batch
                print(f"  … deleted {deleted:,} nodes so far")

        # Drop all indexes and constraints so schema is clean
        with driver.session(database=database) as session:
            constraints = session.run("SHOW CONSTRAINTS").data()
            for c in constraints:
                name = c.get("name")
                if name:
                    safe_name = name.replace("`", "``")
                    session.run(f"DROP CONSTRAINT `{safe_name}` IF EXISTS")
                    print(f"  ✓ Dropped constraint {cyan(name)}")

            indexes = session.run("SHOW INDEXES").data()
            for idx in indexes:
                name = idx.get("name")
                idx_type = idx.get("type", "")
                # Skip internal lookup indexes
                if name and idx_type != "LOOKUP":
                    safe_name = name.replace("`", "``")
                    session.run(f"DROP INDEX `{safe_name}` IF EXISTS")
                    print(f"  ✓ Dropped index {cyan(name)}")

        driver.close()
        print(green(f"  Neo4j reset complete — {deleted:,} nodes removed."))
        return True

    except Exception as e:
        print(red(f"  ✗ Neo4j reset failed: {e}"))
        return False


def reset_blob_storage(dry_run: bool) -> bool:
    """Delete all blobs in the QPrisma media container."""
    from core.config import settings

    header = "Azure Blob Storage"
    print(f"\n{'─' * 60}")
    print(bold(f"  {header}"))
    print(f"{'─' * 60}")

    conn_str = settings.azure.storage_connection_string
    container_name = settings.azure.storage_container_name

    if not conn_str:
        print(yellow("  AZURE_STORAGE_CONNECTION_STRING not set — skipping."))
        return True

    try:
        from azure.storage.blob import BlobServiceClient

        blob_service = BlobServiceClient.from_connection_string(conn_str)
        container = blob_service.get_container_client(container_name)

        # Count blobs first
        blobs = list(container.list_blobs())
        total = len(blobs)

        print(f"  Container : {cyan(container_name)}")
        print(f"  Blobs     : {total:,}")

        if total == 0:
            print(green("  Container is already empty — nothing to reset."))
            return True

        # Show breakdown by prefix
        prefixes: dict[str, int] = {}
        for blob in blobs:
            prefix = blob.name.split("/")[0] if "/" in blob.name else "(root)"
            prefixes[prefix] = prefixes.get(prefix, 0) + 1
        for prefix, count in sorted(prefixes.items(), key=lambda x: -x[1]):
            print(f"    {prefix:30s} {count:>6,} blobs")

        if dry_run:
            print(yellow(f"  [DRY-RUN] Would DELETE {total:,} blobs."))
            return True

        deleted = 0
        start = time.time()
        for blob in blobs:
            container.delete_blob(blob.name)
            deleted += 1
            if deleted % 100 == 0 or deleted == total:
                elapsed = time.time() - start
                rate = deleted / elapsed if elapsed > 0 else 0
                print(
                    f"  … {deleted:,}/{total:,} deleted"
                    f"  ({rate:.0f} blobs/s)",
                    end="\r",
                )
        print()  # newline after progress

        print(green(f"  Blob Storage reset complete — {deleted:,} blobs removed."))
        return True

    except Exception as e:
        print(red(f"  ✗ Blob Storage reset failed: {e}"))
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask_url(url: str) -> str:
    """Mask password in a connection URL for display."""
    if "@" in url and "://" in url:
        scheme_rest = url.split("://", 1)
        if len(scheme_rest) == 2:
            creds_host = scheme_rest[1].split("@", 1)
            if len(creds_host) == 2 and ":" in creds_host[0]:
                user = creds_host[0].split(":")[0]
                return f"{scheme_rest[0]}://{user}:****@{creds_host[1]}"
    return url


def confirm_reset(stores: list[str]) -> bool:
    """Ask the user to type 'RESET' to confirm."""
    print()
    print(red(bold("  ⚠  WARNING — DESTRUCTIVE OPERATION  ⚠")))
    print()
    print(f"  This will permanently delete ALL data from: {', '.join(stores)}")
    print(f"  This action {bold('cannot be undone')}.")
    print()
    try:
        answer = input(f"  Type {bold('RESET')} to confirm: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n  Aborted.")
        return False
    return answer == "RESET"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset all QPrisma data stores for a fresh start.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the reset (default is dry-run).",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip the interactive confirmation prompt.",
    )
    parser.add_argument("--skip-postgres", action="store_true", help="Skip PostgreSQL reset.")
    parser.add_argument("--skip-neo4j", action="store_true", help="Skip Neo4j reset.")
    parser.add_argument("--skip-blob", action="store_true", help="Skip Blob Storage reset.")
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Override the production environment safety guard.",
    )

    args = parser.parse_args()
    dry_run = not args.execute

    print()
    print(bold("╔══════════════════════════════════════════════════════════╗"))
    print(bold("║           QPrisma — Full Data Reset Utility             ║"))
    print(bold("╚══════════════════════════════════════════════════════════╝"))

    # Block execution against production unless explicitly overridden
    from core.config import settings as _settings
    env = getattr(getattr(_settings, "app", None), "environment", "development")
    if env in ("production", "staging") and not args.allow_production:
        print(red(f"\n  ✗ Refusing to run against '{env}' environment."))
        print(red("    Pass --allow-production to override this safety guard.\n"))
        sys.exit(1)

    if dry_run:
        print(yellow("\n  Mode: DRY-RUN (pass --execute to perform the reset)\n"))
    else:
        print(red("\n  Mode: EXECUTE — data will be permanently deleted\n"))

    # Determine which stores to reset
    stores: list[tuple[str, callable]] = []
    if not args.skip_postgres:
        stores.append(("PostgreSQL", reset_postgresql))
    if not args.skip_neo4j:
        stores.append(("Neo4j", reset_neo4j))
    if not args.skip_blob:
        stores.append(("Blob Storage", reset_blob_storage))
    if not stores:
        print(yellow("  All stores skipped — nothing to do."))
        sys.exit(0)

    print(f"  Stores to reset: {', '.join(name for name, _ in stores)}")

    # Confirmation gate (only in execute mode)
    if not dry_run and not args.yes:
        if not confirm_reset([name for name, _ in stores]):
            print(yellow("\n  Reset cancelled."))
            sys.exit(1)

    # Run each store reset
    results: dict[str, bool] = {}
    for name, fn in stores:
        results[name] = fn(dry_run)

    # Summary
    print(f"\n{'═' * 60}")
    print(bold("  Summary"))
    print(f"{'═' * 60}")
    for name, ok in results.items():
        status = green("✓ OK") if ok else red("✗ FAILED")
        print(f"  {name:20s} {status}")

    failed = [n for n, ok in results.items() if not ok]
    if failed:
        print(red(f"\n  {len(failed)} store(s) failed: {', '.join(failed)}"))
        sys.exit(1)
    elif dry_run:
        print(yellow("\n  Dry-run complete. Pass --execute to perform the reset."))
    else:
        print(green("\n  All stores reset successfully. You're starting fresh! 🚀"))


if __name__ == "__main__":
    main()
