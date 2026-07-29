#!/usr/bin/env python
"""Apply pending SQL migrations to the configured Postgres database.

Forward-only: corrections are new migrations, never edits to applied ones.
A checksum mismatch on an already-applied migration is a hard failure.
See docs/DATA_SPEC.md #7.

Usage:
    python scripts/apply_migrations.py --database-url postgresql://...
    python scripts/apply_migrations.py   # uses DATABASE_URL env var
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = _REPO_ROOT / "core" / "db" / "migrations"

_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version      text PRIMARY KEY,
  applied_at   timestamptz NOT NULL DEFAULT now(),
  checksum     text NOT NULL
);
"""


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def apply_migrations(database_url: str) -> None:
    migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migrations:
        print("No migration files found.")
        return

    with psycopg.connect(database_url, autocommit=False) as conn:
        conn.execute(_BOOTSTRAP_SQL)
        conn.commit()

        applied = {
            row[0]: row[1]
            for row in conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
        }

        for migration in migrations:
            version = migration.stem
            sql = migration.read_text(encoding="utf-8")
            checksum = _checksum(sql)

            if version in applied:
                if applied[version] != checksum:
                    print(
                        f"FATAL: {version} has already been applied but its checksum "
                        f"no longer matches. Migrations are forward-only — never edit "
                        f"an applied migration; write a new one instead.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                print(f"skip  {version} (already applied)")
                continue

            print(f"apply {version}")
            try:
                # schema_migrations is already committed by the bootstrap above, so
                # this migration's own DDL and its ledger row commit atomically.
                conn.execute(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                    (version, checksum),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    print("Done.")


def main() -> None:
    load_dotenv(_REPO_ROOT / ".env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Postgres connection string. Defaults to $DATABASE_URL or .env.",
    )
    args = parser.parse_args()

    if not args.database_url:
        print(
            "No database URL found.\n"
            "Set DATABASE_URL in a .env file at the repo root (copy .env.example), "
            "or pass --database-url.",
            file=sys.stderr,
        )
        sys.exit(1)

    apply_migrations(args.database_url)


if __name__ == "__main__":
    main()
